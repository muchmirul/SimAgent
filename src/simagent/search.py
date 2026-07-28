"""Automated search over the sandbox: falsify a forall, or witness an exists.

Strategy:
  1. Random sampling over the declared domain (constraint-rejected).
  2. If the spec exposes a continuous margin, anneal the most promising sample
     to push the margin decisively past 0 (a robustly-violating instance
     survives rationalization far better than a boundary-hugging one).
  3. Rationalize the candidate and re-decide with exact arithmetic
     (spec.certify) — only then do we call it a certificate.
"""
from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field

import numpy as np

from .core.claim import Claim, NativeCheckResult, NativeEngine
from .core.space import sample_vars
from .sandbox import certify as certify_mod


@dataclass
class SearchReport:
    verdict: str  # counterexample | witness | no_counterexample | no_witness
    certified: bool | None  # None = no certify code / not attempted
    trials: int
    valid_trials: int
    refine_steps: int
    seed: int
    witness: dict | None  # var name -> nested float lists
    witness_check: dict | None  # CheckResult of the witness
    exact_witness: dict | None  # var name -> 'p/q' string arrays (if certified)
    margin_min: float | None
    margin_max: float | None
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)


def _safe_check(comp: NativeEngine, vars: dict) -> NativeCheckResult | None:
    try:
        if not comp.valid(**vars):
            return None
        return comp.check(**vars)
    except Exception:  # noqa: BLE001 - degenerate numerics count as invalid samples
        return None


def _refine(
    comp: NativeEngine,
    spec: Claim,
    start: dict[str, np.ndarray],
    rng: np.random.Generator,
    minimize: bool,
    steps: int = 500,
    sigma0: float = 0.15,
    goal: float = 0.08,
) -> tuple[dict[str, np.ndarray], NativeCheckResult, int]:
    """Hill-climb the margin (down for counterexamples, up for witnesses)."""
    spaces = spec.spaces  # the annealing move is Space.perturb (input boundary)
    cur = {k: np.array(v, dtype=float) for k, v in start.items()}
    cur_res = _safe_check(comp, cur)
    assert cur_res is not None and cur_res.margin is not None
    sigma = sigma0
    used = 0
    for i in range(steps):
        used = i + 1
        cand = {k: spaces[k].perturb(rng, v, sigma) for k, v in cur.items()}
        res = _safe_check(comp, cand)
        if res is not None and res.margin is not None:
            better = res.margin < cur_res.margin if minimize else res.margin > cur_res.margin
            if better:
                cur, cur_res = cand, res
        sigma *= 0.995
        if minimize and cur_res.margin <= -goal:
            break
        if not minimize and cur_res.margin >= goal:
            break
    return cur, cur_res, used


def _try_certify(
    comp: NativeEngine, spec: Claim, vars: dict[str, np.ndarray], want_holds: bool
) -> tuple[bool | None, dict | None, dict[str, np.ndarray] | None, list[str]]:
    """Rationalize -> confirm numerically -> decide exactly.

    Returns (certified, exact_repr, rationalized_float_vars, notes).
    """
    notes: list[str] = []
    if not comp.has_certify:
        notes.append("no exact certifier on the Claim; result is numeric-only")
        return None, None, None, notes
    for max_den in (16, 64, 256, 1024):
        exact = {k: certify_mod.rationalize_array(v, max_den=max_den) for k, v in vars.items()}
        # Snapping must not reshape: rationalize_array widens a 1-D vector to a
        # (1, n) row matrix for the exact geometry helpers, so restore each
        # variable's sampled shape before re-running the numeric check.
        floats = {
            k: np.asarray(certify_mod.to_float(e), dtype=float).reshape(np.shape(vars[k]))
            for k, e in exact.items()
        }
        num = _safe_check(comp, floats)
        if num is None or num.holds != want_holds:
            continue  # snapping crossed the boundary; retry with finer rationals
        try:
            holds_exact = comp.certify(**exact)
        except Exception as e:  # noqa: BLE001
            notes.append(f"certify raised ({type(e).__name__}: {e}); numeric-only result")
            return None, None, None, notes
        if holds_exact == want_holds:
            notes.append(f"certified with denominators <= {max_den}")
            return True, {k: certify_mod.exact_repr(e) for k, e in exact.items()}, floats, notes
        notes.append(f"exact check disagreed at max_den={max_den}; trying finer rationals")
    notes.append("could not certify a rationalized instance; result is numeric-only")
    return False, None, None, notes


