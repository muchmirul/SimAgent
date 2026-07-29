"""Run Lean 4 core certificates and fail closed on every trust boundary.

There are two source classes:

* ``check_source`` checks code emitted by SimAgent's closed generators.
* ``check_untrusted_source`` checks model-written or other externally supplied
  code inside an operating-system sandbox. If that sandbox is unavailable,
  the proof stays unverified rather than running with host access.

Both paths reject proof holes and Lean commands that can execute arbitrary I/O.
A source passes only when Lean exits cleanly and reports every named theorem as
axiom-free.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Tokens that would make "checked by the kernel, axiom-free" false.
_FORBIDDEN = ("sorry", "admit", "sorryAx", "native_decide")

# These constructs can run user code while Lean elaborates a file. UNTRUSTED
# source is searched raw, not comment-stripped: rejecting a harmless mention is
# safer than letting a crafted string confuse a best-effort comment stripper.
# GENERATED source is searched comment-stripped instead, because its only free
# text is the claim's title inside one block comment whose delimiters leangen
# has already neutralised. Scanning that raw cost a correct proof its Lean
# stamp whenever a title happened to contain an ordinary English word: a title
# reading "System of circumcenter constraints" dropped the claim from
# sandbox+lean to sandbox, which is a verdict decided by prose.
_UNSAFE_WORDS = (
    "import",
    "initialize",
    "builtin_initialize",
    "unsafe",
    "partial",
    "elab",
    "syntax",
    "macro",
    "run_tac",
    "liftIO",
    "foreign",
    "extern",
    "implemented_by",
    "IO",
    "System",
    "FilePath",
)


def _strip_comments(src: str) -> str:
    """Remove line and block comments for proof-hole checks (best effort)."""
    src = re.sub(r"/-.*?-/", " ", src, flags=re.S)
    src = re.sub(r"--[^\n]*", " ", src)
    return src


def _unsafe_source_reason(source: str) -> str | None:
    """Name the first source construct that may perform host I/O."""
    for match in re.finditer(r"#\s*([A-Za-z_][A-Za-z0-9_]*)", source):
        command = match.group(1)
        if command != "print" or not re.match(
            r"\s+axioms\b", source[match.end():]
        ):
            return f"unsafe Lean command: #{command}"
    for word in _UNSAFE_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", source):
            return f"unsafe Lean construct: {word}"
    return None


def lean_binary() -> str | None:
    env = os.environ.get("SIMAGENT_LEAN")
    if env and env.strip().lower() in ("off", "none", "0", "false"):
        return None
    if env and Path(env).exists():
        return env
    found = shutil.which("lean")
    if found:
        return found
    elan = Path.home() / ".elan" / "bin" / "lean"
    if elan.exists():
        return str(elan)
    return None


def lean_available() -> bool:
    return lean_binary() is not None


def _base_result() -> dict:
    return {
        "available": lean_available(),
        "ok": False,
        "axiom_clean": False,
        "isolated": None,
        "output": "",
    }


def _isolated_command(binary: str, temp_dir: Path) -> tuple[list[str] | None, str]:
    """Build a bubblewrap command with no network and no writable host tree."""
    if not sys.platform.startswith("linux"):
        return None, "untrusted Lean checking needs Linux bubblewrap isolation"
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        return None, "untrusted Lean checking needs bubblewrap; proof left unverified"
    try:
        prefix_run = subprocess.run(
            [binary, "--print-prefix"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"could not locate the Lean installation for isolation: {exc}"
    prefix = Path(prefix_run.stdout.strip())
    isolated_lean = Path("/opt/lean/bin/lean")
    if prefix_run.returncode != 0 or not (prefix / "bin" / "lean").is_file():
        return None, "could not locate the Lean installation for isolation"

    command = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--clearenv",
    ]
    # Lean needs only its installation and the platform runtime. No home,
    # checkout, credentials, or other user files enter the sandbox.
    for host_dir in ("/usr", "/bin", "/lib", "/lib64"):
        if Path(host_dir).exists():
            command += ["--ro-bind", host_dir, host_dir]
    command += [
        "--dir", "/opt",
        "--ro-bind", str(prefix), "/opt/lean",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--dir", "/work",
        "--bind", str(temp_dir), "/work",
        "--chdir", "/work",
        "--setenv", "HOME", "/tmp",
        "--setenv", "XDG_CACHE_HOME", "/tmp",
        "--setenv", "PATH", "/opt/lean/bin:/usr/bin:/bin",
        str(isolated_lean),
        "/work/Certificate.lean",
    ]
    return command, ""


def _check(source: str, workdir, timeout: int, *, isolate: bool) -> dict:
    result = _base_result()
    binary = lean_binary()
    if binary is None:
        result["output"] = "no Lean toolchain (install elan; see README)"
        return result

    code = _strip_comments(source)
    unsafe = _unsafe_source_reason(source if isolate else code)
    if unsafe:
        result["output"] = f"source uses {unsafe}"
        return result

    for token in _FORBIDDEN:
        if re.search(rf"\b{re.escape(token)}\b", code):
            result["output"] = f"source uses forbidden construct: {token}"
            return result

    targets = re.findall(r"#print\s+axioms\s+([A-Za-z_][\w'.]*)", code)

    try:
        with tempfile.TemporaryDirectory(dir=workdir) as td:
            temp_dir = Path(td).resolve()
            path = temp_dir / "Certificate.lean"
            path.write_text(source)
            if isolate:
                command, refusal = _isolated_command(binary, temp_dir)
                if command is None:
                    result["isolated"] = False
                    result["output"] = refusal
                    return result
            else:
                command = [binary, str(path)]
            try:
                proc = subprocess.run(
                    command,
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                result["output"] = f"Lean timed out after {timeout}s"
                return result
    except OSError as exc:
        result["output"] = f"Lean checker setup failed: {type(exc).__name__}: {exc}"
        return result

    output = (proc.stdout or "") + (proc.stderr or "")
    result["output"] = output.strip()[-8000:]
    if isolate:
        if output.lstrip().startswith("bwrap:"):
            result["isolated"] = False
            result["output"] = (
                "Lean isolation failed; proof left unverified: " + result["output"]
            )
            return result
        result["isolated"] = True
    if proc.returncode != 0 or "sorry" in output.lower():
        return result
    result["ok"] = True
    if re.search(r"depends on axioms", output):
        return result
    result["axiom_clean"] = bool(targets) and all(
        f"'{name}' does not depend on any axioms" in output for name in targets
    )
    return result


def check_source(source: str, workdir=None, timeout: int = 240) -> dict:
    """Check source emitted by SimAgent's closed Lean generators."""
    return _check(source, workdir, timeout, isolate=False)


def check_untrusted_source(source: str, workdir=None, timeout: int = 240) -> dict:
    """Check externally supplied source only inside an OS sandbox.

    A machine without working bubblewrap gets an explained refusal. It never
    falls back to executing the source with host access.
    """
    return _check(source, workdir, timeout, isolate=True)
