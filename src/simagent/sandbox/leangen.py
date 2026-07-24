"""Generate Lean 4 *core* certificates for mechanized proofs.

No Mathlib, no Batteries, no build system — a certificate is one file the
Lean kernel checks by pure computation (`decide`), so verification is
axiom-free and needs only the bare toolchain.

Encoding: a rational p/q is the pair (p, q) : Int × Int with q > 0. The
generated theorem asserts q > 0 for every atom; qadd/qsub/qmul multiply
denominators, so positivity is preserved on every derived pair, and under
that invariant qeq/qlt (cross-multiplication) coincide with =/< on ℚ.
This two-line closure argument is the entire trusted modeling step; all the
arithmetic itself is kernel-checked.
"""
from __future__ import annotations

import sympy as sp

from .certify import exact_barycentric, exact_circumcenter

PRELUDE = """\
/- SimAgent certificate — Lean 4 core only; checked by `decide` (no axioms).

   Encoding: (p, q) : Int × Int stands for the rational p/q with q > 0.
   The theorem asserts q > 0 for every atom; qadd/qsub/qmul multiply
   denominators, so every derived pair keeps q > 0, and then
     qeq a b ↔ a = b   and   qlt a b ↔ a < b   as rationals. -/

abbrev Q := Int × Int

def qadd (a b : Q) : Q := (a.1 * b.2 + b.1 * a.2, a.2 * b.2)
def qsub (a b : Q) : Q := (a.1 * b.2 - b.1 * a.2, a.2 * b.2)
def qmul (a b : Q) : Q := (a.1 * b.1, a.2 * b.2)

abbrev qeq (a b : Q) : Prop := a.1 * b.2 = b.1 * a.2
abbrev qlt (a b : Q) : Prop := a.1 * b.2 < b.1 * a.2
abbrev qposden (a : Q) : Prop := 0 < a.2
"""


def _q(x) -> str:
    x = sp.Rational(x)
    assert x.q > 0
    return f"(({x.p} : Int), {x.q})"


def _fold(op: str, terms: list[str]) -> str:
    expr = terms[0]
    for t in terms[1:]:
        expr = f"({op} {expr} {t})"
    return expr


def _det(rows: list[list[str]]) -> str:
    """Cofactor-expansion determinant over Q-expression strings (n <= 3)."""
    n = len(rows)
    if n == 1:
        return rows[0][0]
    if n == 2:
        return f"(qsub (qmul {rows[0][0]} {rows[1][1]}) (qmul {rows[0][1]} {rows[1][0]}))"
    terms = []
    for j in range(n):
        minor = [[row[k] for k in range(n) if k != j] for row in rows[1:]]
        term = f"(qmul {rows[0][j]} {_det(minor)})"
        terms.append(term if j % 2 == 0 else f"(qsub {_q(0)} {term})")
    return _fold("qadd", terms)