EXHAUSTION_CAP = 2_000_000


def case_count(spec: Claim) -> int | None:
    """Total number of cases in the domain, or None if it is not finite.

    Returns 0 for an empty or inverted (low > high) integer range.
    """
    total = 1
    for space in spec.spaces.values():
        n = space.count()
        if n is None:
            return None
        if n == 0:
            return 0
        total *= n
    return total


def int_domain_exact(spec: Claim) -> bool:
    """True iff every integer input stays within the exact-float range."""
    return all(space.int_exact for space in spec.spaces.values())


def exhaustible(spec: Claim, cap: int = EXHAUSTION_CAP) -> bool:
    n = case_count(spec)
    return n is not None and 0 < n <= cap


def run_exhaustive(spec: Claim, cap: int = EXHAUSTION_CAP) -> SearchReport:
    """Check EVERY case of a finite integer domain — proof by exhaustion.

    Unlike run_search this is definitive (within the declared domain):
    'holds_on_domain' / 'no_witness_on_domain' mean every single case was
    checked. Constraint-invalid cases are excluded from the claim and counted.
    """
    total = case_count(spec)
    if total is None:
        raise ValueError(f"{spec.id}: domain is not finite (all vars must be kind='int')")
    if total == 0:
        raise ValueError(f"{spec.id}: empty or inverted integer domain (low > high?)")
    if total > cap:
        raise ValueError(f"{spec.id}: {total} cases exceeds the exhaustion cap {cap}")

    comp = spec.compiled()
    hunting_violation = spec.quantifier == "forall"
    int_exact = int_domain_exact(spec)
    # Basis for calling the enumeration a proof: exact integer evaluation (safe
    # bounds) OR a Claim-provided exact certifier we can invoke per hit.
    exact_note = (
        "float64 evaluation of integer-valued cases (exact: all inputs within "
        f"|x| <= 2^40, so integer arithmetic below 2^53 is exact)"
        if int_exact
        else "float64 evaluation (inputs exceed the exact-integer guard; "
        "verdict is NOT certified unless an exact certifier re-decides it)"
    )

    spaces = spec.spaces

    # A space that enumerates only up to symmetry covers the domain ONLY if the
    # claim cannot tell the symmetric copies apart. Spot-check it and refuse on
    # a violation: skipping real cases while calling the result exhaustive
    # would be the worst kind of false verdict.
    for name, space in spaces.items():
        if not getattr(space, "up_to_iso", False):
            continue
        rng = np.random.default_rng(0)

        def one(value, _name=name):
            res = _safe_check(comp, {_name: value})
            return None if res is None else (res.holds, res.margin)

        if not space.respects_relabelling(one, rng):
            raise ValueError(
                f"{spec.id}: {name} enumerates up to symmetry, but the claim's "
                "check distinguishes relabelled copies, so the reduced "
                "enumeration would skip real cases"
            )

    def var_cases(v):
        return spaces[v.name].enumerate_cases()

    names = [v.name for v in spec.domain]
    checked = 0
    skipped = 0
    errored = 0
    for assignment in itertools.product(*(var_cases(v) for v in spec.domain)):
        vars = dict(zip(names, assignment))
        try:
            valid = comp.valid(**vars)
        except Exception:  # noqa: BLE001
            valid = False
        if not valid:
            skipped += 1
            continue
        try:
            res = comp.check(**vars)
        except Exception:  # noqa: BLE001 - a case whose check crashes is NOT a checked case
            errored += 1
            continue
        checked += 1
        hit = (not res.holds) if hunting_violation else res.holds
        if hit:
            want_holds = not hunting_violation
            certified, exact_repr_vars, _floats, notes = _try_certify(
                comp, spec, vars, want_holds
            )
            # Fail closed: only claim certified via an exact certifier, or by
            # the integer-exactness of the domain. Never default to True.
            if certified is None:
                certified = int_exact
                notes.append(
                    "no exact certifier; certified by integer-exact evaluation"
                    if int_exact
                    else "no exact certifier and inputs exceed the exact-integer guard: NOT certified"
                )
            return SearchReport(
                verdict="counterexample" if hunting_violation else "witness",
                certified=certified,
                trials=total,
                valid_trials=checked,
                refine_steps=0,
                seed=0,
                witness={k: np.asarray(v).tolist() for k, v in vars.items()},
                witness_check={"holds": res.holds, "margin": res.margin, "data": res.data},
                exact_witness=exact_repr_vars
                or ({k: _int_repr(v) for k, v in vars.items()} if int_exact else None),
                margin_min=None,
                margin_max=None,
                notes=notes + [f"found by complete enumeration ({checked} cases checked)"],
            )
    if errored:
        # Some cases could not be decided -> the ∀/∃ claim is NOT settled.
        return SearchReport(
            verdict="no_counterexample" if hunting_violation else "no_witness",
            certified=None,
            trials=total,
            valid_trials=checked,
            refine_steps=0,
            seed=0,
            witness=None,
            witness_check=None,
            exact_witness=None,
            margin_min=None,
            margin_max=None,
            notes=[
                f"INCOMPLETE exhaustion: {errored} of {total} cases raised in check() "
                f"and could not be decided; {checked} passed, {skipped} excluded by the "
                "constraint. Not a proof — fix the check or narrow the domain."
            ],
        )
    return SearchReport(
        verdict="holds_on_domain" if hunting_violation else "no_witness_on_domain",
        certified=int_exact,
        trials=total,
        valid_trials=checked,
        refine_steps=0,
        seed=0,
        witness=None,
        witness_check=None,
        exact_witness=None,
        margin_min=None,
        margin_max=None,
        notes=[
            f"complete enumeration: all {checked} valid cases checked "
            f"({skipped} excluded by the constraint); {exact_note}"
        ],
    )


