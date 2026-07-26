"""Sweep view: margin along ONE coordinate — the cheapest experiment.

Zero crossings are marked: each one is a boundary of the claim on this line.
Works for scalar variables too (the sum-of-odds case: margin has no meaning
there, so discrete claims sweep the holds value instead).
"""
from __future__ import annotations

import numpy as np

from ..core.space import spaces_for
from . import _style


def render_sweep(
    spec,
    comp,
    vars: dict,
    out_path,
    var: str | None = None,
    row: int | None = None,
    coord: int = 0,
    resolution: int = 120,
) -> tuple[str, dict]:
    spaces = spaces_for(spec)
    if var is None:
        var = next(iter(vars))
    if var not in vars:
        raise ValueError(f"unknown variable {var!r}")
    base = np.array(vars[var], dtype=float)
    if base.ndim > 2:
        raise ValueError("sweep supports scalar/1-D/2-D variables only")
    r = 0 if row is None else row  # the row actually swept — used everywhere below
    space = spaces[var]
    lo, hi = float(space.low), float(space.high)
    discrete = space.count() is not None
    if discrete:
        xs = np.arange(int(lo), int(hi) + 1, dtype=float)
    else:
        xs = np.linspace(lo, hi, resolution)

    margins = np.full(xs.shape, np.nan)
    holds = np.full(xs.shape, np.nan)
    work = {k: np.array(v, dtype=float) for k, v in vars.items()}
    for i, x in enumerate(xs):
        w = np.array(base)
        if w.ndim == 0:
            w = np.asarray(x, dtype=float)
        elif w.ndim == 1:
            w[coord] = x
        else:
            w[r, coord] = x
        work[var] = w
        try:
            if not comp.valid(**work):
                continue
            res = comp.check(**work)
        except Exception:  # noqa: BLE001
            continue
        holds[i] = 1.0 if res.holds else 0.0
        if res.margin is not None:
            margins[i] = res.margin

    have_margin = np.isfinite(margins).any()
    ys = margins if have_margin else holds
    if not np.isfinite(ys).any():
        raise ValueError("no evaluable points along this sweep")

    crossings: list[float] = []
    if have_margin:
        for i in range(len(xs) - 1):
            a, b = margins[i], margins[i + 1]
            if np.isfinite(a) and np.isfinite(b) and a * b < 0:
                t = a / (a - b)
                crossings.append(float(xs[i] + t * (xs[i + 1] - xs[i])))

    fig, ax = _style.figure(figsize=(6.4, 3.6))
    label = f"{var}[{r}][{coord}]" if base.ndim == 2 else (
        f"{var}[{coord}]" if base.ndim == 1 else var)
    if have_margin:
        ax.axhline(0.0, color=_style.ZERO_CONTOUR, linewidth=1.0)
        pos = np.where(np.isfinite(margins) & (margins > 0), margins, np.nan)
        neg = np.where(np.isfinite(margins) & (margins <= 0), margins, np.nan)
        ax.plot(xs, pos, color="#6ab0f3", linewidth=1.6, label="HOLDS")
        ax.plot(xs, neg, color="#e74c3c", linewidth=1.6, label="FAILS")
        for c in crossings:
            ax.axvline(c, color=_style.ZERO_CONTOUR, linewidth=0.8, linestyle=":")
        ax.set_ylabel("margin", color=_style.DIM, fontsize=9)
    else:
        ax.step(xs, holds, where="mid", color="#6ab0f3")
        ax.set_ylabel("holds (discrete)", color=_style.DIM, fontsize=9)
        ax.set_yticks([0, 1])
    ax.set_xlabel(label, color=_style.DIM, fontsize=9)
    ax.legend(loc="best", fontsize=7, facecolor=_style.BG, labelcolor=_style.FG) if have_margin else None

    finite = ys[np.isfinite(ys)]
    meta = {
        "kind": "sweep",
        "var": var, "row": r if base.ndim == 2 else None, "coord": coord,
        "discrete": bool(discrete),
        "zero_crossings": crossings,
        "min": float(np.nanmin(ys)), "max": float(np.nanmax(ys)),
        "fail_fraction": float((finite <= 0).sum() / finite.size) if have_margin
        else float((finite == 0).sum() / finite.size),
    }
    path = _style.finish(fig, out_path, title=f"margin sweep — {label}")
    return path, meta
