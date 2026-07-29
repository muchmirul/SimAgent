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

With `constraints` the identity becomes p - eps = sigma_0 + sum_k sigma_k g_k,
so the claim's own hypotheses ("for positive x", "for the sides of a
triangle") become ingredients of the proof, exactly as a human uses them.
Without that, a conditional claim cannot be proved at all: x^3 + 1 - x is
negative somewhere on the reals, and true on x >= 0.

The search is still INCOMPLETE and says so. Free Gram parameters are tried at
zero first, then by alternating projection between the affine set and the PSD
cone, then snapped back to rationals; every candidate is re-checked exactly.
So a failure means "no certificate found", never "no certificate exists".
Fail closed, as everywhere else in the kernel.
"""
from __future__ import annotations

import itertools
from collections import defaultdict
from fractions import Fraction

import numpy as np
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


def _psd_gap(G: sp.Matrix) -> float:
    """How far a Gram matrix is from positive semidefinite: its most negative
    eigenvalue, and 0.0 once it is PSD.

    This is the proving side's margin. Refuting a claim answers every move with
    a number the model can walk downhill; a certificate attempt answered only
    accepted-or-refused, so a second attempt began exactly where the first did.
    The quantity is numeric and reported only: nothing is ever stamped from it,
    and the exact rational check remains the sole judge of a certificate.
    """
    A = np.array(G.tolist(), dtype=float)
    return float(min(np.linalg.eigvalsh((A + A.T) / 2).min(), 0.0))


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


def _candidate_assignments(sub: dict, unknowns: list, free: list, blocks: list):
    """Values to try for the Gram matrix's free parameters.

    Zero first, because it is cheap and often right. Then a numeric search:
    alternate between the affine set that reproduces the margin's coefficients
    and the cone of positive-semidefinite matrices, which converges to a point
    in both, and snap the result to rationals at a few denominators. Rounding
    can break either property, so every candidate is still re-checked exactly
    by the caller; this only proposes.
    """
    yield {u: 0 for u in free}
    if not free:
        return
    try:
        numeric = _alternating_projection(sub, unknowns, free, blocks)
    except Exception:  # noqa: BLE001 - a numeric failure just means no proposal
        return
    if numeric is None:
        return
    for max_den in (2, 6, 12, 60, 360, 2520):
        yield {u: sp.Rational(Fraction(float(val)).limit_denominator(max_den))
               for u, val in zip(free, numeric)}


def _alternating_projection(sub: dict, unknowns: list, free: list, blocks: list,
                            rounds: int = 200):
    """Numeric search for free-parameter values that make every block PSD."""
    index = {u: i for i, u in enumerate(unknowns)}
    # each unknown is affine in the free parameters: value = base + M @ t
    base = np.array([float(sp.sympify(sub.get(u, u)).subs({f: 0 for f in free}))
                     for u in unknowns])
    cols = []
    for f in free:
        one = {g: (1 if g is f else 0) for g in free}
        cols.append(np.array([float(sp.sympify(sub.get(u, u)).subs(one))
                              for u in unknowns]) - base)
    M = np.stack(cols, axis=1)
    pinv = np.linalg.pinv(M)

    def matrices(vec):
        out = []
        for b in blocks:
            n = len(b["basis"])
            G = np.zeros((n, n))
            for (i, j), s in b["syms"].items():
                G[i, j] = G[j, i] = vec[index[s]]
            out.append(G)
        return out

    def flatten(mats):
        vec = base + M @ np.zeros(len(free))
        vec = vec.copy()
        for b, G in zip(blocks, mats):
            for (i, j), s in b["syms"].items():
                vec[index[s]] = G[i, j]
        return vec

    t = np.zeros(len(free))
    for _ in range(rounds):
        vec = base + M @ t
        mats = matrices(vec)
        worst = min((np.linalg.eigvalsh(G).min() for G in mats), default=0.0)
        if worst >= 0:
            return t
        # project each block onto the PSD cone, then back onto the affine set
        projected = []
        for G in mats:
            w, V = np.linalg.eigh(G)
            projected.append((V * np.clip(w, 0.0, None)) @ V.T)
        t = pinv @ (flatten(projected) - base)
    vec = base + M @ t
    if min((np.linalg.eigvalsh(G).min() for G in matrices(vec)), default=0.0) < -1e-9:
        return None
    return t


def _poly_terms(g: sp.Expr, symbols: list) -> dict:
    """Exponent vector -> rational coefficient."""
    P = sp.Poly(sp.expand(g), *symbols)
    return {tuple(m): sp.cancel(c) for m, c in zip(P.monoms(), P.coeffs())}


def find_sos(poly: sp.Expr, symbols: list, eps=0, constraints=(),
             notes: list | None = None, progress: dict | None = None) -> dict | None:
    """Exact rational certificate that `poly - eps` is nonnegative, or None.

        poly - eps  =  sigma_0  +  sum_k sigma_k * g_k       (all sigma SOS)

    With no `constraints` this is a plain sum of squares, so the conclusion
    holds at every real point. With constraints it holds wherever every
    `g_k >= 0`, which is what lets a CONDITIONAL claim ("for positive x", "for
    the sides of a triangle") be proved at all: the hypotheses become
    ingredients of the proof, exactly as a human uses them.

    Raises SOSError when the margin is not a polynomial (or is past the size
    caps); returns None when no certificate was found by this incomplete
    search. Every failure appends its REASON to `notes`, and `progress` (an
    out-parameter dict) carries the QUANTITY behind it: `gap`, how far the
    closest candidate Gram matrix was from positive semidefinite, so a refused
    attempt is a position rather than a wall.
    """
    say = notes.append if notes is not None else (lambda _m: None)
    if progress is not None:
        progress.update({"gap": None, "eps": str(_exact(eps)), "candidates": 0})
    target_expr = sp.expand(poly - _exact(eps))
    if len(symbols) > MAX_VARS:
        raise SOSError(f"sum-of-squares search caps at {MAX_VARS} variables")
    if not symbols:
        c = sp.cancel(target_expr)
        if not c.is_rational:
            raise SOSError("constant margin is not rational")
        if c < 0:
            return None
        block = {"basis": [()], "gram": sp.Matrix([[c]]),
                 "squares": [(c, [sp.Integer(1)])], "g": None,
                 "gterms": {(): sp.Integer(1)}}
        return {"blocks": [block], "basis": [()], "gram": block["gram"],
                "squares": block["squares"], "eps": _exact(eps), "symbols": [],
                "monomials": [()], "coefficients": [c], "constraints": []}
    try:
        P = sp.Poly(target_expr, *symbols)
    except sp.PolynomialError as e:
        raise SOSError(f"margin is not polynomial: {e}") from None
    if not all(c.is_rational for c in P.coeffs()):
        raise SOSError("margin has non-rational coefficients")
    deg = P.total_degree()
    if deg > MAX_DEGREE:
        raise SOSError(f"sum-of-squares search caps at total degree {MAX_DEGREE}")
    if deg % 2 == 1 and not constraints:
        # With hypotheses in hand an odd-degree margin is perfectly provable
        # (x^3 + 1 - x on x >= 0); without them it must go negative somewhere.
        say(f"the margin has odd total degree {deg}, so it takes negative values "
            "somewhere: with no assumptions to use, no decomposition can exist")
        return None

    nv = len(symbols)
    # one block per multiplier: sigma_0 times 1, then sigma_k times g_k
    multipliers = [(None, {(0,) * nv: sp.Integer(1)})]
    for g in constraints:
        multipliers.append((g, _poly_terms(g, symbols)))

    blocks = []
    for idx, (g, gterms) in enumerate(multipliers):
        gdeg = max(sum(m) for m in gterms)
        half = (deg - gdeg) // 2
        if half < 0:
            continue  # this hypothesis is too high-degree to help here
        basis = _monomials(nv, half)
        syms = {(i, j): sp.Symbol(f"g{idx}_{i}_{j}")
                for i in range(len(basis)) for j in range(i, len(basis))}
        blocks.append({"basis": basis, "syms": syms, "g": g, "gterms": gterms})

    produced: dict[tuple, list] = defaultdict(list)
    for b in blocks:
        basis, syms = b["basis"], b["syms"]
        for i in range(len(basis)):
            for j in range(len(basis)):
                s = syms[(i, j)] if i <= j else syms[(j, i)]
                for t, ct in b["gterms"].items():
                    m = tuple(a + bb + tt for a, bb, tt in zip(basis[i], basis[j], t))
                    produced[m].append(ct * s)

    target = {tuple(mon): sp.cancel(c) for mon, c in zip(P.monoms(), P.coeffs())}
    for m in target:
        if m not in produced:
            say(f"the margin contains the monomial {m}, which nothing in the "
                "decomposition can produce")
            return None

    equations = [sp.Eq(sum(terms), target.get(m, 0)) for m, terms in produced.items()]
    unknowns = sorted((s for b in blocks for s in b["syms"].values()),
                      key=lambda s: s.name)
    solution = sp.solve(equations, unknowns, dict=True)
    if not solution:
        say("no combination of squares reproduces the margin's coefficients over "
            "this monomial basis")
        return None
    sub = solution[0]
    free = [u for u in unknowns if u not in sub]
    # Zero is only the first guess. When it is not positive semidefinite the
    # remaining freedom is searched numerically and the answer snapped back to
    # rationals, so "not found" stops meaning "we did not look".
    best_gap: float | None = None
    tried = 0
    rounded_off_target = False
    for assignment in _candidate_assignments(sub, unknowns, free, blocks):
        values = {s: sp.cancel(sp.sympify(sub.get(s, s)).subs(assignment))
                  for s in unknowns}
        if any(not v.is_rational for v in values.values()):
            continue
        tried += 1
        for b in blocks:
            n = len(b["basis"])
            syms = b["syms"]
            b["gram"] = sp.Matrix(n, n, lambda i, j: values[syms[(min(i, j), max(i, j))]])
        # Measured for every candidate, including the ones that fail: the whole
        # point is that a failure still reports where it stood.
        gap = min(_psd_gap(b["gram"]) for b in blocks)
        if best_gap is None or gap > best_gap:
            best_gap = gap
        ok = True
        for b in blocks:
            b["squares"] = _psd_squares(b["gram"])
            if b["squares"] is None:
                ok = False
                break
        if ok:
            if _verify_blocks(target_expr, symbols, blocks):
                break
            rounded_off_target = True
    else:
        if progress is not None:
            progress.update({"gap": best_gap, "candidates": tried})
        # Report the limit, name neither a verdict nor a next method: choosing
        # what to try next is the model's job, not the harness's.
        say("no positive-semidefinite solution was found. The numeric search "
            "plus rational rounding is still incomplete, so a certificate may "
            "exist that this missed. The margin may equally be negative "
            "somewhere on the domain. This instrument cannot tell those two "
            "cases apart")
        if best_gap is not None:
            say(f"distance from a certificate: the closest of {tried} candidate "
                f"Gram matrices was short of positive semidefinite by "
                f"{best_gap:.6g} (its most negative eigenvalue), at eps = "
                f"{_exact(eps)}. A certificate needs 0")
        if rounded_off_target:
            say("one candidate was positive semidefinite but its rounded "
                "rational entries no longer reproduced the margin exactly")
        return None
    if progress is not None:
        # Exactly 0: the winning Gram matrix passed the EXACT positive-semidefinite
        # split, so its distance is zero as a fact of rational arithmetic, whatever
        # rounding the eigenvalue routine reports.
        progress.update({"gap": 0.0, "candidates": tried})
    # Every monomial the decomposition can PRODUCE, not just the ones the margin
    # mentions: a product the margin lacks still has to be forced to zero, and
    # the Lean check can only force what it is given.
    mons = sorted(produced)
    return {"blocks": blocks,
            # block 0 under the historical names, so unconstrained callers read
            # the same shape they always did
            "basis": blocks[0]["basis"], "gram": blocks[0]["gram"],
            "squares": blocks[0]["squares"],
            "eps": _exact(eps), "symbols": list(symbols),
            "constraints": list(constraints),
            "monomials": mons,
            "coefficients": [target.get(m, sp.Integer(0)) for m in mons]}


def _block_expr(block: dict, symbols: list) -> sp.Expr:
    z = [sp.prod([s**e for s, e in zip(symbols, mon)]) for mon in block["basis"]]
    total = 0
    for d, v in block["squares"]:
        total += d * sum(vi * zi for vi, zi in zip(v, z)) ** 2
    return total if block["g"] is None else total * block["g"]


def identity_text(cert: dict, margin_label: str = "margin") -> str:
    """The certificate written as mathematics a human can check by hand.

    This IS the proof. Expanding the right-hand side and comparing is a
    ten-second check that needs no Lean and no trust in this code, so the
    kernel must never compute it and keep it to itself.
    """
    symbols = cert["symbols"]
    parts = []
    for block in cert["blocks"]:
        z = [sp.prod([s**e for s, e in zip(symbols, mon)]) for mon in block["basis"]]
        for d, v in block["squares"]:
            form = sp.expand(sum(vi * zi for vi, zi in zip(v, z)))
            term = f"({sp.sstr(form)})**2" if d == 1 else f"({sp.sstr(d)})*({sp.sstr(form)})**2"
            if block["g"] is not None:
                term = f"({sp.sstr(block['g'])})*{term}"
            parts.append(term)
    eps = cert["eps"]
    lhs = margin_label if eps == 0 else f"{margin_label} - ({sp.sstr(eps)})"
    return f"{lhs} = " + (" + ".join(parts) if parts else "0")


def _verify_blocks(target_expr: sp.Expr, symbols: list, blocks: list) -> bool:
    """Independent check: expand the whole decomposition and compare, exactly."""
    total = sum(_block_expr(b, symbols) for b in blocks)
    return sp.expand(target_expr - total) == 0


def _verify(target_expr: sp.Expr, symbols: list, basis: list, squares: list) -> bool:
    """Single-block form of `_verify_blocks` (unconstrained certificates)."""
    return _verify_blocks(target_expr, symbols,
                          [{"basis": basis, "squares": squares, "g": None}])


def prove_positive(poly: sp.Expr, symbols: list, eps_hint=None, constraints=(),
                   notes: list | None = None, progress: dict | None = None) -> dict | None:
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

    # The closest attempt across the whole ladder, kept rather than thrown away:
    # every rung used to fail silently, so the model saw one refusal and no sign
    # that eleven strictness levels had been measured.
    best: dict | None = None

    def keep(step: dict) -> None:
        nonlocal best
        if step.get("gap") is not None and (best is None or step["gap"] > best["gap"]):
            best = dict(step)

    for eps in candidates:
        step: dict = {}
        found = find_sos(poly, symbols, eps=eps, constraints=constraints,
                         progress=step)
        keep(step)
        if found is not None:
            found["strict"] = True
            if progress is not None:
                progress.update(step)
            return found
    step = {}
    found = find_sos(poly, symbols, eps=0, constraints=constraints, notes=notes,
                     progress=step)
    keep(step)
    if progress is not None:
        # a non-strict success is described by the attempt that succeeded;
        # a total failure by the nearest attempt anywhere on the ladder
        progress.update(step if found is not None else (best or step))
    if (found is None and best is not None
            and (step.get("gap") is None or best["gap"] > step["gap"])):
        # The eps = 0 attempt already reported its own gap, so this line is added
        # only when a different rung of the ladder actually came nearer.
        say = notes.append if notes is not None else (lambda _m: None)
        say(f"nearest over all {len(candidates) + 1} strictness levels: eps = "
            f"{best['eps']}, short of positive semidefinite by {best['gap']:.6g}")
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
