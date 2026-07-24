"""Run generated Lean sources through the Lean kernel.

Deliberately primitive: certificates target Lean 4 *core* (no Mathlib, no
Batteries, no lake project) so checking is a single `lean file.lean` process.

The acceptance rule is fail-closed and does not trust the source. A source
passes (`ok and axiom_clean`) only if ALL of:
  1. no proof-hole tokens anywhere (`sorry`, `admit`, `sorryAx`), and no
     `native_decide` (that trusts compiled code, not the kernel);
  2. lean exits 0 with no sorry warning;
  3. the source contains at least one `#print axioms <name>`, and for EVERY
     such name the output carries the exact line
     `'<name>' does not depend on any axioms`;
  4. the output contains NO `depends on axioms` line (the non-clean phrasing).

Because both the source and Lean's stdout are attacker-controlled when the
spec is untrusted, axiom-freedom is bound to the specific theorem names the
source asks to print, and the presence of ANY dependence phrase rejects — a
string that merely echoes the clean phrase cannot satisfy rule 3 for a name
that Lean actually reports as depending on axioms.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

# Tokens that would make "checked by the kernel, axiom-free" a lie.
_FORBIDDEN = ("sorry", "admit", "sorryAx", "native_decide")


def _strip_comments(src: str) -> str:
    """Remove -- line comments and /- .. -/ block comments (best effort)."""
    src = re.sub(r"/-.*?-/", " ", src, flags=re.S)
    src = re.sub(r"--[^\n]*", " ", src)
    return src


def lean_binary() -> str | None:
    env = os.environ.get("SIMAGENT_LEAN")
    if env and env.strip().lower() in ("off", "none", "0", "false"):
        # Deliberate opt-out. Lean is optional, and a user without it must get
        # honest sandbox verdicts rather than a broken run, so that path has to
        # be reachable on a machine that HAS the toolchain.
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


def check_source(source: str, workdir=None, timeout: int = 240) -> dict:
    """Check one self-contained Lean 4 core source. Fail-closed on any doubt."""
    result = {
        "available": lean_available(),
        "ok": False,
        "axiom_clean": False,
        "output": "",
    }
    binary = lean_binary()
    if binary is None:
        result["output"] = "no Lean toolchain (install elan; see README)"
        return result

    code = _strip_comments(source)
    for tok in _FORBIDDEN:
        if re.search(rf"\b{re.escape(tok)}\b", code):
            result["output"] = f"source uses forbidden construct: {tok}"
            return result

    # The names whose axiom-freedom the source explicitly asks us to confirm.
    # An empty list means nothing can be certified (axiom_clean stays False),
    # but the file may still compile cleanly (ok can be True).
    targets = re.findall(r"#print\s+axioms\s+([A-Za-z_][\w'.]*)", code)

    with tempfile.TemporaryDirectory(dir=workdir) as td:
        path = Path(td) / "Certificate.lean"
        path.write_text(source)
        try:
            proc = subprocess.run(
                [binary, str(path)], capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            result["output"] = f"lean timed out after {timeout}s"
            return result
    out = (proc.stdout or "") + (proc.stderr or "")
    result["output"] = out.strip()[-8000:]
    if proc.returncode != 0 or "sorry" in out.lower():
        return result
    result["ok"] = True

    # Any reported axiom dependence anywhere is disqualifying.
    if re.search(r"depends on axioms", out):
        return result
    # Certified only if the source named at least one target AND every named
    # target is reported axiom-free by name.
    result["axiom_clean"] = bool(targets) and all(
        f"'{name}' does not depend on any axioms" in out for name in targets
    )
    return result
