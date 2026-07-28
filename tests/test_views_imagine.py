"""P4 gate: the perception pack.

- field view of the triangle claim: zero-contour present (the Thales circle),
  metadata calibrated (fail fraction, min marker)
- imagine: journals a thought experiment WITHOUT touching the mainline;
  kernel-grade ops are rejected inside it
- hull_facets: dimension-generic known answer (4-cube) and fail-closed limits
"""
import json
from pathlib import Path

import numpy as np
import pytest

from simagent.agent import AgentRun
from simagent.core.journal import read_trace
from simagent.library import get
from simagent.sandbox.geometry import hull_facets
from simagent.views import render_field, render_sweep, render_trajectory


def triangle_ctx():
    spec = get("circumcenter-in-triangle")
    comp = spec.compiled()
    vars = {"T": np.array([[-1.0, 0.0], [1.0, 0.0], [0.0, 0.8]])}
    return spec, comp, vars


def test_field_view_shows_the_thales_boundary(tmp_path):
    spec, comp, vars = triangle_ctx()
    path, meta = render_field(spec, comp, vars, tmp_path / "field.png",
                              var="T", row=2, resolution=40)
    assert Path(path).exists()
    assert meta["zero_contour"] is True, "moving C must cross HOLDS<->FAILS (Thales)"
    assert 0.05 < meta["fail_fraction"] < 0.95
    assert meta["min_margin"] < 0 < meta["max_margin"]


def test_sweep_view_finds_zero_crossings(tmp_path):
    spec, comp, vars = triangle_ctx()
    path, meta = render_sweep(spec, comp, vars, tmp_path / "sweep.png",
                              var="T", row=2, coord=1, resolution=80)
    assert Path(path).exists()
    assert meta["zero_crossings"], "sweeping C vertically must cross the boundary"


def test_trajectory_view_from_journal(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.8]})
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]})
    steps = read_trace(tmp_path)["steps"]
    path, meta = render_trajectory(steps, tmp_path / "traj.png")
    assert Path(path).exists() and meta["points"] == 2
    assert meta["final_margin"] < 0


def test_imagine_leaves_mainline_untouched(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.8]})
    before = {k: v.copy() for k, v in run.session.vars.items()}
    content, err = run.dispatch("imagine", {
        "ops": [{"op": "set", "target": "T", "row": 2, "values": [0.0, 0.2]}],
        "look": True,
    })
    assert not err
    for k, v in before.items():
        assert np.array_equal(run.session.vars[k], v), "imagine mutated the mainline!"
    steps = read_trace(tmp_path)["steps"]
    im = steps[-1]
    assert im["mode"] == "imagine"
    assert im["branch"]["base_step"] == 1
    assert im["branch"]["outcomes"][0]["check"]["holds"] is False  # flattening fails
    assert im["image"] and (tmp_path / im["image"]).exists()  # the ghost render
    # the imagined step carries the HYPOTHETICAL state, not the mainline
    assert im["vars"]["T"][2] == [0.0, 0.2]
    # and the next commit still diffs against the true mainline
    run.dispatch("check", {})
    last = read_trace(tmp_path)["steps"][-1]
    assert last["diff"]["changed"] == []  # nothing really moved


def test_imagine_rejects_kernel_ops(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    for bad in ("certify", "exhaust", "hunt", "submit_lean_proof", "replace"):
        content, err = run.dispatch("imagine", {"ops": [{"op": bad}]})
        assert err and "committed state" in content


def test_view_tool_journals_metadata(tmp_path):
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.8]})
    content, err = run.dispatch("view", {"kind": "field", "var": "T", "row": 2,
                                          "resolution": 24})
    assert not err
    # numbers-first: the model gets the measured metadata as text, and the
    # render is still journaled for the human notebook
    assert isinstance(content, str) and "kind" in content
    step = read_trace(tmp_path)["steps"][-1]
    assert step["extra"]["view"]["kind"] == "field"
    assert (tmp_path / step["image"]).exists()
    # views perceive; they never mutate
    assert step["diff"]["changed"] == []


def test_hull_facets_dimension_generic():
    corners = np.array(np.meshgrid(*[[0.0, 1.0]] * 4)).reshape(4, -1).T  # 4-cube
    V, ridges, facets = hull_facets(corners)
    assert V == 16
    assert facets > 0 and ridges == facets * 4 // 2
    with pytest.raises(ValueError):
        hull_facets(np.zeros((5, 9)))  # d>8: fail closed
    with pytest.raises(ValueError):
        hull_facets(np.zeros((4, 3)))  # degenerate: all points equal


# ---- review-workflow regression pins (post-P5 audit) ------------------------

def test_hull_counts_is_3d_only_fail_closed():
    # d=4 clouds previously produced garbage V/E/F silently (confirmed finding)
    corners4 = np.array(np.meshgrid(*[[0.0, 1.0]] * 4)).reshape(4, -1).T
    with pytest.raises(ValueError, match="3-D only"):
        from simagent.sandbox.geometry import hull_counts
        hull_counts(corners4)


def test_field_view_on_discrete_measure_says_so(tmp_path):
    claim = get("euler-characteristic-hull")
    comp = claim.compiled()
    rng = np.random.default_rng(0)
    vars = {"P": claim.spaces["P"].sample(rng)}
    while not comp.valid(**vars):
        vars = {"P": claim.spaces["P"].sample(rng)}
    with pytest.raises(ValueError, match="discrete"):
        render_field(claim, comp, vars, tmp_path / "f.png", var="P", row=0, resolution=10)


def test_sweep_rejects_ndim3_and_labels_default_row(tmp_path):
    spec, comp, vars = triangle_ctx()
    _, meta = render_sweep(spec, comp, vars, tmp_path / "s.png", var="T", coord=1)
    assert meta["row"] == 0  # row=None means row 0 was swept — and says so
    import numpy as _np
    from simagent.core.space import Box
    from types import SimpleNamespace
    fake = SimpleNamespace(domain=[SimpleNamespace(name="X", shape=[2, 2, 2],
                                                   low=-1.0, high=1.0, kind="real")])
    with pytest.raises(ValueError, match="scalar/1-D/2-D"):
        render_sweep(fake, comp, {"X": _np.zeros((2, 2, 2))}, tmp_path / "s2.png", var="X")


def test_finalize_writes_proof_before_journal_end_marker(tmp_path):
    # live viewers treat the end marker as "everything is on disk" (race fix)
    run = AgentRun(get("circumcenter-in-triangle"), tmp_path)
    run.dispatch("set_var", {"name": "T", "values": [-1, 0, 1, 0, 0, 0.2]})
    run.dispatch("certify", {})
    run.dispatch("finish", {"summary": "done"})

    order = []
    real_close = run.trace.close

    def tracking_close():
        order.append(("proof_exists", (tmp_path / "proof.json").exists()))
        real_close()

    run.trace.close = tracking_close
    run.finalize()
    assert order == [("proof_exists", True)]
