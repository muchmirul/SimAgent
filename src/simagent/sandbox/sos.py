"""Sum-of-squares certificates: the harness's first way to PROVE a universal
claim over a continuous domain.

Search can only ever disprove: one bad point kills a `forall`, but no amount
of good points proves one. A sum-of-squares decomposition breaks that
asymmetry for polynomial margins, because it replaces "check infinitely many
points" with one finite algebraic identity:

    p(x) - eps  =  sum_i  d_i * ( v_i . z )^2      with all d_i >= 0

where z is the vector of monomials. Every square is nonnegative at every
real point, so p >= eps everywhere, in one line, forever. The identity is
found and checked in exact rational arithmetic; nothing here is numerical.

The search is deliberately INCOMPLETE and says so: it fixes the free
parameters of the Gram matrix at zero rather than solving a semidefinite
program, so a failure means "no certificate found", never "no certificate
exists". Fail closed, as everywhere else in the kernel.
"""
from __future__ import annotations

import itertools
from collections import defaultdict

import sympy as sp

MAX_VARS = 8
MAX_DEGREE = 8


def _exact(v) -> sp.Rational:
    """A rational, exactly. Floats are snapped; exact values pass through
    untouched (nsimplify on an exact value can return an irrational that is
    merely close to it, which would leave exact arithmetic silently)."""
    if isinstance(v, sp.Basic) and v.is_rational:
        return sp.Rational(v)
    return sp.Rational(sp.nsimplify(v, rational=True))


class SOSError(ValueError):
    """The margin is outside the reach of a sum-of-squares certificate."""


def _monomials(nvars: int, degree: int) -> list[tuple]:
    """Exponent vectors of every monomial of total degree <= `degree`."""
    out = []
    for total in range(degree + 1):
        for combo in itertools.combinations_with_replacement(range(nvars), total):
            e = [0] * nvars
            for i in combo:
                e[i] += 1
            out.append(tuple(e))
    return sorted(set(out))


def _psd_squares(G: sp.Matrix) -> list[tuple] | None:
    """Exact rational LDL-style decomposition: G = sum_i d_i v_i v_i^T.

    Symmetric elimination (completing the square) rather than sympy's LDL,
    because a positive-SEMI-definite Gram matrix is usually singular and LDL
    divides by a zero pivot. Returns None if G is not PSD.
    """
    n = G.rows
    work = sp.Matrix(G)
    squares: list[tuple] = []
    for i in range(n):
        d = sp.cancel(work[i, i])
        if d < 0:
            return None
        if d == 0:
            # a PSD matrix with a zero diagonal entry has that whole row zero
            if any(work[i, j] != 0 for j in range(n)):
                return None
            continue
        v = [sp.cancel(work[i, j] / d) for j in range(n)]
        squares.append((d, v))
        for r in range(n):
            for c in range(n):
                work[r, c] = sp.cancel(work[r, c] - d * v[r] * v[c])
    if any(work[r, c] != 0 for r in range(n) for c in range(n)):
        return None  # elimination left a remainder: not PSD
    return squares