def _int_repr(arr: np.ndarray) -> object:
    """Exact-string form of an integer case, any ndim (d-generic)."""
    a = np.asarray(arr)
    if a.ndim == 0:
        return str(int(a))
    if a.ndim == 1:
        return [[str(int(x)) for x in a]]
    if a.ndim == 2:
        return [[str(int(x)) for x in row] for row in a]
    return [_int_repr(sub) for sub in a]


def refine_candidate(
    spec: Claim,
    start_vars: dict[str, np.ndarray],
    steps: int = 500,
    minimize: bool | None = None,
    seed: int = 0,
) -> tuple[dict[str, np.ndarray], NativeCheckResult, int]:
    """Public annealing entry point (used by interactive play).

    Pushes the margin down for forall specs (toward a counterexample) or up
    for exists specs (toward a witness). Stays inside the declared domain.
    """
    comp = spec.compiled()
    if minimize is None:
        minimize = spec.quantifier == "forall"
    res = _safe_check(comp, start_vars)
    if res is None:
        raise ValueError("starting configuration is invalid or degenerate")
    if res.margin is None:
        raise ValueError("this Claim has a discrete check (no margin); refine unavailable")
    rng = np.random.default_rng(seed)
    return _refine(comp, spec, start_vars, rng, minimize=minimize, steps=steps)


