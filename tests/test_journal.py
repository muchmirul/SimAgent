"""P3 gate: journal promotion — modes, annotations, replay, and backward
compatibility with pre-P3 traces."""
import json
from pathlib import Path

import numpy as np

from simagent.core.journal import Journal, read_trace, replay_vars


def entry(j, tool, vars, margin, **kw):
    return j.record(
        tool=tool, args={}, result="ok", error=False,
        vars=vars, check={"holds": margin > 0, "margin": margin, "data": {}},
        scene=[], **kw,
    )


def test_imagine_never_advances_the_diff_baseline(tmp_path):
    j = Journal(tmp_path)
    j.seed({"T": np.zeros((2, 2))}, {"holds": True, "margin": 1.0})
    entry(j, "set", {"T": np.ones((2, 2))}, 0.5)                       # commit
    entry(j, "imagine", {"T": np.full((2, 2), 9.0)}, -3.0,
          mode="imagine", branch={"base_step": 1, "ops": [], "outcomes": []})
    e3 = entry(j, "set", {"T": np.full((2, 2), 2.0)}, 0.2)             # commit
    j.close()
    # step 3's diff compares against step 1 (the last commit), not the fantasy
    assert e3["diff"]["margin"]["before"] == 0.5
    assert all(c["before"] == "(1, 1)" for c in e3["diff"]["changed"])
    steps = read_trace(tmp_path)["steps"]
    assert steps[1]["mode"] == "imagine" and steps[1]["branch"]["base_step"] == 1


def test_replay_vars_follows_the_mainline_only(tmp_path):
    j = Journal(tmp_path)
    entry(j, "set", {"T": np.ones((2, 2))}, 0.5)
    entry(j, "imagine", {"T": np.full((2, 2), 9.0)}, -3.0, mode="imagine")
    j.annotate("user_comment", {"text": "try flattening", "target": {"step": 1}})
    entry(j, "set", {"T": np.full((2, 2), 2.0)}, 0.2)
    j.close()
    steps = read_trace(tmp_path)["steps"]
    tip = replay_vars(steps)
    assert np.array_equal(tip["T"], np.full((2, 2), 2.0))
    at2 = replay_vars(steps, through=3)  # imagine+comment don't count
    assert np.array_equal(at2["T"], np.ones((2, 2)))


def test_annotation_events_ride_the_worldline(tmp_path):
    j = Journal(tmp_path)
    j.note_thought("user said something useful")
    e = j.annotate("user_comment", {"text": "look at the degenerate case", "target": {"step": 2}})
    j.close()
    assert e["mode"] == "annotation" and e["kind"] == "user_comment"
    assert e["thought"][0]["text"].startswith("user said")
    steps = read_trace(tmp_path)["steps"]
    assert steps[0]["text"] == "look at the degenerate case"


def test_pre_p3_trace_without_mode_reads_as_commit(tmp_path):
    old = {  # exactly the pre-P3 schema: no mode, no toolCallId requirement
        "step": 1, "ts": 0.0, "thought": None, "tool": "set_var", "args": {},
        "error": False, "result": "set", "check": {"holds": False, "margin": -1.0},
        "vars": {"T": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]}, "scene": [],
        "equation": {"text": [], "latex": []},
        "diff": {"changed": [], "margin": {"before": None, "after": -1.0}},
        "extra": None, "image": None,
    }
    p = Path(tmp_path) / "trace.jsonl"
    p.write_text(json.dumps(old) + "\n" + json.dumps({"event": "end", "steps": 1}) + "\n")
    out = read_trace(tmp_path)
    assert out["done"] and out["total"] == 1
    tip = replay_vars(out["steps"])
    assert tip["T"].shape == (3, 2)