def find_sos(poly: sp.Expr, symbols: list, eps=0, notes: list | None = None) -> dict | None:
    """Exact rational sum-of-squares certificate for `poly - eps`, or None.

    Raises SOSError when the margin is not a polynomial at all (or is past
    the size caps); returns None when it is polynomial but no certificate was
    found with this incomplete search. Every failure appends its REASON to
    `notes`: a dead end with no reason is a dead end the caller cannot act on.
    """
    say = notes.append if notes is not None else (lambda _m: None)
    target_expr = sp.expand(poly - _exact(eps))
    if len(symbols) > MAX_VARS:
        raise SOSError(f"sum-of-squares search caps at {MAX_VARS} variables")
    if not symbols:
        c = sp.cancel(target_expr)
        if not c.is_rational:
            raise SOSError("constant margin is not rational")
        return ({"basis": [()], "gram": sp.Matrix([[c]]), "squares": [(c, [sp.Integer(1)])],
                 "eps": _exact(eps), "symbols": [],
                 "monomials": [()], "coefficients": [c]} if c >= 0 else None)
    try:
        P = sp.Poly(target_expr, *symbols)
    except sp.PolynomialError as e:
        raise SOSError(f"margin is not polynomial: {e}") from None
    if not all(c.is_rational for c in P.coeffs()):
        raise SOSError("margin has non-rational coefficients")
    deg = P.total_degree()
    if deg > MAX_DEGREE:
        raise SOSError(f"sum-of-squares search caps at total degree {MAX_DEGREE}")
    if deg % 2 == 1:
        say(f"the margin has odd total degree {deg}, so it takes negative values "
            "somewhere: no sum-of-squares decomposition can exist")
        return None

    basis = _monomials(len(symbols), deg // 2)
    n = len(basis)
    # unknown symmetric Gram matrix, matched coefficient by coefficient
    g = {(i, j): sp.Symbol(f"g_{i}_{j}") for i in range(n) for j in range(i, n)}

    def gsym(i, j):
        return g[(i, j)] if i <= j else g[(j, i)]

    produced: dict[tuple, list] = defaultdict(list)
    for i in range(n):
        for j in range(n):
            m = tuple(a + b for a, b in zip(basis[i], basis[j]))
            produced[m].append(gsym(i, j))

    target = {tuple(mon): sp.cancel(c) for mon, c in zip(P.monoms(), P.coeffs())}
    for m, c in target.items():
        if m not in produced:
            say(f"the margin contains the monomial {m}, which no product of two "
                "basis monomials can produce")
            return None

    equations = [sp.Eq(sum(terms), target.get(m, 0)) for m, terms in produced.items()]
    unknowns = sorted(g.values(), key=lambda s: s.name)
    solution = sp.solve(equations, unknowns, dict=True)
    if not solution:
        say("no Gram matrix reproduces the margin's coefficients over this "
            "monomial basis")
        return None
    sub = solution[0]
    # the remaining freedom is exactly what a semidefinite solver would search;
    # this pins it at zero, which is why a None here is "not found", not "none exists"
    zeros = {u: 0 for u in unknowns}
    values = {s: sp.cancel(sp.sympify(sub.get(s, 0)).subs(zeros)) for s in unknowns}
    if any(not v.is_rational for v in values.values()):
        say("the Gram matrix solution is not rational")
        return None

    G = sp.Matrix(n, n, lambda i, j: values[gsym(i, j)])
    squares = _psd_squares(G)
    if squares is None:
        # Report the limit, name neither a verdict nor a next method: choosing
        # what to try next is the model's job, not the harness's.
        say("a Gram matrix was found but it is not positive semidefinite once "
            "its free parameters are pinned at zero. This search is incomplete, "
            "so a certificate may still exist (a semidefinite search would find "
            "one). The margin may equally be negative somewhere. This instrument "
            "cannot tell those two cases apart")
        return None
    if not _verify(target_expr, symbols, basis, squares):
        say("the decomposition failed its own exact expansion check")
        return None
    # Every monomial the basis can PRODUCE, not just the ones p mentions: a
    # product like x*y that p lacks still has to be forced to zero, and the
    # Lean check can only force what it is given.
    mons = sorted(produced)
    return {"basis": basis, "gram": G, "squares": squares,
            "eps": _exact(eps), "symbols": list(symbols),
            "monomials": mons,
            "coefficients": [target.get(m, sp.Integer(0)) for m in mons]}


def identity_text(cert: dict, margin_label: str = "margin") -> str:
    """The certificate written as mathematics a human can check by hand.

    This IS the proof. Expanding the right-hand side and comparing is a
    ten-second check that needs no Lean and no trust in this code, so the
    kernel must never compute it and keep it to itself.
    """
    symbols, basis = cert["symbols"], cert["basis"]
    z = [sp.prod([s**e for s, e in zip(symbols, mon)]) for mon in basis]
    parts = []
    for d, v in cert["squares"]:
        form = sp.expand(sum(vi * zi for vi, zi in zip(v, z)))
        parts.append(f"({sp.sstr(d)})*({sp.sstr(form)})**2" if d != 1
                     else f"({sp.sstr(form)})**2")
    eps = cert["eps"]
    lhs = margin_label if eps == 0 else f"{margin_label} - ({sp.sstr(eps)})"
    return f"{lhs} = " + " + ".join(parts) if parts else f"{lhs} = 0"


def _verify(target_expr: sp.Expr, symbols: list, basis: list, squares: list) -> bool:
    """Independent check: expand the decomposition and compare, exactly."""
    z = [sp.prod([s**e for s, e in zip(symbols, mon)]) for mon in basis]
    total = 0
    for d, v in squares:
        total += d * sum(vi * zi for vi, zi in zip(v, z)) ** 2
    return sp.expand(target_expr - total) == 0


def prove_positive(poly: sp.Expr, symbols: list, eps_hint=None,
                   notes: list | None = None) -> dict | None:
    """Certify p > 0 everywhere (strict) by certifying p - eps as SOS.

    `eps_hint` is typically half the smallest margin the search ever saw. A
    certificate with eps > 0 proves the STRICT claim; eps == 0 only proves
    p >= 0, which does not settle a strict statement, so it is reported with
    `strict: False` and the caller must not upgrade it.
    """
    # A search may supply a hint, but the instrument must stand alone: without
    # one it walks a descending ladder to find its own positive lower bound,
    # rather than making the caller run a search first.
    candidates = []
    if eps_hint is not None and eps_hint > 0:
        e = _exact(eps_hint)
        candidates = [e, e / 4, e / 64]
    candidates += [sp.Rational(1, 2**k) for k in range(0, 11)]
    for eps in candidates:
        found = find_sos(poly, symbols, eps=eps)
        if found is not None:
            found["strict"] = True
            return found
    found = find_sos(poly, symbols, eps=0, notes=notes)
    if found is not None:
        found["strict"] = False
        if notes is not None:
            notes.append(
                "the margin is a sum of squares, so it is >= 0 everywhere, but no "
                "positive lower bound was found: the inequality is TIGHT (it touches "
                "equality). A strict claim is therefore not proved - check whether "
                "the equality case is inside the claim's domain"
            )
    return found
