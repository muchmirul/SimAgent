"""The measurement, checked offline.

These tests never call a model. They check the parts that decide whether the
measurement means anything: that a seed which already settles the claim is
thrown out and SAID, that arms are compared on the same tasks, that the
threshold is read from the manifest rather than from the results, and that
nothing here reads model prose.
"""
import json

import pytest

from simagent import evaluate
from simagent.library import get


def test_the_default_manifest_is_versioned_and_declares_its_threshold_first():
    """A threshold chosen after seeing results is not a threshold."""
    manifest = evaluate.load_manifest()
    assert manifest["format"] == evaluate.MANIFEST_VERSION
    required = manifest["required_improvement"]
    assert required["certified_solve_rate_over_search"] > 0
    assert required["note"]
    assert manifest["tasks"], "an empty task list measures nothing"
    for task in manifest["tasks"]:
        assert task["why"], f"{task['id']} does not say what it tests"


def test_a_foreign_manifest_is_refused(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"format": "something/else", "tasks": []}))
    with pytest.raises(ValueError, match="not a eval/1 manifest"):
        evaluate.load_manifest(path)


def test_a_seed_that_already_settles_the_claim_is_detected():
    """Such a seed measures nothing: every arm wins at step zero, including the
    one with no model in it."""
    # a random triangle often has its circumcenter outside, so seed 3 hands the
    # counterexample over before any arm does anything
    assert evaluate.seed_settles_the_claim(get("circumcenter-in-triangle"), 3) is True
    # positive-quadratic holds everywhere, so no sample can ever settle its forall
    assert evaluate.seed_settles_the_claim(get("positive-quadratic"), 1) is False


def test_a_skipped_seed_is_recorded_not_silently_dropped(tmp_path, monkeypatch):
    """A hidden skip makes the arms look like they ran on tasks they never saw."""
    manifest = {
        "format": evaluate.MANIFEST_VERSION,
        "name": "skip-test",
        "tasks": [{"id": "circumcenter-in-triangle", "spec": "unbounded.json",
                   "seeds": [3], "why": "settles immediately on purpose"}],
        "required_improvement": {"certified_solve_rate_over_search": 0.1},
        "budget": {"search_trials": 10},
    }
    spec = get("circumcenter-in-triangle")
    (tmp_path / "unbounded.json").write_text(json.dumps(spec.to_json()))

    report = evaluate.run(manifest, tmp_path / "out", arms=("search",),
                          repo_root=tmp_path, log=lambda *_: None)
    assert report["results"] == []
    assert len(report["skipped"]) == 1
    assert report["skipped"][0]["seed"] == 3
    assert "settles the claim" in report["skipped"][0]["why"]


def test_the_search_arm_runs_offline_and_records_a_kernel_outcome(tmp_path):
    manifest = {
        "format": evaluate.MANIFEST_VERSION,
        "name": "search-only",
        "tasks": [{"id": "positive-quadratic", "spec": "pq.json",
                   "seeds": [1], "why": "a claim search cannot settle either way"}],
        "required_improvement": {"certified_solve_rate_over_search": 0.2},
        "budget": {"search_trials": 40},
    }
    (tmp_path / "pq.json").write_text(json.dumps(get("positive-quadratic").to_json()))

    report = evaluate.run(manifest, tmp_path / "out", arms=("search",),
                          repo_root=tmp_path, log=lambda *_: None)
    assert len(report["results"]) == 1
    row = report["results"][0]
    assert row["arm"] == "search"
    assert row["verdict"] == "no_counterexample"
    assert row["verified_by"] in ("none", "sandbox", "lean", "sandbox+lean")
    assert row["elapsed_s"] >= 0
    assert (tmp_path / "out" / "eval.json").is_file()


