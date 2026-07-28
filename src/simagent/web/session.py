"""Server-side sandbox session backing the browser UI.

Holds one live configuration per loaded problem; every mutation returns the
full authoritative state (vars + scene graph + check) so the frontend stays a
dumb renderer.

Since P2 the session is a thin shell over the core atoms: state lives in a
core.entity.World (free entities from the Claim's Spaces) and every mutation
flows through core.op.apply_op. The session adds only the Claim engine's
check/scene glue and the kept-best report discipline.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..core.claim import Claim, require_valid_claim
from ..core.entity import World
from ..core.op import apply_op
from ..core.space import sample_vars
from ..search import (
    SearchReport,
    certify_candidate,
    exhaustible,
    refine_candidate,
    run_exhaustive,
    run_search,
)


_DECISIVE = frozenset(
    {"counterexample", "witness", "holds_on_domain", "no_witness_on_domain"}
)


def _report_rank(report: SearchReport | None) -> int:
    """Ordering so a later weaker search never shadows an earlier decisive one."""
    if report is None:
        return -1
    if report.verdict in _DECISIVE and report.certified:
        return 3
    if report.verdict in _DECISIVE:
        return 2
    return 1


class SandboxSession:
    def __init__(self, spec: Claim, out_dir, seed: int = 0):
        self.spec = require_valid_claim(spec)
        self.comp = self.spec.compiled()
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.spec.save(self.out / "spec.json")
        # The starting configuration. Runs that must be independent (evaluation
        # seeds) differ only here, so a fixed 0 would make every "seed" the same
        # experiment repeated.
        self.rng = np.random.default_rng(seed)
        self._hunt_seed = seed
        self.world = World()
        for name, space in self.spec.spaces.items():
            self.world.add_free(name, space)
        self.last_report: SearchReport | None = None  # most recent search result
        self.best_report: SearchReport | None = None  # strongest kept so far (never downgrades)
        self.sample()

    @property
    def vars(self) -> dict[str, np.ndarray]:
        """The free configuration (historical dict shape; state lives in World)."""
        return self.world.free_values()

    def _keep(self, report: SearchReport) -> None:
        self.last_report = report
        if _report_rank(report) > _report_rank(self.best_report):
            self.best_report = report

    # -- state ---------------------------------------------------------------

    def _check(self) -> dict:
        try:
            res = self.comp.check(**self.vars)
            return {"holds": res.holds, "margin": res.margin, "data": res.data}
        except Exception as e:  # noqa: BLE001 - degenerate configs are a UI state
            return {"error": f"{type(e).__name__}: {e}"}

    def scene(self) -> list[dict]:
        try:
            base = self.comp.build_scene(**self.vars)
        except Exception:  # noqa: BLE001
            return []
        return base + self._constructed_prims()

    def _constructed_prims(self) -> list[dict]:
        """Render agent-constructed derived entities (the sketching hand):
        every construct op becomes visible geometry, projected to <=3 coords."""
        from ..sandbox import scene as scene_mod

        prims: list[dict] = []
        for name in self.world.derived_names():
            val = self.world.values.get(name)
            if val is None:
                continue  # degenerate construction: nothing to draw
            arr = np.asarray(val, dtype=float)
            if arr.ndim == 0:
                continue  # scalars (volumes etc.) surface via measures, not geometry
            if arr.ndim == 1 and arr.size >= 2:
                prims.append(scene_mod.points([arr[:3].tolist()], color="#f2c14e",
                                              radius=0.06, name=name))
            elif arr.ndim == 2 and arr.shape[0] == 2:
                prims.append(scene_mod.segments(
                    [(arr[0][:3].tolist(), arr[1][:3].tolist())], color="#f2c14e", width=2.0))
        return prims

    def construct(self, name: str, ctor: str, args: list[str]) -> dict:
        """Add a derived entity (the agent's pencil). Returns its value/status."""
        apply_op(self.world, {"op": "construct", "name": name, "ctor": ctor,
                              "args": list(args)})
        val = self.world.values.get(name)
        return {
            "name": name, "ctor": ctor, "args": list(args),
            "value": None if val is None else np.asarray(val).tolist(),
            "degenerate": val is None,
        }

    def state(self) -> dict:
        scene = self.scene()
        (self.out / "scene.json").write_text(json.dumps(scene))
        return {
            "spec": {
                "id": self.spec.id,
                "title": self.spec.title,
                "conjecture": self.spec.conjecture,
                "latex": self.spec.latex,
                "quantifier": self.spec.quantifier,
                "has_certify": self.comp.has_certify,
                "domain": [
                    {"name": v.name, "shape": v.shape, "low": v.low, "high": v.high}
                    for v in self.spec.domain
                ],
            },
            "vars": {k: np.asarray(v).tolist() for k, v in self.vars.items()},
            "scene": scene,
            "check": self._check(),
        }

    # -- mutations -----------------------------------------------------------

    def sample(self, seed: int | None = None) -> None:
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        for _ in range(1000):
            vars = sample_vars(self.rng, self.spec)
            try:
                if self.comp.valid(**vars):
                    apply_op(self.world, {"op": "replace", "vars": vars})
                    return
            except Exception:  # noqa: BLE001
                continue
        raise RuntimeError("could not draw a valid sample (constraint too strict?)")

    def set_value(self, name: str, row: int | None, values: list[float]) -> None:
        apply_op(self.world, {"op": "set", "target": name, "row": row, "values": values})

    def refine(self, steps: int = 300) -> dict:
        vars, res, used = refine_candidate(self.spec, self.vars, steps=steps)
        apply_op(self.world, {"op": "replace", "vars": vars})
        return {"steps": used, "holds": res.holds, "margin": res.margin}

    def exhaust(self) -> dict:
        """Check EVERY case of a finite integer domain (proof by exhaustion)."""
        if not exhaustible(self.spec):
            raise ValueError(
                "domain is not finite (or too large); exhaustion needs all vars kind='int'"
            )
        report = run_exhaustive(self.spec)
        self._keep(report)
        if report.witness:
            apply_op(self.world, {"op": "replace", "vars": {
                k: np.array(v, dtype=float) for k, v in report.witness.items()}})
        return {
            "verdict": report.verdict,
            "certified": report.certified,
            "cases_checked": report.valid_trials,
            "loaded_witness": report.witness is not None,
            "notes": report.notes,
        }

    def hunt(self, trials: int = 800) -> dict:
        self._hunt_seed += 1
        report = run_search(self.spec, trials=trials, seed=self._hunt_seed)
        self._keep(report)
        if report.witness:
            apply_op(self.world, {"op": "replace", "vars": {
                k: np.array(v, dtype=float) for k, v in report.witness.items()}})
        return {
            "verdict": report.verdict,
            "certified": report.certified,
            "loaded_witness": report.witness is not None,
            "exact_witness": report.exact_witness,
            "notes": report.notes,
            "trials": report.trials,
            "valid_trials": report.valid_trials,
        }

    def certify(self) -> dict:
        res, certified, exact, notes = certify_candidate(self.spec, self.vars)
        return {
            "holds": res.holds,
            "margin": res.margin,
            "certified": certified,
            "exact": exact,
            "notes": notes,
        }
