"""Measure — atom #5 (observable): perception as calibrated compression.

The agent (and the notebook) should never have to read raw coordinate dumps:
a measure turns kernel state into the compressed, perceptual language a
mathematician uses — "the center is OUTSIDE, beyond the face opposite vertex
2, margin −0.41". Margin convention everywhere: margin > 0 ⇔ property holds.

Measures only *describe* state; they never decide anything — the claim's
distinguished check plus the truth layer (certify/exhaust/Lean) remain the
only verdict path.
"""
from __future__ import annotations

import numpy as np

NEAR_BOUNDARY = 0.05


def _measure_lines(vars: dict, check: dict, spec) -> list[str]:
    """Predicates written by the claim's own measure, via the MEASURES registry.

    Each measure kind describes its own state, because only it knows what its
    numbers mean: `min_coord` speaks about faces of a simplex, `expr` about the
    terms of its margin. Without this the perceptual layer could only repeat
    the margin the model already had.
    """
    from .claim import MEASURES

    measure = getattr(spec, "measure", None)
    if not isinstance(measure, dict):
        return []
    entry = MEASURES.get(measure.get("kind"))
    describe = (entry or {}).get("qualitative")
    if describe is None:
        return []
    try:
        return list(describe(vars, check, measure))
    except Exception as e:  # noqa: BLE001 - a description must never break a tool call
        return [f"(could not describe this measure: {type(e).__name__}: {e})"]


def qualitative_lines(vars: dict, check: dict, spec=None) -> list[str]:
    """Human/agent-readable predicates for the current state."""
    if check.get("error"):
        return [f"degenerate configuration: {check['error']}"]
    lines: list[str] = _measure_lines(vars, check, spec)
    margin, holds = check.get("margin"), check.get("holds")
    if margin is None:
        lines.append(f"discrete claim at this configuration: holds = {holds}")
    else:
        m = float(margin)
        state = "HOLDS" if holds else "FAILS"
        distance = "close to the boundary" if abs(m) < NEAR_BOUNDARY else "clearly"
        lines.append(f"the property {state} here, {distance} (margin {m:+.4g})")
    for name, val in vars.items():
        arr = np.asarray(val, dtype=float)
        if arr.ndim == 2 and arr.shape[1] > 3:
            lines.append(
                f"{name} lives in ℝ^{arr.shape[1]} — the picture is a projection; "
                "trust the numbers over the image"
            )
    return lines


def measure_state(vars: dict, check: dict, spec=None) -> dict:
    """The agent-facing measurement of the current configuration."""
    return {
        "holds": None if check.get("error") else check.get("holds"),
        "margin": None if check.get("error") else check.get("margin"),
        "qualitative": qualitative_lines(vars, check, spec),
        "data": check.get("data") if not check.get("error") else None,
        "error": check.get("error"),
    }