def lean_simplex_circumcenter(T: sp.Matrix, theorem: str, title: str) -> str:
    """Certificate: this rational simplex's circumcenter lies OUTSIDE it.

    States, over explicit numerals: the exhibited point c is equidistant from
    all vertices (it IS the circumcenter), the exhibited weights w are its
    barycentric coordinates (affine combination = c, sum = 1), the simplex is
    nondegenerate (edge determinant nonzero, so c and w are unique), and some
    w_k < 0 — which is the definition of "outside". Raises if the instance is
    not actually violating.
    """
    m, d = T.shape
    assert m == d + 1, "expected an (n+1) x n simplex"
    if d > 3:
        # The edge-determinant encoding uses cofactor expansion; beyond 3x3 the
        # term count explodes and `decide` chokes. Honest cap, stated plainly
        # (the LU-witness encoding is the documented post-v2 extension).
        raise ValueError(
            f"Lean certificate capped at d<=3 (got d={d}); "
            "sandbox verdict (exact rational arithmetic) stands"
        )
    c = exact_circumcenter(T)
    w = exact_barycentric(T, c)
    k = min(range(m), key=lambda i: w[i])
    if not w[k] < 0:
        raise ValueError("instance is not a counterexample: all barycentric coords >= 0")

    lines = [PRELUDE, f"/- {title} -/", ""]
    atoms: list[str] = []

    def atom(name: str, value) -> str:
        lines.append(f"def {name} : Q := {_q(value)}")
        atoms.append(name)
        return name

    t = [[atom(f"t{i}{j}", T[i, j]) for j in range(d)] for i in range(m)]
    cs = [atom(f"c{j}", c[j]) for j in range(d)]
    ws = [atom(f"w{i}", w[i]) for i in range(m)]
    lines.append("")

    # squared distance from c to each vertex
    for i in range(m):
        sq = _fold(
            "qadd",
            [f"(qmul (qsub {cs[j]} {t[i][j]}) (qsub {cs[j]} {t[i][j]}))" for j in range(d)],
        )
        lines.append(f"def dist{i} : Q := {sq}")
    # barycentric combination, per coordinate
    for j in range(d):
        combo = _fold("qadd", [f"(qmul {ws[i]} {t[i][j]})" for i in range(m)])
        lines.append(f"def combo{j} : Q := {combo}")
    lines.append(f"def wsum : Q := {_fold('qadd', ws)}")
    edges = [[f"(qsub {t[i][j]} {t[0][j]})" for j in range(d)] for i in range(1, m)]
    lines.append(f"def edgeDet : Q := {_det(edges)}")
    lines.append("")

    conjuncts = [f"qposden {a}" for a in atoms]
    conjuncts += [f"qeq dist0 dist{i}" for i in range(1, m)]
    conjuncts += [f"qeq combo{j} c{j}" for j in range(d)]
    conjuncts += [f"qeq wsum {_q(1)}", f"¬ qeq edgeDet {_q(0)}", f"qlt w{k} {_q(0)}"]

    body = " ∧\n    ".join(conjuncts)
    lines += [
        f"theorem {theorem} :",
        f"    {body} := by",
        "  decide",
        "",
        f"#print axioms {theorem}",
        "",
    ]
    return "\n".join(lines)


EXPR_TERM_CAP = 4000  # `decide` evaluates the term in-kernel; keep it tractable


def _render_q(term: tuple) -> str:
    kind = term[0]
    if kind == "lit":
        return _q(term[1])
    if kind == "atom":
        return term[1]
    return f"({kind} {_render_q(term[1])} {_render_q(term[2])})"


def _term_size(term: tuple) -> int:
    return 1 if term[0] in ("lit", "atom") else 1 + _term_size(term[1]) + _term_size(term[2])


def lean_expr_sign(
    atoms: dict, term: tuple, theorem: str, title: str, negative: bool
) -> str:
    """Certificate: this rational point makes the claim's margin negative (a
    counterexample) or positive (a witness).

    `atoms`/`term` come from `core.expr.lean_form`, so the Lean term is the
    same expression the sandbox measured — no second encoding to drift.
    Unlike the circumcenter certificate this has no determinant blow-up, so
    it carries no dimension cap.
    """
    size = _term_size(term)
    if size > EXPR_TERM_CAP:
        raise ValueError(
            f"Lean term too large ({size} nodes > {EXPR_TERM_CAP}); "
            "sandbox verdict (exact rational arithmetic) stands"
        )
    lines = [PRELUDE, f"/- {title} -/", ""]
    for name in sorted(atoms):
        lines.append(f"def {name} : Q := {_q(atoms[name])}")
    lines += ["", f"def margin : Q := {_render_q(term)}", ""]

    zero = _q(0)
    conjuncts = [f"qposden {name}" for name in sorted(atoms)]
    conjuncts.append(f"qlt margin {zero}" if negative else f"qlt {zero} margin")
    body = " ∧\n    ".join(conjuncts)
    lines += [
        f"theorem {theorem} :",
        f"    {body} := by",
        "  decide",
        "",
        f"#print axioms {theorem}",
        "",
    ]
    return "\n".join(lines)


