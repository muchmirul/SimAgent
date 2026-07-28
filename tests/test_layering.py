"""Layering guard: core/ is the pure atom layer (plan.md §6).

core may import: stdlib, numpy, sympy, and the sandbox math leaves
(certify/geometry/scene). It must never import the web/llm/visualize/agent
layers or any UI/provider dependency — that is what keeps the atoms reusable
under any runtime (CLI, web, pi) forever.
"""
import ast
from pathlib import Path

CORE = Path(__file__).parent.parent / "src" / "simagent" / "core"

ALLOWED_ABSOLUTE = (
    "numpy", "sympy", "itertools", "dataclasses", "math", "abc", "typing",
    "json", "time", "pathlib", "fractions", "collections", "enum", "hashlib",
    "copy", "ast", "re", "__future__",
)
ALLOWED_RELATIVE_L2 = ("sandbox", "sandbox.certify", "sandbox.geometry", "sandbox.scene")
FORBIDDEN_MARKERS = ("web", "llm", "visualize", "agent", "matplotlib", "fastapi", "anthropic")


def test_core_layer_is_pure():
    assert CORE.is_dir(), "core package must exist"
    problems = []
    for path in sorted(CORE.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in ALLOWED_ABSOLUTE:
                        problems.append(f"{path.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if node.level == 0:
                    if mod.split(".")[0] not in ALLOWED_ABSOLUTE:
                        problems.append(f"{path.name}: from {mod} import ...")
                elif node.level == 1:
                    continue  # within core — always fine
                elif node.level == 2:
                    if mod not in ALLOWED_RELATIVE_L2 and not mod.startswith("sandbox."):
                        problems.append(f"{path.name}: from ..{mod} import ...")
                else:
                    problems.append(f"{path.name}: relative import above the package")
    assert not problems, "core layering violations:\n" + "\n".join(problems)


def test_core_never_names_forbidden_layers():
    for path in sorted(CORE.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            for m in mods:
                for marker in FORBIDDEN_MARKERS:
                    assert not (m == marker or m.endswith("." + marker) or m.startswith(marker + ".")), (
                        f"{path.name} imports forbidden layer {m!r}"
                    )
