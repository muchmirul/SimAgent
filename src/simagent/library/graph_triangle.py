"""Ground truth: FALSE — C5 has five edges on five vertices and no triangle.

"Every graph on 5 vertices with at least 5 edges contains a triangle" is a
plausible-sounding extremal claim, and the 5-cycle refutes it. (Turán's
theorem gives the true threshold: a triangle-free graph on 5 vertices can
carry up to 6 edges, the complete bipartite K(2,3).)

This is the known-answer test for DISCRETE spaces. The object here is a
graph, not a point in a box, so no amount of the existing vocabulary could
state it: GraphSpace samples adjacency matrices, moves flip edges instead of
nudging coordinates, and the whole space of 2^10 = 1024 graphs enumerates, so
the harness can check every case rather than sample.

The implication is stated the general way: the hypothesis (at least 5 edges)
filters the domain through `expr_nonneg`, and the conclusion (a triangle
exists) is the margin.
"""
from ..core.claim import Claim
from ..core.space import GraphSpace

CLAIM = Claim(
    id="graph-triangle-threshold",
    title="Every 5-vertex graph with 5+ edges has a triangle",
    conjecture=(
        "Every simple graph on 5 labelled vertices with at least 5 edges "
        "contains a triangle."
    ),
    latex=(
        r"\forall\, G \text{ on } 5 \text{ vertices},\ |E(G)| \ge 5:\quad "
        r"G \text{ contains } K_3"
    ),
    quantifier="forall",
    spaces={"G": GraphSpace(n=5)},
    recipe=[
        {"name": "E", "ctor": "edge_count", "args": ["G"]},
        {"name": "T", "ctor": "triangle_count", "args": ["G"]},
    ],
    # margin > 0 iff at least one triangle (counts are integers, so 1/2 separates)
    measure={"kind": "expr", "margin": "T - 0.5"},
    constraint={"kind": "expr_nonneg", "expr": "E - 5"},
    certify={"kind": "expr", "margin": "T - 0.5"},
    scene={"kind": "graph", "of": "G"},
    lean_statement=(
        "theorem five_edges_forces_triangle (G : SimpleGraph (Fin 5))\n"
        "    (h : 5 ≤ G.edgeFinset.card) :\n"
        "    ∃ a b c, G.Adj a b ∧ G.Adj b c ∧ G.Adj a c := by\n"
        "  sorry"
    ),
    notes=(
        "False: the 5-cycle has exactly 5 edges and no triangle. Turán's "
        "theorem puts the real threshold at 7 edges (K(2,3) is triangle-free "
        "with 6)."
    ),
)

SPEC = CLAIM
