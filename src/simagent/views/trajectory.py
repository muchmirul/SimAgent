"""Trajectory view: margin vs journal step — the convergence plot.

Reads committed steps only (imagination is not motion). Shows what the
session's acts did to the margin over time; the zero line is the boundary
between HOLDS and FAILS.
"""
from __future__ import annotations

import numpy as np

from . import _style


def render_trajectory(steps: list[dict], out_path, title: str | None = None) -> tuple[str, dict]:
    xs, ys, tools = [], [], []
    for entry in steps:
        if entry.get("mode", "commit") != "commit" or entry.get("tool") is None:
            continue
        check = entry.get("check") or {}
        margin = check.get("margin")
        if margin is None:
            continue
        xs.append(entry.get("step", 0))
        ys.append(float(margin))
        tools.append(entry.get("tool"))
    if not xs:
        raise ValueError("no margin-valued committed steps to plot")

    fig, ax = _style.figure(figsize=(6.4, 3.2))
    ax.axhline(0.0, color=_style.ZERO_CONTOUR, linewidth=1.0)
    ax.plot(xs, ys, color="#6ab0f3", linewidth=1.4, marker="o", markersize=4)
    for x, y, t in zip(xs, ys, tools):
        if t in ("hunt", "refine", "certify", "exhaust"):
            ax.annotate(t, (x, y), color=_style.DIM, fontsize=7,
                        textcoords="offset points", xytext=(4, 6))
    ax.set_xlabel("journal step", color=_style.DIM, fontsize=9)
    ax.set_ylabel("margin", color=_style.DIM, fontsize=9)

    meta = {
        "kind": "trajectory",
        "points": len(xs),
        "first_margin": ys[0],
        "final_margin": ys[-1],
        "crossed_zero": bool(min(ys) < 0 < max(ys)) if ys else False,
    }
    path = _style.finish(fig, out_path, title=title or "margin trajectory")
    return path, meta
