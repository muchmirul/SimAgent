"""Always-available renderer: scene graph -> static 3D PNG via matplotlib.

This is the quick-look output; the generated Manim scene (manim_gen.py) is the
cinematic one. Both consume the same scene JSON.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection  # noqa: E402

from ..sandbox import scene as scene_mod  # noqa: E402

_BG = "#ffffff"
_FG = "#1c1e21"
_GRID = "#dde1e6"
_GRID_AXIS = "#c2c8d0"


def _reference_grid(ax, lo: float, hi: float, divisions: int = 12) -> None:
    """The xy-plane, drawn as lines, matching the browser's 3D view.

    The preview turns the axes off, which is right (ticks on a configuration
    space mean little), but it left the scene floating with no sense of scale
    or orientation. This is the same grid three.js draws, so the picture in the
    cell and the picture you get by clicking it agree.
    """
    z = 0.0 if lo <= 0.0 <= hi else lo
    ticks = np.linspace(lo, hi, divisions + 1)
    lines, colors = [], []
    for t in ticks:
        on_axis = abs(t) < 1e-12
        lines.append([(t, lo, z), (t, hi, z)])
        lines.append([(lo, t, z), (hi, t, z)])
        colors += [_GRID_AXIS if on_axis else _GRID] * 2
    ax.add_collection3d(Line3DCollection(lines, colors=colors, linewidths=0.6, zorder=0))


def render_png(scene: list[dict], path, title: str | None = None) -> str:
    fig = plt.figure(figsize=(7, 5.2), facecolor=_BG)
    ax = fig.add_subplot(111, projection="3d")
    ax.set_facecolor(_BG)
    _reference_grid(ax, *scene_mod.bounds(scene))

    labels: list[str] = []
    for prim in scene:
        kind = prim["type"]
        if kind == "points":
            coords = np.array(prim["coords"], dtype=float)
            size = max(12.0, (prim.get("radius", 0.05) * 130.0) ** 2)
            ax.scatter(
                coords[:, 0], coords[:, 1], coords[:, 2],
                color=prim["color"], s=size, depthshade=False,
            )
            if prim.get("name"):
                p = coords[0]
                ax.text(p[0], p[1], p[2], f"  {prim['name']}", color=prim["color"], fontsize=9)
        elif kind == "segments":
            ax.add_collection3d(
                Line3DCollection(
                    prim["pairs"], colors=prim["color"], linewidths=prim.get("width", 2.0)
                )
            )
        elif kind == "polygon":
            poly = Poly3DCollection([prim["coords"]], alpha=prim.get("opacity", 0.35))
            poly.set_facecolor(prim["color"])
            poly.set_edgecolor(prim["color"])
            ax.add_collection3d(poly)
        elif kind == "mesh":
            verts = prim["vertices"]
            tris = [[verts[i] for i in face] for face in prim["faces"]]
            mesh = Poly3DCollection(tris, alpha=prim.get("opacity", 0.3))
            mesh.set_facecolor(prim["color"])
            mesh.set_edgecolor(prim["color"])
            mesh.set_linewidth(0.35)
            ax.add_collection3d(mesh)
        elif kind == "sphere":
            c, r = prim["center"], prim["radius"]
            u = np.linspace(0.0, 2.0 * np.pi, 36)
            v = np.linspace(0.0, np.pi, 18)
            x = c[0] + r * np.outer(np.cos(u), np.sin(v))
            y = c[1] + r * np.outer(np.sin(u), np.sin(v))
            z = c[2] + r * np.outer(np.ones_like(u), np.cos(v))
            # A wireframe, not a surface. plot_surface stacks the alpha of every
            # overlapping quad, which on a light background turns a faint halo
            # into a solid disc that hides the very shape the sphere is about.
            ax.plot_wireframe(
                x, y, z, color=prim["color"], rstride=3, cstride=3,
                linewidth=0.45, alpha=0.5,
            )
        elif kind == "label":
            labels.append(prim["text"])

    lo, hi = scene_mod.bounds(scene)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_zlim(lo, hi)
    # zoom fills the frame: the default 3D projection leaves ~60% of a
    # square axes empty, which on a notebook page is wasted reading space.
    ax.set_box_aspect((1, 1, 1), zoom=1.45)
    ax.view_init(elev=22, azim=-60)
    ax.set_axis_off()

    # A 3D axes reports its whole box to bbox_inches, not the drawn content,
    # so the margins have to be taken back by hand or the picture floats in
    # a field of white.
    fig.subplots_adjust(left=0.02, right=0.98, top=0.99, bottom=0.01)
    if title:
        fig.suptitle(title, color=_FG, fontsize=13, y=0.985)
    if labels:
        fig.text(0.5, 0.012, "\n".join(labels), ha="center", color="#5f6368", fontsize=10)

    fig.savefig(path, dpi=150, facecolor=_BG, bbox_inches="tight")
    plt.close(fig)
    return str(path)
