"""Field view: the claim's margin painted over a 2D slice of configuration
space — the Ansys lesson. The zero-contour is the theorem's shape (for the
triangle claim it is literally the circle with diameter AB: Thales).

The slice: one row of one free variable sweeps two of its coordinates over
the variable's box; every other coordinate stays at its current value. Each
grid point is evaluated with the claim's own check (constraint-invalid or
crashing points are masked). This converts search into perception: the agent
sees WHERE the claim fails, not just whether it fails here.
"""
from __future__ import annotations

import numpy as np

from . import _style


def render_field(
    spec,
    comp,
    vars: dict,
    out_path,
    var: str | None = None,
    row: int = 0,
    xi: int = 0,
    yi: int = 1,
    resolution: int = 48,
) -> tuple[str, dict]:
    spaces = spec.spaces
    if var is None:
        var = next(iter(vars))
    if var not in vars:
        raise ValueError(f"unknown variable {var!r}")
    base = np.array(vars[var], dtype=float)
    # A lone vector IS one point: slice it directly. That is the natural shape
    # for an algebraic claim, whose failure region is exactly what this paints.
    flat = base.ndim == 1
    if flat:
        base = base.reshape(1, -1)
    elif base.ndim != 2:
        raise ValueError("field view needs a point-set variable (use sweep for scalars)")
    m, d = base.shape
    if not (0 <= row < m):
        raise ValueError(f"{var} has rows 0..{m - 1}")
    if not (0 <= xi < d and 0 <= yi < d and xi != yi):
        raise ValueError(f"coordinate indices must be distinct and < {d}")
    space = spaces[var]
    lo, hi = float(space.low), float(space.high)
    xs = np.linspace(lo, hi, resolution)
    ys = np.linspace(lo, hi, resolution)
    margins = np.full((resolution, resolution), np.nan)
    work = {k: np.array(v, dtype=float) for k, v in vars.items()}
    evaluated = 0  # valid points that ran, margin or not — for honest diagnostics
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            pt = np.array(base)
            pt[row, xi] = x
            pt[row, yi] = y
            work[var] = pt.reshape(-1) if flat else pt
            try:
                if not comp.valid(**work):
                    continue
                res = comp.check(**work)
            except Exception:  # noqa: BLE001 - degenerate grid points stay masked
                continue
            evaluated += 1
            if res.margin is not None:
                margins[j, i] = res.margin

    finite = margins[np.isfinite(margins)]
    if finite.size == 0:
        if evaluated > 0:
            raise ValueError(
                "this claim's measure is discrete (no margin) — the field view "
                "paints margins; use view kind='sweep', which plots holds instead"
            )
        raise ValueError("no evaluable grid points on this slice (constraint too strict?)")
    # Zero stays the colour centre (that is the contract), but each side gets
    # its own extreme. A single symmetric scale hides the failure region
    # whenever the claim holds by a wide margin somewhere: margins from -1 to
    # +17 would paint every failing cell almost the background colour, which is
    # the one region the reader is looking for.
    lo, hi = float(finite.min()), float(finite.max())
    fig, ax = _style.figure()
    norm = _style.centered_norm(lo, hi)
    mesh = ax.pcolormesh(xs, ys, margins, cmap=_style.CMAP, norm=norm, shading="auto")
    cbar = fig.colorbar(mesh, ax=ax)
    cbar.set_label("margin  (blue: HOLDS · red: FAILS)", color=_style.DIM, fontsize=8)
    cbar.ax.tick_params(colors=_style.DIM, labelsize=7)

    has_pos = bool((finite > 0).any())
    has_neg = bool((finite < 0).any())
    zero_contour = has_pos and has_neg
    if zero_contour:
        ax.contour(xs, ys, margins, levels=[0.0], colors=[_style.ZERO_CONTOUR],
                   linewidths=1.6)
    # extrema callout + the configuration's current position on the slice
    j_min, i_min = np.unravel_index(np.nanargmin(margins), margins.shape)
    min_at = [float(xs[i_min]), float(ys[j_min])]
    ax.plot(*min_at, marker="v", color=_style.MARKER_MIN, markersize=9)
    ax.plot(base[row, xi], base[row, yi], marker="o", color=_style.MARKER_CURRENT,
            markersize=8, markeredgecolor="white")
    # the fixed points of the slice, for orientation
    others = np.delete(np.arange(m), row)
    ax.scatter(base[others, xi], base[others, yi], color="white", s=24, zorder=5)
    coord = (lambda i: f"{var}[{i}]") if flat else (lambda i: f"{var}[{row}][{i}]")
    ax.set_xlabel(coord(xi), color=_style.DIM, fontsize=9)
    ax.set_ylabel(coord(yi), color=_style.DIM, fontsize=9)
    ax.set_aspect("equal")

    meta = {
        "kind": "field",
        "var": var, "row": row, "coords": [xi, yi],
        "resolution": resolution,
        "min_margin": float(np.nanmin(margins)),
        "min_at": min_at,
        "max_margin": float(np.nanmax(margins)),
        "zero_contour": zero_contour,
        "fail_fraction": float((finite < 0).sum() / finite.size),
        "masked_fraction": float(1.0 - finite.size / margins.size),
    }
    label = (
        f"failure region covers {meta['fail_fraction']:.0%} of the slice; "
        f"min margin {meta['min_margin']:+.3g} at ({min_at[0]:.3g}, {min_at[1]:.3g})"
        + ("; zero-contour visible — the claim's boundary has a shape here"
           if zero_contour else "")
    )
    ax.set_title(label, color=_style.FG, fontsize=8)
    path = _style.finish(fig, out_path, title=f"margin field — sweep {var}[{row}]")
    return path, meta
