"""Shared view styling: ONE calibrated visual language for every margin plot.

The colormap contract (fixed repo-wide, the Ansys legend discipline):
diverging, centered at margin = 0 — red = FAILS (margin < 0), blue = HOLDS
(margin > 0). Every field/sweep view uses these constants so the agent's
vision channel is a calibrated instrument, not decoration.

Plots are drawn on a LIGHT background, matching the notebook, the matplotlib
preview and the Manim scene. One background everywhere is not a taste
decision: a picture is only evidence if the reader can see it, and a plot
tuned for one background is close to invisible on the other.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # offline; never require a display
import matplotlib.pyplot as plt  # noqa: E402

BG = "#ffffff"
FG = "#1c1e21"
DIM = "#5f6368"
CMAP = "RdBu"  # with symmetric vmin/vmax: negative margin = red, positive = blue
ZERO_CONTOUR = "#c8890a"
MARKER_CURRENT = "#137333"
MARKER_MIN = "#c5221f"


def centered_norm(lo: float, hi: float):
    """Diverging colours pinned at margin 0, each side scaled to its own range.

    The sign is what decides the claim, so 0 must stay the colour centre. But
    the two sides are rarely the same size, and a symmetric scale then spends
    almost all its contrast on the larger one. Give each half its own extreme
    and both stay readable, with 0 still exactly at the middle colour.
    """
    eps = 1e-9
    if lo >= 0.0:
        return matplotlib.colors.TwoSlopeNorm(vcenter=0.0, vmin=-eps, vmax=max(hi, eps))
    if hi <= 0.0:
        return matplotlib.colors.TwoSlopeNorm(vcenter=0.0, vmin=min(lo, -eps), vmax=eps)
    return matplotlib.colors.TwoSlopeNorm(vcenter=0.0, vmin=lo, vmax=hi)


def figure(figsize=(6.4, 5.2)):
    fig, ax = plt.subplots(figsize=figsize, facecolor=BG)
    ax.set_facecolor(BG)
    ax.tick_params(colors=DIM, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#dfe1e6")
    return fig, ax


def finish(fig, out_path, title=None):
    if title:
        fig.suptitle(title, color=FG, fontsize=11)
    fig.savefig(out_path, dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    return str(out_path)
