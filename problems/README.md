# Your own problems

Any `claim/1` spec file you drop in this folder appears in the notebook's
problem dropdown, marked `(from problems/)`. Restart nothing: the list is read
when the page loads, so a browser refresh is enough.

This exists because the bundled eleven are known-answer tests, not a menu of
what you are allowed to ask. A question you cannot get into the tool is a
question the tool cannot help you with.

These are **not** bundled, and the difference is real. Trust is decided by
object identity with the bundled registry, so a Lean stamp on a file here says
`statement_review = spec-generated-review-needed`: the arithmetic is kernel
checked, but a human still has to confirm the Lean theorem states what you
meant. A bundled claim says `bundled-trusted` because its certificate was
reviewed once and lives in the test suite.

Copy `three-xy.json` and edit it. The fields that matter:

| Field | What it is |
|---|---|
| `id` | Safe run-folder name: lowercase letters or digits joined by single hyphens, at most 80 characters |
| `quantifier` | `forall` or `exists` |
| `spaces` | The free variables. `shape: [2]` is a point in the plane, `[4, 3]` is four points in space |
| `measure.margin` | The expression whose **sign decides the claim**: positive means the property holds |
| `certify.margin` | The same expression, verbatim. The validator rejects any difference, because a certifier that checks something else proves nothing |
| `lean.margin` | The same again, for the certificate |
| `scene` | How to draw it: `point`, `simplex`, `hull3d`, `graph` |

Write the margin so that **positive means true**. For "A > B" that is `A - B`.
Everything else follows from the sign: search pushes it down looking for a
counterexample, the field view paints its zero contour, and exact arithmetic
decides the case at the end.

A broken file is skipped and the reason is printed in the terminal running the
server, so check there if a file does not show up.
