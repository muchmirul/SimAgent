"""Orchestrates one full run: spec -> search -> certify -> visualize -> answer.

Every run leaves a self-describing directory:
  spec.json  report.json  preview.png  scene.json  scene_manim.py
  answer.md  answer.tex  conjecture.lean  [proof_sketch.md]  [media/]
"""
from __future__ import annotations

import json
import platform
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import answer as answer_mod
from . import proof as proof_mod
from .core.claim import Claim, require_valid_claim
from .core.space import sample_vars
from .search import SearchReport, exhaustible, run_exhaustive, run_search
from .visualize import manim_gen, mpl


@dataclass
class PipelineResult:
    spec: Claim
    report: SearchReport
    out_dir: str
    artifacts: dict[str, str]
    proof: proof_mod.Proof | None = None
    log: list[str] = field(default_factory=list)


def _witness_or_sample(spec: Claim, report: SearchReport, seed: int) -> dict:
    comp = spec.compiled()
    if report.witness:
        return {k: np.array(v, dtype=float) for k, v in report.witness.items()}
    rng = np.random.default_rng(seed)
    for _ in range(500):
        vars = sample_vars(rng, spec)
        try:
            if comp.valid(**vars):
                return vars
        except Exception:  # noqa: BLE001
            continue
    raise RuntimeError(f"{spec.id}: could not draw a valid representative sample")


def run_problem(
    spec: Claim,
    out_dir,
    trials: int = 2000,
    seed: int = 0,
    render_manim: bool = False,
    llm_proof: bool = False,
    llm_model: str | None = None,
) -> PipelineResult:
    # Validate before creating the run directory. A malformed Claim is not a
    # warning: executing any part of it would answer an unapproved question.
    require_valid_claim(spec)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    log: list[str] = []
    t0 = time.time()

    spec.save(out / "spec.json")

    if exhaustible(spec):
        log.append(f"finite domain: checking every case (proof by exhaustion, {spec.quantifier})")
        report = run_exhaustive(spec)
    else:
        log.append(f"searching: {trials} trials, seed {seed} ({spec.quantifier})")
        report = run_search(spec, trials=trials, seed=seed)
    from . import library

    proof = proof_mod.mechanized_proof(
        spec, report, out_dir=out, spec_trusted=library.is_bundled(spec)
    )
    sos_note = None
    if proof is None:
        # Search found nothing to refute, so try to PROVE the claim outright.
        # `solve` is the batch path with no model in the loop, so the harness
        # runs the deductive instruments itself here; in agent mode the model
        # chooses which one to reach for.
        proof = proof_mod.sos_proof(
            spec, report, out_dir=out, spec_trusted=library.is_bundled(spec)
        )
        if proof is not None:
            sos_note = "no counterexample exists: sum-of-squares certificate found"
        else:
            proof = proof_mod.induction_proof(
                spec, out_dir=out, spec_trusted=library.is_bundled(spec)
            )
            if proof is not None:
                sos_note = ("no counterexample exists: proved by induction "
                            "(base case + non-decreasing step)")
    log.append(f"verdict: {answer_mod.verdict_text(report, proof)}")
    if sos_note:
        log.append(sos_note)
    if proof is not None:
        log.append(
            f"proof: {proof.method.value.replace('_', ' ')} — verified by {proof.verified_by}"
        )
        if proof.lean_report is not None and proof.verified_by != "sandbox+lean":
            log.append(f"lean certificate NOT verified: {proof.lean_report.get('output', '')[:160]}")
    else:
        log.append("proof: none — result is evidence only (a deductive method in Lean could close it)")

    comp = spec.compiled()
    scene_vars = _witness_or_sample(spec, report, seed)
    scene = comp.build_scene(**scene_vars)
    (out / "scene.json").write_text(json.dumps(scene, indent=2))

    artifacts: dict[str, str] = {
        "spec": str(out / "spec.json"),
        "scene": str(out / "scene.json"),
    }
    artifacts["preview_png"] = mpl.render_png(scene, out / "preview.png", title=spec.title)
    log.append("rendered preview.png (matplotlib)")

    scene_py = manim_gen.write_manim_scene(scene, spec.title, spec.id, out / "scene_manim.py")
    artifacts["manim_scene"] = scene_py
    if render_manim:
        ok, msg, files = manim_gen.try_render_manim(scene_py, still=True, quality="h")
        log.append(msg)
        if ok and files:
            artifacts["manim_render"] = files[-1]
    else:
        log.append("manim scene written (render skipped; pass --render-manim)")

    if llm_proof and proof is None:
        from . import llm

        try:
            attempt = llm.attempt_proof(spec, report.to_json(), model=llm_model)
            proof = proof_mod.deductive_proof(
                spec,
                method=attempt["method"],
                argument=attempt["argument"],
                lean_code=attempt.get("lean_code"),
                out_dir=out,
            )
            log.append(
                f"LLM proof attempt: {proof.method.value} — verified by {proof.verified_by}"
            )
        except Exception as e:  # noqa: BLE001 - the attempt is best-effort; the verdict stands
            log.append(f"LLM proof attempt failed: {type(e).__name__}: {e}")
    elif llm_proof:
        log.append("LLM proof attempt skipped: a mechanized proof already exists")

    artifacts.update(answer_mod.write_answers(spec, report, out, proof=proof))
    if proof is not None:
        artifacts["proof"] = proof_mod.save_proof(proof, out)
        if proof.lean_file:
            artifacts["lean_certificate"] = proof.lean_file

    from . import lean_check

    env = {
        "python": platform.python_version(),
        "manim": manim_gen.manim_available(),
        "lean_toolchain": lean_check.lean_available(),
        "elapsed_s": round(time.time() - t0, 2),
    }
    (out / "report.json").write_text(
        json.dumps(
            {
                "report": report.to_json(),
                "proof": proof.to_json() if proof else None,
                "env": env,
                "artifacts": artifacts,
                "log": log,
            },
            indent=2,
        )
    )
    artifacts["report"] = str(out / "report.json")
    return PipelineResult(
        spec=spec, report=report, out_dir=str(out), artifacts=artifacts, proof=proof, log=log
    )
