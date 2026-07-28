"""Does acting in the world help a model settle a claim?

`simagent bench` answers a different question: it checks known answers and how
strong the kernel is. It cannot say whether a model that samples, nudges,
refines and reads margins finds answers that one-shot reasoning and blind
search miss. That claim is the reason this project exists, and it is currently
unmeasured.

So: one task list, several arms on the SAME problems and the same budget, and
only mechanical outcomes scored. No prose is read, no answer is judged by a
model, and the improvement that would count is written into the manifest
BEFORE any arm runs, because a threshold chosen after seeing results is not a
threshold.

Arms:
  search  - automatic search alone, no model in the loop (the floor)
  text    - the tool loop with numbers-first senses (the default harness)
  images  - the same loop with pictures also sent to the model

This module runs arms and counts. It never decides what the numbers mean.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

MANIFEST_VERSION = "eval/1"
ARMS = ("search", "text", "images")

# The bundled task list. Versioned and small on purpose: a manifest that grows
# silently makes two runs incomparable while looking like the same experiment.
DEFAULT_MANIFEST = {
    "format": MANIFEST_VERSION,
    "name": "first-evaluation",
    "tasks": [
        {
            "id": "circumcenter-near-centroid",
            "spec": "problems/circumcenter-near-centroid.json",
            "seeds": [1, 2, 3],
            "why": (
                "automatic search missed the counterexample in 2000 trials while "
                "successive refine calls crossed the boundary, so it tests whether a "
                "model can find a multi-step path through the world rather than "
                "certify whatever it was handed"
            ),
        },
    ],
    # Declared before any result is seen. This is the whole point of writing it
    # down: it is a prediction, not a description.
    "required_improvement": {
        "certified_solve_rate_over_search": 0.25,
        "note": (
            "the model arms must certify at least 25 percentage points more runs "
            "than search alone on the same tasks and seeds, or the visual/experiential "
            "harness is not earning its cost"
        ),
    },
    "budget": {"max_turns": 40, "thinking": "medium", "search_trials": 2000},
}


@dataclass
class ArmResult:
    """One (task, arm, seed) run. Every field is machine-recorded."""

    task: str
    arm: str
    seed: int
    provider: str = ""
    model: str = ""
    thinking: str = ""
    max_turns: int = 0
    elapsed_s: float = 0.0
    turns: int = 0
    tool_errors: int = 0
    human_interventions: int = 0
    verdict: str = ""
    verified_by: str = "none"
    certified: bool = False
    branch_improved: bool = False
    error: str = ""
    out_dir: str = ""

    def to_json(self) -> dict:
        return asdict(self)


def load_manifest(path: str | Path | None = None) -> dict:
    if path is None:
        return json.loads(json.dumps(DEFAULT_MANIFEST))
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != MANIFEST_VERSION:
        raise ValueError(f"not a {MANIFEST_VERSION} manifest: {path}")
    return data


def _load_task_spec(task: dict, repo_root: Path):
    from .spec import ProblemSpec

    return ProblemSpec.load(repo_root / task["spec"])


def seed_settles_the_claim(spec, seed: int) -> bool:
    """True when the very first sampled configuration already decides it.

    A seed like that measures nothing: every arm "wins" at step zero, including
    the one with no model in it.
    """
    import numpy as np

    from .core.space import sample_vars

    comp = spec.compiled()
    rng = np.random.default_rng(seed)
    for _ in range(64):
        variables = sample_vars(rng, spec)
        try:
            if not comp.valid(**variables):
                continue
            result = comp.check(**variables)
        except Exception:  # noqa: BLE001 - an unusable sample is not a settled claim
            return False
        decided = (result.margin < 0) if spec.quantifier == "forall" else (result.margin > 0)
        return bool(decided)
    return False


def run_search_arm(spec, seed: int, trials: int, out_dir: Path) -> ArmResult:
    """The floor: no model, no world actions, just sampling and annealing."""
    from .proof import mechanized_proof
    from .search import exhaustible, run_exhaustive, run_search

    started = time.monotonic()
    result = ArmResult(task=spec.id, arm="search", seed=seed, out_dir=str(out_dir))
    try:
        report = run_exhaustive(spec) if exhaustible(spec) else run_search(
            spec, trials=trials, seed=seed)
        proof = mechanized_proof(spec, report, out_dir=out_dir)
        result.verdict = report.verdict
        result.certified = bool(report.certified)
        result.verified_by = proof.verified_by if proof is not None else "none"
    except Exception as exc:  # noqa: BLE001 - a failed arm is a recorded outcome
        result.error = f"{type(exc).__name__}: {exc}"
    result.elapsed_s = round(time.monotonic() - started, 3)
    return result


def _read_run_outcome(out_dir: Path, result: ArmResult) -> None:
    """Fill a model arm's result from what the run left on disk.

    Everything here is kernel state or a journal count. Nothing reads the
    model's prose, because prose is not an outcome.
    """
    proof_path = out_dir / "proof.json"
    if proof_path.is_file():
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        result.verified_by = proof.get("verified_by", "none")
        result.verdict = proof.get("claim", "") or proof.get("method", "")
        result.certified = result.verified_by != "none"
    runtime_path = out_dir / "runtime.json"
    if runtime_path.is_file():
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        result.provider = runtime.get("provider", "")
        result.model = runtime.get("model", "")
    trace_path = out_dir / "trace.jsonl"
    if trace_path.is_file():
        steps = 0
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("event") is not None:
                continue
            steps += 1
            if record.get("error"):
                result.tool_errors += 1
            if record.get("actor") not in (None, "model"):
                result.human_interventions += 1
        result.turns = steps


def run_model_arm(spec_path: Path, task_id: str, arm: str, seed: int, *,
                  out_dir: Path, budget: dict, provider: str | None,
                  model: str | None, repo_root: Path,
                  launcher=None) -> ArmResult:
    """One agent run through the pi runtime, with the image channel on or off.

    `launcher` exists so the wiring can be tested offline; the default really
    starts the runtime.
    """
    result = ArmResult(
        task=task_id, arm=arm, seed=seed,
        thinking=budget.get("thinking", "medium"),
        max_turns=int(budget.get("max_turns", 40)),
        provider=provider or "", model=model or "",
        out_dir=str(out_dir),
    )
    command = [
        "run",
        "--spec", str(spec_path),
        "--out-dir", str(out_dir),
        "--thinking", result.thinking,
        "--max-turns", str(result.max_turns),
        "--images", "true" if arm == "images" else "false",
        "--seed", str(seed),
    ]
    if provider and model:
        command += ["--provider", provider, "--model", model]
    started = time.monotonic()
    try:
        code = (launcher or _launch_pi)(command, repo_root)
        if code != 0:
            result.error = f"runtime exited {code}"
    except Exception as exc:  # noqa: BLE001 - a broken arm is data, not a crash
        result.error = f"{type(exc).__name__}: {exc}"
    result.elapsed_s = round(time.monotonic() - started, 3)
    _read_run_outcome(out_dir, result)
    return result


def _launch_pi(command: list[str], repo_root: Path) -> int:
    pi_cli = Path(os.environ.get("SIMAGENT_PI_CLI", repo_root / "agent" / "dist" / "cli.js"))
    if not pi_cli.is_file():
        raise RuntimeError(f"pi runtime is not built: {pi_cli}")
    node = os.environ.get("SIMAGENT_PI_NODE") or shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required to run a model arm")
    return subprocess.run([node, str(pi_cli), *command], cwd=repo_root,
                          check=False).returncode


def score(results: list[ArmResult]) -> dict:
    """Mechanical counts per arm, plus the comparison the manifest declared.

    Rates only: certified solve rate, verified_by counts, median turns, branch
    improvements. No arm is called better here; the manifest's threshold is
    compared and reported, and reading it is the human's job.
    """
    per_arm: dict[str, dict] = {}
    for arm in ARMS:
        rows = [r for r in results if r.arm == arm]
        if not rows:
            continue
        certified = [r for r in rows if r.certified]
        turns = sorted(r.turns for r in rows if r.turns)
        per_arm[arm] = {
            "runs": len(rows),
            "certified": len(certified),
            "certified_solve_rate": round(len(certified) / len(rows), 4),
            "verified_by": _counts(r.verified_by for r in rows),
            "median_turns": turns[len(turns) // 2] if turns else None,
            "tool_errors": sum(r.tool_errors for r in rows),
            "human_interventions": sum(r.human_interventions for r in rows),
            "branch_improved": sum(1 for r in rows if r.branch_improved),
            "errored": sum(1 for r in rows if r.error),
        }
    return per_arm


def _counts(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return out


def separation(results: list[ArmResult]) -> list[dict]:
    """Which tasks can tell the arms apart at all.

    A task that automatic search already certifies carries no signal about the
    loop: every arm wins, so averaging it in only moves every rate toward 1 and
    hides the tasks that matter. Reported per task rather than dropped, because
    the reader has to know the manifest contained one.
    """
    tasks: dict[str, dict] = {}
    for row in results:
        seen = tasks.setdefault(row.task, {"task": row.task, "search_certified": 0,
                                           "search_runs": 0})
        if row.arm == "search":
            seen["search_runs"] += 1
            seen["search_certified"] += 1 if row.certified else 0
    for seen in tasks.values():
        seen["separates"] = seen["search_runs"] > 0 and seen["search_certified"] == 0
        seen["why"] = ("search never settles it, so a model arm that does has shown "
                       "something search cannot do"
                       if seen["separates"]
                       else "search settles it on its own, so every arm wins and the "
                            "task says nothing about the loop")
    return list(tasks.values())


def compare(per_arm: dict, manifest: dict) -> list[dict]:
    """The declared threshold against what happened. States the gap; never
    concludes what to do about it."""
    required = float(manifest.get("required_improvement", {})
                     .get("certified_solve_rate_over_search", 0.0))
    floor = per_arm.get("search", {}).get("certified_solve_rate")
    rows = []
    for arm in ("text", "images"):
        got = per_arm.get(arm, {}).get("certified_solve_rate")
        if got is None or floor is None:
            continue
        rows.append({
            "arm": arm,
            "certified_solve_rate": got,
            "search_floor": floor,
            "improvement": round(got - floor, 4),
            "required": required,
            "meets_declared_threshold": (got - floor) >= required,
        })
    return rows


def run(manifest: dict, out_root: str | Path, *, arms=ARMS, provider=None,
        model=None, repo_root: Path | None = None, launcher=None,
        log=print) -> dict:
    """Every (task, seed, arm) in the manifest, recorded to one directory."""
    repo_root = Path(repo_root or Path(__file__).resolve().parents[2])
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    budget = manifest.get("budget", {})
    results: list[ArmResult] = []
    skipped: list[dict] = []

    for task in manifest["tasks"]:
        spec_path = (repo_root / task["spec"]).resolve()
        spec = _load_task_spec(task, repo_root)
        for seed in task["seeds"]:
            if seed_settles_the_claim(spec, seed):
                # Recorded, not silently dropped: a hidden skip makes the arms
                # look like they ran on tasks they never saw.
                skipped.append({"task": task["id"], "seed": seed,
                                "why": "the first sampled state already settles the claim"})
                log(f"[eval] skip {task['id']} seed {seed}: initial state settles it")
                continue
            for arm in arms:
                out_dir = out_root / f"{task['id']}-seed{seed}-{arm}"
                log(f"[eval] {task['id']} seed {seed} arm {arm}")
                if arm == "search":
                    out_dir.mkdir(parents=True, exist_ok=True)
                    result = run_search_arm(
                        spec, seed, int(budget.get("search_trials", 2000)), out_dir)
                else:
                    result = run_model_arm(
                        spec_path, task["id"], arm, seed, out_dir=out_dir,
                        budget=budget, provider=provider, model=model,
                        repo_root=repo_root, launcher=launcher)
                results.append(result)
                log(f"[eval]   -> verdict={result.verdict or '-'} "
                    f"verified_by={result.verified_by} "
                    f"{'error=' + result.error if result.error else ''}")

    per_arm = score(results)
    report = {
        "format": MANIFEST_VERSION,
        "manifest": manifest,
        "results": [r.to_json() for r in results],
        "skipped": skipped,
        "per_arm": per_arm,
        "separation": separation(results),
        "comparison": compare(per_arm, manifest),
    }
    (out_root / "eval.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def format_report(report: dict) -> str:
    lines = [f"manifest: {report['manifest'].get('name')} ({report['format']})", ""]
    lines.append(f"{'arm':8} {'runs':>5} {'certified':>10} {'rate':>7} {'median turns':>13} {'errors':>7}")
    for arm, row in report["per_arm"].items():
        lines.append(f"{arm:8} {row['runs']:5d} {row['certified']:10d} "
                     f"{row['certified_solve_rate']:7.2f} "
                     f"{str(row['median_turns'] or '-'):>13} {row['errored']:7d}")
    separating = [row for row in report.get("separation", []) if not row["separates"]]
    if separating:
        lines += ["", "tasks that cannot tell the arms apart:"]
        lines += [f"  {row['task']}: {row['why']}" for row in separating]
    if report["skipped"]:
        lines += ["", "skipped (not counted in any arm):"]
        lines += [f"  {s['task']} seed {s['seed']}: {s['why']}" for s in report["skipped"]]
    lines += ["", "against the improvement declared before the run:"]
    if not report["comparison"]:
        lines.append("  (no model arm ran, so there is nothing to compare)")
    for row in report["comparison"]:
        verdict = "meets" if row["meets_declared_threshold"] else "does NOT meet"
        lines.append(f"  {row['arm']}: {row['certified_solve_rate']:.2f} vs search "
                     f"{row['search_floor']:.2f} = {row['improvement']:+.2f} "
                     f"({verdict} the required {row['required']:+.2f})")
    return "\n".join(lines)
