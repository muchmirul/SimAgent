"""When a loop of adopted runs should stop, and how a round is read.

A run ends at its turn budget whether or not the claim is settled, and adopting
lets the next run continue it. That turns "one run" into "a loop", and a loop
needs a rule for when to stop that the model cannot influence. The rules live
here, once, because two callers apply them: `simagent agent --rounds N` and the
evaluation arms that measure whether rounds help. Two copies would be two rules
that drift, and the eval would then be scoring a loop nobody runs.

Every rule is mechanical and every unknown falls toward "nothing established":

  * the kernel stamped something in that round      -> settled, stop
  * the round recorded no act of its own            -> the next one would only
                                                       replay the same history
                                                       at the same price, stop
  * the runtime exited non-zero                     -> stop; do not retry a
                                                       failure N times
  * otherwise                                       -> continue until the
                                                       budget declared up front

Nothing here reads the model's opinion that it is finished, and nothing here
mints a verdict: `verified_by` is copied from the round's own metrics.json,
which only `proof.py` can have written.
"""
from __future__ import annotations

import json
from pathlib import Path


def read_round(index: int, round_out: str | Path, code: int) -> dict:
    """What one round left behind, read off its own artifacts.

    A round that crashed before finalizing has no metrics.json, an unreadable
    one is treated as unrecorded rather than killing the loop mid-flight, and a
    round whose runtime exited non-zero is not credited with metrics at all:
    those could belong to an earlier invocation that used the same directory.
    """
    round_out = Path(round_out)
    record = {"round": index, "dir": str(round_out), "exit_code": code,
              "verified_by": "none", "ended_by": "", "turns": 0}
    metrics_path = round_out / "metrics.json"
    if code != 0 or not metrics_path.is_file():
        return record
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record["ended_by"] = "unreadable metrics.json"
        return record
    if not isinstance(metrics, dict):
        return record
    stamp = metrics.get("verified_by")
    record["verified_by"] = stamp if isinstance(stamp, str) and stamp else "none"
    record["ended_by"] = str(metrics.get("ended_by") or "")
    turns = metrics.get("turns")
    record["turns"] = turns if isinstance(turns, int) else 0
    return record


def stop_reason(record: dict) -> str:
    """Why the loop should stop after this round, or "" to keep going."""
    if record["exit_code"] != 0:
        return f"the runtime exited {record['exit_code']}"
    if record["verified_by"] != "none":
        return f"the kernel stamped {record['verified_by']}"
    if record["turns"] == 0:
        return f"round {record['round']} recorded no acts of its own"
    return ""


def budget_spent(rounds: int) -> str:
    return f"the declared budget of {rounds} round(s) ran out"


def round_dir(out: str | Path, index: int, rounds: int) -> Path:
    """Where round `index` runs.

    A single round keeps the directory it was given, so an ordinary run looks
    exactly as it always did and every existing manifest still points at the
    right artifacts.
    """
    out = Path(out)
    return out if rounds == 1 else out / f"round-{index}"