def certify_candidate(
    spec: Claim, vars: dict[str, np.ndarray]
) -> tuple[NativeCheckResult, bool | None, dict | None, list[str]]:
    """Exact-arithmetic verdict for one configuration (used by interactive play).

    Returns (numeric check, certified, exact witness repr, notes) where
    `certified` confirms the numeric holds/fails verdict in exact rationals.
    """
    comp = spec.compiled()
    res = _safe_check(comp, vars)
    if res is None:
        raise ValueError("configuration is invalid or degenerate; cannot certify")
    certified, exact, _floats, notes = _try_certify(comp, spec, vars, want_holds=res.holds)
    return res, certified, exact, notes


def run_search(
    spec: Claim,
    trials: int = 2000,
    seed: int = 0,
    refine: bool = True,
) -> SearchReport:
    comp = spec.compiled()
    rng = np.random.default_rng(seed)
    hunting_violation = spec.quantifier == "forall"

    best_vars: dict | None = None
    best_res: NativeCheckResult | None = None
    found_vars: dict | None = None
    found_res: NativeCheckResult | None = None
    valid = 0
    m_min: float | None = None
    m_max: float | None = None

    for _ in range(trials):
        vars = sample_vars(rng, spec)
        res = _safe_check(comp, vars)
        if res is None:
            continue
        valid += 1
        if res.margin is not None:
            m_min = res.margin if m_min is None else min(m_min, res.margin)
            m_max = res.margin if m_max is None else max(m_max, res.margin)
        hit = (not res.holds) if hunting_violation else res.holds
        if hit and found_vars is None:
            found_vars, found_res = vars, res
        if res.margin is not None:
            better = (
                best_res is None
                or best_res.margin is None
                or (res.margin < best_res.margin if hunting_violation else res.margin > best_res.margin)
            )
            if better:
                best_vars, best_res = vars, res
        if found_vars is not None and res.margin is None:
            break  # discrete check: first hit is as good as any

    refine_steps = 0
    notes: list[str] = []

    # Anneal toward a robust instance when we have a continuous margin.
    seed_vars = found_vars if found_vars is not None else best_vars
    seed_res = found_res if found_res is not None else best_res
    if refine and seed_vars is not None and seed_res is not None and seed_res.margin is not None:
        refined_vars, refined_res, refine_steps = _refine(
            comp, spec, seed_vars, rng, minimize=hunting_violation
        )
        hit = (not refined_res.holds) if hunting_violation else refined_res.holds
        if hit:
            found_vars, found_res = refined_vars, refined_res

    if found_vars is None:
        verdict = "no_counterexample" if hunting_violation else "no_witness"
        return SearchReport(
            verdict=verdict,
            certified=None,
            trials=trials,
            valid_trials=valid,
            refine_steps=refine_steps,
            seed=seed,
            witness=None,
            witness_check=None,
            exact_witness=None,
            margin_min=m_min,
            margin_max=m_max,
            notes=[f"no {'violation' if hunting_violation else 'witness'} in {valid} valid samples"],
        )

    want_holds = not hunting_violation
    certified, exact_repr_vars, rational_floats, cert_notes = _try_certify(
        comp, spec, found_vars, want_holds
    )
    notes.extend(cert_notes)
    if rational_floats is not None:
        found_vars = rational_floats  # prefer the certified rational instance
        recheck = _safe_check(comp, found_vars)
        if recheck is not None:
            found_res = recheck

    return SearchReport(
        verdict="counterexample" if hunting_violation else "witness",
        certified=certified,
        trials=trials,
        valid_trials=valid,
        refine_steps=refine_steps,
        seed=seed,
        witness={k: np.asarray(v).tolist() for k, v in found_vars.items()},
        witness_check={
            "holds": found_res.holds,
            "margin": found_res.margin,
            "data": found_res.data,
        }
        if found_res
        else None,
        exact_witness=exact_repr_vars,
        margin_min=m_min,
        margin_max=m_max,
        notes=notes,
    )
