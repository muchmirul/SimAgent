"""Scene graph: the shared visual language between the sandbox and renderers.

A scene is a list of primitive dicts. Closed Claim scene builders create them
through the constructors below; both matplotlib and generated Manim
scene consume the same JSON, so a witness found by the search renders
identically everywhere. 2D inputs are lifted to z = 0.
"""
from __future__ import annotations


def _pt3(p) -> list[float]:
    p = [float(x) for x in p]
    while len(p) < 3:
        p.append(0.0)
    return p[:3]


def _pts3(coords) -> list[list[float]]:
    return [_pt3(p) for p in coords]


# One palette, so every renderer agrees on what a thing looks like. Tuned for
# a LIGHT background, because that is what the notebook, the matplotlib preview
# and the Manim scene all draw on: a near-white ink would simply disappear.
INK = "#1c1e21"    # the objects themselves
EDGE = "#5f6368"   # structure between objects
FACE = "#4a90d9"   # polygon and mesh fills
HALO = "#c8890a"   # circumsphere and other soft indicators
GOOD = "#137333"   # the property holds
BAD = "#c5221f"    # the property fails


def points(coords, color: str = INK, radius: float = 0.05, name: str | None = None,
           binds: str | None = None) -> dict:
    """A set of dots. `binds` names the FREE variable they render, so index i is
    row i of that variable.

    Without it a picked dot is just a position on screen: the UI can talk about
    it but cannot move it, because it does not know which number to change. A
    DERIVED point (a circumcenter, say) leaves binds empty on purpose, since
    moving it directly would mean nothing.
    """
    return {"type": "points", "coords": _pts3(coords), "color": color,
            "radius": radius, "name": name, "binds": binds}


def segments(pairs, color: str = EDGE, width: float = 2.0) -> dict:
    return {"type": "segments", "pairs": [[_pt3(a), _pt3(b)] for a, b in pairs], "color": color, "width": width}


def polygon(coords, color: str = FACE, opacity: float = 0.35) -> dict:
    return {"type": "polygon", "coords": _pts3(coords), "color": color, "opacity": opacity}


def mesh(vertices, faces, color: str = FACE, opacity: float = 0.3) -> dict:
    return {
        "type": "mesh",
        "vertices": _pts3(vertices),
        "faces": [[int(i) for i in f] for f in faces],
        "color": color,
        "opacity": opacity,
    }


def sphere(center, radius: float, color: str = HALO, opacity: float = 0.12) -> dict:
    return {"type": "sphere", "center": _pt3(center), "radius": float(radius), "color": color, "opacity": opacity}


def label(text: str) -> dict:
    return {"type": "label", "text": str(text)}


def bounds(scene: list[dict]) -> tuple[float, float]:
    """(lo, hi) cube bounds covering all geometry in the scene."""
    xs: list[float] = []
    for prim in scene:
        if prim["type"] == "points":
            for p in prim["coords"]:
                xs.extend(p)
        elif prim["type"] == "segments":
            for a, b in prim["pairs"]:
                xs.extend(a)
                xs.extend(b)
        elif prim["type"] == "polygon":
            for p in prim["coords"]:
                xs.extend(p)
        elif prim["type"] == "mesh":
            for p in prim["vertices"]:
                xs.extend(p)
        elif prim["type"] == "sphere":
            c, r = prim["center"], prim["radius"]
            xs.extend([v - r for v in c])
            xs.extend([v + r for v in c])
    if not xs:
        return -1.0, 1.0
    lo, hi = min(xs), max(xs)
    pad = 0.1 * max(hi - lo, 1e-6)
    return lo - pad, hi + pad