def test_the_model_arms_differ_only_by_the_image_flag(tmp_path):
    """The comparison is worthless if the arms differ in anything else: same
    task, same seed, same budget, same model, one flag."""
    calls = []

    def fake_launcher(command, repo_root):
        calls.append(command)
        return 0

    manifest = {
        "format": evaluate.MANIFEST_VERSION,
        "name": "arm-shape",
        "tasks": [{"id": "positive-quadratic", "spec": "pq.json",
                   "seeds": [1], "why": "wiring only"}],
        "required_improvement": {"certified_solve_rate_over_search": 0.2},
        "budget": {"search_trials": 10, "max_turns": 7, "thinking": "low"},
    }
    (tmp_path / "pq.json").write_text(json.dumps(get("positive-quadratic").to_json()))

    evaluate.run(manifest, tmp_path / "out", arms=("text", "images"),
                 provider="somewhere", model="some-model", repo_root=tmp_path,
                 launcher=fake_launcher, log=lambda *_: None)

    assert len(calls) == 2
    text_cmd, image_cmd = calls
    assert text_cmd[text_cmd.index("--images") + 1] == "false"
    assert image_cmd[image_cmd.index("--images") + 1] == "true"
    # everything except the flag and the output directory must match
    def without_variable_parts(cmd):
        out = list(cmd)
        del out[out.index("--images"):out.index("--images") + 2]
        del out[out.index("--out-dir"):out.index("--out-dir") + 2]
        return out
    assert without_variable_parts(text_cmd) == without_variable_parts(image_cmd)
    assert text_cmd[text_cmd.index("--max-turns") + 1] == "7"
    assert text_cmd[text_cmd.index("--thinking") + 1] == "low"
    assert text_cmd[text_cmd.index("--model") + 1] == "some-model"


def test_a_model_arm_reads_its_outcome_from_the_kernel_not_from_prose(tmp_path):
    """The run's own summary is narrative. Only proof.json and the journal
    decide what an arm achieved."""
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    (out_dir / "proof.json").write_text(json.dumps(
        {"verified_by": "sandbox", "method": "counterexample", "claim": "DISPROVED"}))
    (out_dir / "runtime.json").write_text(json.dumps(
        {"provider": "somewhere", "model": "some-model"}))
    (out_dir / "trace.jsonl").write_text("\n".join([
        json.dumps({"event": "header"}),
        json.dumps({"step": 1, "tool": "look", "error": False}),
        json.dumps({"step": 2, "tool": "certify", "error": True}),
        json.dumps({"step": 3, "tool": "set_var", "error": False, "actor": "user"}),
        json.dumps({"step": 4, "tool": "finish", "error": False,
                    "result": "I have proved the theorem"}),
    ]))
    result = evaluate.run_model_arm(
        tmp_path / "spec.json", "t", "text", 1, out_dir=out_dir,
        budget={"max_turns": 5}, provider=None, model=None, repo_root=tmp_path,
        launcher=lambda command, repo_root: 0)

    assert result.verified_by == "sandbox" and result.certified is True
    assert result.tool_errors == 1
    assert result.human_interventions == 1
    assert result.turns == 4
    assert "proved the theorem" not in json.dumps(result.to_json())


def test_scoring_counts_and_never_picks_a_winner():
    rows = [
        evaluate.ArmResult(task="t", arm="search", seed=1, certified=False),
        evaluate.ArmResult(task="t", arm="search", seed=2, certified=False),
        evaluate.ArmResult(task="t", arm="text", seed=1, certified=True,
                           verified_by="sandbox", turns=12),
        evaluate.ArmResult(task="t", arm="text", seed=2, certified=False, turns=30),
    ]
    per_arm = evaluate.score(rows)
    assert per_arm["search"]["certified_solve_rate"] == 0.0
    assert per_arm["text"]["certified_solve_rate"] == 0.5
    assert per_arm["text"]["verified_by"]["sandbox"] == 1

    manifest = {"required_improvement": {"certified_solve_rate_over_search": 0.25}}
    comparison = evaluate.compare(per_arm, manifest)
    row = next(r for r in comparison if r["arm"] == "text")
    assert row["improvement"] == 0.5
    assert row["meets_declared_threshold"] is True
    # the report states the gap; it never says which arm to keep
    text = evaluate.format_report({
        "format": evaluate.MANIFEST_VERSION,
        "manifest": {"name": "x", **manifest},
        "per_arm": per_arm, "comparison": comparison, "skipped": [], "results": [],
    })
    assert "meets" in text
    for word in ("should", "recommend", "better", "use images", "winner"):
        assert word not in text.lower()


def test_eval_cli_defaults_to_the_offline_arm(tmp_path, capsys):
    """Model arms spend real API calls, so `simagent eval` with no --arms must
    not start one by surprise."""
    from types import SimpleNamespace

    from simagent.cli import _cmd_eval

    args = SimpleNamespace(manifest=None, arms=None, provider=None, model=None,
                           out=str(tmp_path / "out"), dry_run=True)
    assert _cmd_eval(args) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["format"] == evaluate.MANIFEST_VERSION
