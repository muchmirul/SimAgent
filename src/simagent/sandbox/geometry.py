"""Numeric geometry used by the closed Claim vocabulary.

Every function here is exposed to the exec'd `check` / `build_scene` code of a
spec (see spec.toolbox()). Keep signatures simple and array-based: this module
is the "physics" of the sandbox that LLM-generated specs program against.

Conventions:
- A simplex is an (n+1, n) array: n+1 points in R^n (triangle in R^2,
  tetrahedron in R^3).
- Point clouds are (m, d) arrays.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.spatial import ConvexHull


def circumcenter(pts) -> np.ndarray:
    """Circumcenter of a nondegenerate simplex given as an (n+1, n) array.

    Solves 2(p_i - p_0) . c = |p_i|^2 - |p_0|^2 for i = 1..n.
    """
    pts = np.asarray(pts, dtype=float)
    p0 = pts[0]
    A = 2.0 * (pts[1:] - p0)
    b = (pts[1:] ** 2).sum(axis=1) - (p0**2).sum()
    return np.linalg.solve(A, b)


def barycentric(pts, x) -> np.ndarray:
    """Barycentric coordinates of point x w.r.t. simplex pts ((n+1, n) array).

    Returns an (n+1,) array summing to 1. All coordinates positive iff x lies
    strictly inside the simplex.
    """
    pts = np.asarray(pts, dtype=float)
    x = np.asarray(x, dtype=float)
    T = (pts[1:] - pts[0]).T
    w = np.linalg.solve(T, x - pts[0])
    return np.concatenate([[1.0 - w.sum()], w])


def simplex_volume(pts) -> float:
    """Unsigned volume (area in 2D) of a simplex given as an (n+1, n) array."""
    pts = np.asarray(pts, dtype=float)
    n = pts.shape[0] - 1
    return abs(float(np.linalg.det(pts[1:] - pts[0]))) / math.factorial(n)


def hull_counts(points) -> tuple[int, int, int]:
    """(V, E, F) of the convex hull boundary of a 3D point cloud.

    STRICTLY 3-D (fail closed): the edge walk assumes triangular facets, so a
    d>3 cloud would silently produce garbage counts — use `hull_facets` for
    other dimensions. The hull boundary is triangulated by qhull, so F counts
    triangles and E counts unique triangle edges. Raises if degenerate.
    """
    pts = np.asarray(points, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError(
            "hull_counts is 3-D only (V/E/F of a polyhedron boundary); "
            "use hull_facets for other dimensions"
        )
    hull = ConvexHull(pts)
    V = len(hull.vertices)
    F = len(hull.simplices)
    edges: set[tuple[int, int]] = set()
    for tri in hull.simplices:
        for i in range(3):
            a, b = int(tri[i]), int(tri[(i + 1) % 3])
            edges.add((min(a, b), max(a, b)))
    return V, len(edges), F


def hull_mesh(points) -> tuple[list[list[float]], list[list[int]]]:
    """(vertices, triangular faces) of a 3D convex hull, for scene building.

    Vertices are the input points; faces index into them.
    """
    points = np.asarray(points, dtype=float)
    hull = ConvexHull(points)
    return points.tolist(), [[int(i) for i in tri] for tri in hull.simplices]


HULL_MAX_DIM = 8  # qhull's practical ceiling; fail closed beyond it


def hull_facets(points) -> tuple[int, int, int]:
    """(V, ridges, facets) of the convex hull of a d-dimensional point cloud —
    dimension-generic (2 <= d <= 8), unlike the historical 3D pair above.

    qhull triangulates the boundary, so `facets` counts (d-1)-simplices and
    `ridges` counts their shared (d-2)-faces (each ridge is shared by exactly
    two facets: ridges = facets * d / 2). Degenerate input raises ValueError —
    fail closed, never guess.
    """
    pts = np.asarray(points, dtype=float)
    if pts.ndim != 2:
        raise ValueError("hull_facets needs an (m, d) point cloud")
    d = pts.shape[1]
    if not (2 <= d <= HULL_MAX_DIM):
        raise ValueError(f"hull_facets supports 2 <= d <= {HULL_MAX_DIM}, got d={d}")
    try:
        hull = ConvexHull(pts)
    except Exception as e:  # noqa: BLE001 - qhull errors become one clear signal
        raise ValueError(f"degenerate point cloud for a {d}-D hull: {e}") from None
    facets = len(hull.simplices)
    ridges = facets * d // 2
    return len(hull.vertices), ridges, facets