SOS_PRELUDE_V2 = """\
/- SimAgent sum-of-squares certificate — Lean 4 core only, checked by `decide`.

   Encoding: (p, q) : Int × Int stands for the rational p/q with q > 0; the
   theorem asserts q > 0 for every number it uses, and qadd/qmul multiply
   denominators, so qeqB/qleB (cross-multiplication) coincide with =/<= on ℚ.

   The certificate is a list of BLOCKS. Block k carries a monomial vector z_k
   (as exponent vectors), a Gram matrix G_k, its decomposition G_k = sum_i
   d_i v_i v_i^T, and a multiplier polynomial g_k (as monomials + coefficients;
   g_0 = 1). The checks below verify, by pure computation:
     (1) every d_i >= 0, so each block is a sum of squares,
     (2) G_k = sum_i d_i v_i v_i^T for every block,
     (3) every monomial of p has coefficient equal to the matching sum over
         all blocks, i.e. p = sum_k g_k * (z_k^T G_k z_k),
     (4) every monomial any block can produce is in p's listed monomials, so
         nothing escapes the comparison, and (5) that list has no repeats.

   Hence p = sum_k g_k * sum_i d_i (v_i . z_k)^2. Every square is nonnegative,
   so wherever every g_k >= 0, p >= 0. With no constraints (only g_0 = 1) that
   is everywhere. That closure step is the whole trusted modeling argument;
   all arithmetic is kernel-checked. -/

abbrev Q := Int × Int

def qadd (a b : Q) : Q := (a.1 * b.2 + b.1 * a.2, a.2 * b.2)
def qmul (a b : Q) : Q := (a.1 * b.1, a.2 * b.2)
def qzero : Q := ((0 : Int), 1)

def qeqB (a b : Q) : Bool := a.1 * b.2 == b.1 * a.2
def qleB (a b : Q) : Bool := decide (a.1 * b.2 <= b.1 * a.2)
def qposdenB (a : Q) : Bool := decide (0 < a.2)

def expAdd : List Nat -> List Nat -> List Nat
  | [], b => b
  | a, [] => a
  | x :: xs, y :: ys => (x + y) :: expAdd xs ys

def memb (m : List Nat) : List (List Nat) -> Bool
  | [] => false
  | x :: xs => (x == m) || memb m xs

def noDup : List (List Nat) -> Bool
  | [] => true
  | x :: xs => !(memb x xs) && noDup xs

def sumQ (l : List Q) : Q := l.foldl qadd qzero

def scaleRow (c : Q) (v : List Q) : List Q := v.map (fun x => qmul c x)
def outer (d : Q) (v : List Q) : List (List Q) := v.map (fun vi => scaleRow (qmul d vi) v)
def addMat (A B : List (List Q)) : List (List Q) := List.zipWith (List.zipWith qadd) A B
def matEqB (A B : List (List Q)) : Bool :=
  (List.zip A B).all (fun p => (List.zip p.1 p.2).all (fun q => qeqB q.1 q.2))

structure Block where
  basis : List (List Nat)
  G : List (List Q)
  gmons : List (List Nat)
  gcoef : List Q
  ds : List Q
  vs : List (List Q)

def zeroMat (n : Nat) : List (List Q) := List.replicate n (List.replicate n qzero)

def recon (b : Block) : List (List Q) :=
  (List.zip b.ds b.vs).foldl (fun acc p => addMat acc (outer p.1 p.2))
    (zeroMat b.basis.length)

-- coefficient of monomial m contributed by one block: g_k * (z^T G z)
def blockCoef (b : Block) (m : List Nat) : Q :=
  sumQ ((List.zip b.basis b.G).map (fun r =>
    sumQ ((List.zip b.basis r.2).map (fun p =>
      sumQ ((List.zip b.gmons b.gcoef).filterMap (fun t =>
        if expAdd (expAdd r.1 p.1) t.1 = m then some (qmul p.2 t.2) else none))))))

def dimsOk (b : Block) : Bool :=
  (b.G.length == b.basis.length) && b.G.all (fun r => r.length == b.basis.length)
  && (b.ds.length == b.vs.length) && b.vs.all (fun v => v.length == b.basis.length)
  && (b.gmons.length == b.gcoef.length)

def blockOk (b : Block) : Bool :=
  dimsOk b
  && b.ds.all (fun d => qposdenB d && qleB qzero d)
  && b.G.all (fun r => r.all qposdenB) && b.vs.all (fun v => v.all qposdenB)
  && b.gcoef.all qposdenB
  && matEqB (recon b) b.G
"""

SOS_BASIS_CAP = 28  # `decide` walks basis^2 products; keep the kernel honest and quick


