"""Packaging: the tool has to work on a machine that is not this one.

Two things are checked here. The package must be importable and runnable
without the repo checkout, and Lean must be genuinely OPTIONAL: a user
without the toolchain gets weaker verdicts, never wrong ones and never a
crash.
"""
import os
import subprocess
import sys

import pytest

from simagent import lean_check
from simagent.library import get
from simagent.pipeline import run_problem


def test_lean_can_be_switched_off_deliberately(monkeypatch):
    """The no-Lean path must be reachable on a machine that HAS Lean, or it
    is never exercised and quietly rots."""
    monkeypatch.setenv("SIMAGENT_LEAN", "off")
    assert lean_check.lean_binary() is None
    assert lean_check.lean_available() is False
    report = lean_check.check_source("theorem t : True := trivial\n#print axioms t\n")
    assert report["available"] is False
    assert report["ok"] is False and report["axiom_clean"] is False


def test_a_counterexample_still_certifies_without_lean(monkeypatch, tmp_path):
    """Exact rational arithmetic does not need Lean, so a disproof survives
    at full strength minus the kernel stamp."""
    monkeypatch.setenv("SIMAGENT_LEAN", "off")
    out = run_problem(get("sum-of-squares-vs-linear"), tmp_path, trials=300,
                      seed=3, render_manim=False)
    assert out.report.verdict == "counterexample"
    assert out.report.certified is True
    assert out.proof is not None
    assert out.proof.verified_by == "sandbox"  # not sandbox+lean
    assert "DISPROVED" in (tmp_path / "answer.md").read_text()


def test_a_true_claim_is_not_stamped_without_lean(monkeypatch, tmp_path):
    """Deductive means Lean-or-nothing, with no exception for a missing
    toolchain. Better to say 'evidence' than to invent a proof."""
    monkeypatch.setenv("SIMAGENT_LEAN", "off")
    out = run_problem(get("positive-quadratic"), tmp_path, trials=300, seed=1,
                      render_manim=False)
    assert out.proof is None
    answer = (tmp_path / "answer.md").read_text()
    assert "evidence for the conjecture, not a proof" in answer
    assert "PROVED" not in answer


def test_the_console_script_runs_outside_the_checkout(tmp_path):
    """Installed users do not stand in the repo root."""
    proc = subprocess.run(
        [sys.executable, "-m", "simagent.cli", "list"],
        capture_output=True, text=True, cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": ""},
    )
    assert proc.returncode == 0, proc.stderr
    assert "circumcenter-in-triangle" in proc.stdout


def test_declared_dependencies_cover_what_is_imported():
    """A dependency used but not declared installs fine here and breaks for
    everyone else."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).parent.parent
    deps = tomllib.loads((root / "pyproject.toml").read_text())["project"]["dependencies"]
    declared = {d.split(">")[0].split("=")[0].split("[")[0].strip().lower() for d in deps}
    for needed in ("numpy", "sympy", "matplotlib"):
        assert needed in declared, f"{needed} is imported by the kernel but not declared"


def test_ci_runs_every_suite_this_repo_depends_on():
    """CI is the only place all three suites run together on a clean machine.

    Checked as text on purpose: no YAML parser is a dependency here, and the
    real risk is a whole job quietly disappearing, which plain strings catch.
    """
    from pathlib import Path

    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    assert workflow.is_file(), "the repo must have CI"
    text = workflow.read_text()

    # The Python kernel, both with and without Lean: the contributor rule is
    # that Lean stays optional, so the degraded path needs its own run.
    assert text.count("python -m pytest -q") == 2
    assert 'SIMAGENT_LEAN: "off"' in text
    assert "elan-init.sh" in text and "lean --version" in text

    # The known-answer test for the whole machine.
    assert "simagent bench" in text and "pass rate: 11/11" in text

    # The pi runtime, built and tested offline.
    assert "npm ci" in text and "npm run build" in text and "npm test" in text
    assert 'PI_OFFLINE: "1"' in text

    # The UI test skips without a browser, and a silent skip is how UI bugs
    # shipped green before. CI must fail instead.
    assert text.count("command -v google-chrome") == 2


def test_ci_pins_the_lean_the_kernel_was_built_against():
    """A different Lean is a different kernel; the version must be explicit."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text()
    documented = (root / "AGENTS.md").read_text()
    assert "LEAN_VERSION: v4.32.1" in workflow
    assert "4.32.1" in documented, "CI and the docs must name the same Lean"