def lean_sos(cert: dict, theorem: str, title: str,
             prelude: bool = True, namespace: str | None = None) -> str:
    """Certificate: the margin is a sum of squares (times the hypotheses), so
    it is nonnegative wherever those hypotheses hold — a universal proof, not
    a sample.

    Takes the certificate from `sandbox.sos` whole; this module only renders
    it, so the Lean text and the sympy check can never describe different
    decompositions.
    """
    blocks = cert["blocks"]
    biggest = max(len(b["basis"]) for b in blocks)
    if biggest > SOS_BASIS_CAP:
        raise ValueError(
            f"sum-of-squares Lean certificate capped at {SOS_BASIS_CAP} basis "
            f"monomials (got {biggest}); the sandbox verdict stands"
        )

    def nat_list(v) -> str:
        return "[" + ", ".join(str(int(x)) for x in v) + "]"

    def nat_lists(vs) -> str:
        return "[" + ", ".join(nat_list(v) for v in vs) + "]"

    def q_list(v) -> str:
        return "[" + ", ".join(_q(x) for x in v) + "]"

    def q_lists(vs) -> str:
        return "[" + ", ".join(q_list(v) for v in vs) + "]"

    rendered = []
    for b in blocks:
        n = len(b["basis"])
        gmons = sorted(b["gterms"])
        rendered.append(
            "  { basis := " + nat_lists(b["basis"])
            + ", G := " + q_lists([[b["gram"][i, j] for j in range(n)] for i in range(n)])
            + ", gmons := " + nat_lists(gmons)
            + ", gcoef := " + q_list([b["gterms"][m] for m in gmons])
            + ", ds := " + q_list([d for d, _ in b["squares"]])
            + ", vs := " + q_lists([v for _, v in b["squares"]])
            + " }"
        )

    lines = [SOS_PRELUDE_V2] if prelude else []
    lines += [f"/- {title} -/", ""]
    if namespace:
        lines.append(f"namespace {namespace}")
        lines.append("")
    lines.append("def blocks : List Block := [\n" + ",\n".join(rendered) + "]")
    lines.append("def mons : List (List Nat) := " + nat_lists(cert["monomials"]))
    lines.append("def pcoef : List Q := " + q_list(cert["coefficients"]))
    lines += [
        "",
        "def totalCoef (m : List Nat) : Q := sumQ (blocks.map (fun b => blockCoef b m))",
        "",
        "def checkAll : Bool :=",
        "  blocks.all blockOk",
        "  && pcoef.all qposdenB",
        "  && (pcoef.length == mons.length)",
        "  && (List.zip mons pcoef).all (fun p => qeqB (totalCoef p.1) p.2)",
        "  && blocks.all (fun b => b.basis.all (fun a => b.basis.all (fun c =>",
        "       b.gmons.all (fun t => memb (expAdd (expAdd a c) t) mons))))",
        "  && noDup mons",
        "",
        f"theorem {theorem} : checkAll = true := by",
        "  decide",
        "",
    ]
    if namespace:
        lines += [f"end {namespace}", "", f"#print axioms {namespace}.{theorem}", ""]
    else:
        lines += [f"#print axioms {theorem}", ""]
    return "\n".join(lines)


def lean_sos_cases(certs: list[dict], theorem: str, title: str,
                   case_notes: list[str]) -> str:
    """One file, one certificate per case, every theorem kernel-checked.

    That the cases COVER the domain is the modeling step and is stated here
    in prose, exactly like the positive-denominator argument above; the
    arithmetic of each case is checked."""
    header = [SOS_PRELUDE_V2, f"/- {title}", ""]
    header += [f"   case {i}: {note}" for i, note in enumerate(case_notes)]
    header += ["", "   The cases above cover the claim's domain; each is certified"
                   " separately below. -/", ""]
    parts = ["\n".join(header)]
    for i, cert in enumerate(certs):
        parts.append(lean_sos(cert, theorem=theorem, title=f"case {i}: {case_notes[i]}",
                              prelude=False, namespace=f"case{i}"))
    return "\n".join(parts)


def lean_bounded_nat(theorem: str, title: str, defs: str, statement: str) -> str:
    """Certificate for a `decide`-able bounded statement over Nat/Int.

    `defs` is verbatim Lean (helper definitions); `statement` is the Prop.
    Kept free-form because bounded claims vary by problem; the checker still
    enforces sorry-freedom and axiom-freedom.
    """
    return "\n".join(
        [
            "/- SimAgent certificate — Lean 4 core only; checked by `decide` (no axioms).",
            f"   {title} -/",
            "",
            "set_option maxRecDepth 8000",
            "",
            defs.strip(),
            "",
            f"theorem {theorem} :",
            f"    {statement.strip()} := by",
            "  decide",
            "",
            f"#print axioms {theorem}",
            "",
        ]
    )


# -- recipe certificates: pin a derived entity to its defining equations -------
#
# A certificate over a derived VALUE proves nothing about how that value was
# built, which is why claims with a recipe stopped at "sandbox". The fix is the
# one the circumcenter certificate already uses, generalized: state the
# equations that DEFINE the derived entity from its arguments, so the kernel
# checks the construction rather than trusting it.

def _sum_term(terms: list[str]) -> str:
    return _fold("qadd", terms) if terms else _q(0)


def _dot_term(u: list[str], v: list[str]) -> str:
    return _sum_term([f"(qmul {a} {b})" for a, b in zip(u, v)])


def _diff(u: list[str], v: list[str]) -> list[str]:
    return [f"(qsub {a} {b})" for a, b in zip(u, v)]


def _pin_circumcenter(out: list[str], T: list[list[str]]) -> list[str]:
    """|c - v_0|^2 = |c - v_i|^2 for every vertex: that IS the circumcenter."""
    def dist_sq(v: list[str]) -> str:
        d = _diff(out, v)
        return _sum_term([f"(qmul {x} {x})" for x in d])
    return [f"qeq {dist_sq(T[0])} {dist_sq(T[i])}" for i in range(1, len(T))]


def _pin_orthocenter(out: list[str], T: list[list[str]]) -> list[str]:
    """(H - A) . (B - C) = 0 and (H - B) . (A - C) = 0: H is on two altitudes,
    which is the definition of the orthocentre."""
    if len(T) != 3:
        raise ValueError("orthocenter pin expects a triangle")
    a, b, c = T
    return [
        f"qeq {_dot_term(_diff(out, a), _diff(b, c))} {_q(0)}",
        f"qeq {_dot_term(_diff(out, b), _diff(a, c))} {_q(0)}",
    ]


def _pin_barycentric(out: list[str], T: list[list[str]], x: list[str]) -> list[str]:
    """Weights summing to one whose affine combination is the point."""
    d = len(x)
    eqs = [f"qeq {_sum_term(out)} {_q(1)}"]
    for j in range(d):
        combo = _sum_term([f"(qmul {out[i]} {T[i][j]})" for i in range(len(T))])
        eqs.append(f"qeq {combo} {x[j]}")
    return eqs


def _pin_centroid(out: list[str], T: list[list[str]]) -> list[str]:
    m = len(T)
    return [f"qeq {_sum_term([T[i][j] for i in range(m)])} "
            f"{_fold('qadd', [out[j]] * m)}" for j in range(len(out))]


def _pin_midpoint(out: list[str], a: list[str], b: list[str]) -> list[str]:
    return [f"qeq (qadd {a[j]} {b[j]}) (qadd {out[j]} {out[j]})"
            for j in range(len(out))]


RECIPE_PINS = {
    "circumcenter": _pin_circumcenter,
    "orthocenter": _pin_orthocenter,
    "barycentric": _pin_barycentric,
    "centroid": _pin_centroid,
    "midpoint": _pin_midpoint,
}


def lean_recipe_witness(atoms: dict, pins: list[str], nondegenerate: list[list[str]],
                        conclusion: list[str], theorem: str, title: str,
                        extra_defs: list[str] | None = None) -> str:
    """Certificate for a claim whose margin reads DERIVED entities.

    `pins` are the equations defining each derived entity from its arguments,
    so the kernel verifies the construction instead of taking the harness's
    word for the numbers. `nondegenerate` is an edge matrix whose determinant
    must be nonzero, which is what makes the construction unique.
    """
    lines = [PRELUDE, f"/- {title}", "",
             "   Each derived quantity is PINNED by the equations that define it,",
             "   so the kernel checks the construction and not merely the numbers.",
             "   The edge determinant is nonzero, so that construction is unique. -/",
             ""]
    for name in sorted(atoms):
        lines.append(f"def {name} : Q := {_q(atoms[name])}")
    lines += list(extra_defs or [])
    conjuncts = [f"qposden {name}" for name in sorted(atoms)]
    conjuncts += pins
    if nondegenerate:
        lines.append(f"def edgeDet : Q := {_det(nondegenerate)}")
        conjuncts.append(f"¬ qeq edgeDet {_q(0)}")
    lines.append("")
    conjuncts += conclusion
    body = " ∧\n    ".join(conjuncts)
    lines += [
        f"theorem {theorem} :",
        f"    {body} := by",
        "  decide",
        "",
        f"#print axioms {theorem}",
        "",
    ]
    return "\n".join(lines)
