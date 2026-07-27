"""Standalone JSONL transport for the SimAgent Python kernel.

This module is intentionally provider- and UI-agnostic.  A controller sends
one LF-delimited JSON request at a time; the transport delegates every tool to
:class:`simagent.agent.AgentRun`, then returns text/image content blocks.  It
adds correlation and replay plumbing only: proof construction and verdicts
remain in the existing Python kernel.

Protocol (one response for every request)::

    {"id":"1", "op":"describe"}
    {"id":"2", "op":"call", "toolCallId":"call-7",
     "name":"look", "args":{}}
    {"id":"3", "op":"userAction", "name":"set_var", "args":{...}}
    {"id":"4", "op":"annotate", "kind":"user_comment", "payload":{...}}
    {"id":"5", "op":"stop", "summary":"stopped by the user"}
    {"id":"6", "op":"snapshot"}
    {"id":"7", "op":"finalize"}

The append-only ``kernel-journal.jsonl`` stores every tool call, human world
move, thought, annotation, and stop boundary. Tool calls keep the unchanged Pi ``toolCallId``;
every event carries a hash of the resulting kernel state. A new transport can
replay a journal prefix, and replay fails closed if any state hash differs.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from .agent import AgentRun, SYSTEM, TOOLS, _task_prompt
from .library import get as get_bundled
from .spec import ProblemSpec

JOURNAL_FILE = "kernel-journal.jsonl"
JOURNAL_VERSION = 3  # 3 adds user_action events and actor attribution

_ANNOTATION_KINDS = frozenset({"user_comment", "provenance"})
# World moves a human may make mid-run. Deliberately excludes every instrument
# that can establish something: what counts as proved stays the model's call.
_USER_TOOLS = frozenset({"sample", "set_var", "nudge", "construct"})
_THOUGHT_KINDS = frozenset({"text", "thinking", "user"})


class KernelReplayError(RuntimeError):
    """Raised when a journal prefix cannot be reproduced exactly."""


def _jsonable(value: Any) -> Any:
    """Convert kernel values to stable, strict-JSON data."""
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _proof_state(run: AgentRun) -> dict[str, Any] | None:
    """Canonical proof-attempt state, excluding output-directory artifacts."""
    if run.deductive is None:
        return None
    proof = run.deductive
    return {
        "method": proof.method.value,
        "claim": proof.claim,
        "verifiedBy": proof.verified_by,
        "argument": proof.argument,
        "witness": proof.witness,
        "statementReview": proof.statement_review,
        "leanOk": (proof.lean_report or {}).get("ok"),
        "leanAxiomClean": (proof.lean_report or {}).get("axiom_clean"),
    }


def _state(run: AgentRun) -> dict[str, Any]:
    """Canonical executable state used to verify exact journal replay.

    Narrative trace contents are deliberately outside this hash, but every
    value that can affect later world operations, proof results, or mechanical
    expectation scoring belongs here. In particular, free coordinates alone
    are insufficient: constructed entities and pending expectations must also
    survive and verify across a branch.
    """
    world = run.session.world
    entities = []
    for entity in world.entities.values():
        item: dict[str, Any] = {"name": entity.name, "kind": entity.kind}
        if entity.kind == "free":
            space = entity.space
            item["space"] = {
                "type": type(space).__name__,
                "shape": list(space.shape),
                "low": space.low,
                "high": space.high,
            }
        else:
            item.update({"ctor": entity.ctor, "args": list(entity.args)})
        entities.append(item)

    report = run.best_report()
    return _jsonable(
        {
            "spec": run.spec.to_json(),
            "world": {"entities": entities, "values": world.values},
            # Keep the historical projection for service clients and tests.
            "vars": run.session.vars,
            "check": run.session._check(),
            "rngState": run.session.rng.bit_generator.state,
            "huntSeed": run.session._hunt_seed,
            "lastReport": run.session.last_report,
            "bestReport": report,
            "certifyReport": run.certify_report,
            "declaredPlans": run.declared_plans,
            "openExpectations": run.open_expectations,
            "scoredExpectations": run.scored_expectations,
            "expectationSequence": run._expectation_seq,
            "artifactCounters": {
                "dispatch": run.seq,
                "looks": run.looks,
                "views": run.views_taken,
                "imaginings": run.imaginings,
            },
            "deductiveProof": _proof_state(run),
            "finished": run.finished,
            "stopRequested": run.stop_requested,
            "summary": run.summary,
        }
    )


def _state_hash(state: dict[str, Any]) -> str:
    payload = json.dumps(
        state, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _result_summary(content: str | list[dict]) -> Any:
    """Journal a useful result without duplicating base64 image payloads."""
    if isinstance(content, str):
        return content
    summary: list[dict[str, Any]] = []
    for block in content:
        if block.get("type") == "image":
            source = block.get("source") or {}
            summary.append(
                {
                    "type": "image",
                    "mimeType": source.get("media_type"),
                    "base64Chars": len(source.get("data") or ""),
                }
            )
        else:
            summary.append(_jsonable(block))
    return summary


def _transport_content(content: str | list[dict]) -> list[dict[str, Any]]:
    """Translate the legacy Anthropic-shaped image block to neutral blocks."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    blocks: list[dict[str, Any]] = []
    for block in content:
        if block.get("type") == "image":
            source = block["source"]
            blocks.append(
                {
                    "type": "image",
                    "data": source["data"],
                    "mimeType": source["media_type"],
                }
            )
        elif block.get("type") == "text":
            blocks.append({"type": "text", "text": str(block.get("text", ""))})
        else:
            raise TypeError(f"unsupported kernel result block: {block.get('type')!r}")
    return blocks


def _read_records(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read a journal, ignoring only a malformed trailing partial line."""
    records: list[dict[str, Any]] = []
    lines = Path(path).read_text().splitlines()
    for index, line in enumerate(lines):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            if index != len(lines) - 1:
                raise KernelReplayError(f"malformed journal line {index + 1}") from None
    if not records or records[0].get("event") != "header":
        raise KernelReplayError("journal has no valid header")
    return records[0], [
        r
        for r in records[1:]
        if r.get("event") in {"call", "user_action", "note", "annotation", "stop"}
    ]


def read_journal(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compatibility reader returning only model tool calls."""
    header, records = _read_records(path)
    return header, [record for record in records if record.get("event") == "call"]


class KernelTransport:
    """One mutable :class:`AgentRun` behind an append-only replay journal."""

    def __init__(
        self,
        spec: ProblemSpec,
        out_dir: str | Path,
        *,
        replay_journal: str | Path | None = None,
        replay_through: int | None = None,
    ):
        if replay_journal is None and replay_through is not None:
            raise ValueError("replay_through requires replay_journal")
        self.out = Path(out_dir)
        journal_path = self.out / JOURNAL_FILE
        if journal_path.exists():
            raise FileExistsError(f"refusing to overwrite existing journal: {journal_path}")
        self.run = AgentRun(spec, self.out)
        self.path = journal_path
        self._fh = self.path.open("x", encoding="utf-8")
        self._closed = False
        self.journal_seq = 0
        self._write(
            {
                "event": "header",
                "version": JOURNAL_VERSION,
                "specId": spec.id,
                "state": _state(self.run),
                "stateHash": _state_hash(_state(self.run)),
                "provenance": (
                    {
                        "journal": str(Path(replay_journal).resolve()),
                        "through": replay_through,
                    }
                    if replay_journal is not None
                    else None
                ),
            }
        )
        if replay_journal is not None:
            try:
                self._replay(replay_journal, replay_through)
            except Exception:
                # A rejected prefix is a normal fail-closed path. Do not leave
                # the partially replayed transport's three owned files open.
                self._fh.close()
                self.run._transcript.close()
                self.run.trace.close()
                self._closed = True
                raise

    def _write(self, record: dict[str, Any]) -> None:
        self._fh.write(json.dumps(_jsonable(record), ensure_ascii=False, allow_nan=False) + "\n")
        self._fh.flush()

    def describe(self) -> dict[str, Any]:
        return {
            "protocolVersion": 2,
            "journalVersion": JOURNAL_VERSION,
            "specId": self.run.spec.id,
            "title": self.run.spec.title,
            "systemPrompt": SYSTEM,
            "taskPrompt": _task_prompt(self.run.spec),
            "tools": TOOLS,
            "journalPath": str(self.path.resolve()),
        }

    def snapshot(self) -> dict[str, Any]:
        state = _state(self.run)
        return {
            "journalSeq": self.journal_seq,
            "traceStep": self.run.trace.steps,
            "journalPath": str(self.path.resolve()),
            "state": state,
            "stateHash": _state_hash(state),
            "finished": self.run.finished,
        }

    def call_tool(self, tool_call_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("kernel transport is finalized")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise ValueError("toolCallId must be a non-empty string")
        if not isinstance(name, str) or not name:
            raise ValueError("tool name must be a non-empty string")
        if not isinstance(args, dict):
            raise ValueError("tool args must be an object")

        content, is_error = self.run.dispatch(name, args, tool_call_id=tool_call_id)
        self.journal_seq += 1
        state = _state(self.run)
        digest = _state_hash(state)
        self._write(
            {
                "event": "call",
                "seq": self.journal_seq,
                "toolCallId": tool_call_id,
                "tool": name,
                "args": args,
                "result": _result_summary(content),
                "isError": is_error,
                "finished": self.run.finished,
                "state": state,
                "stateHash": digest,
            }
        )
        return {
            "toolCallId": tool_call_id,
            "content": _transport_content(content),
            "isError": is_error,
            "finished": self.run.finished,
            "journalSeq": self.journal_seq,
            "traceStep": self.run.trace.steps,
            "journalPath": str(self.path.resolve()),
            "state": state,
            "stateHash": digest,
        }

    def user_action(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Let the HUMAN move the world during a run, on the record.

        This is the other half of collaboration: a comment can only suggest,
        while a stuck run often needs someone to just place the point. It is a
        real world change, so it cannot ride the annotation path (which must
        not alter state); it is a journalled, replayable, hash-checked event
        like any tool call, attributed to ``user`` so the trace never credits
        the model with a move it did not make. Only world moves are allowed:
        truth-making instruments stay the model's to call.
        """
        if self._closed:
            raise RuntimeError("kernel transport is finalized")
        if name not in _USER_TOOLS:
            raise ValueError(
                f"tool {name!r} is not a human world move; allowed: {sorted(_USER_TOOLS)}"
            )
        if not isinstance(args, dict):
            raise ValueError("tool args must be an object")
        self.journal_seq += 1
        content, is_error = self.run.dispatch(
            name, args, tool_call_id=f"user-{self.journal_seq}", actor="user"
        )
        state = _state(self.run)
        digest = _state_hash(state)
        self._write(
            {
                "event": "user_action",
                "seq": self.journal_seq,
                "tool": name,
                "args": args,
                "result": _result_summary(content),
                "isError": is_error,
                "state": state,
                "stateHash": digest,
            }
        )
        return {
            "tool": name,
            "content": _transport_content(content),
            "isError": is_error,
            "journalSeq": self.journal_seq,
            "traceStep": self.run.trace.steps,
            "state": state,
            "stateHash": digest,
            "finished": self.run.finished,
        }

    def note_thought(self, text: str, kind: str = "text") -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("kernel transport is finalized")
        if kind not in _THOUGHT_KINDS:
            raise ValueError(f"unsupported thought kind {kind!r}")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("thought text must be non-empty")
        self.run.note_thought(text, kind=kind)
        self.journal_seq += 1
        state = _state(self.run)
        record = {
            "event": "note",
            "seq": self.journal_seq,
            "kind": kind,
            "text": text,
            "stateHash": _state_hash(state),
            "traceStep": self.run.trace.steps,
        }
        self._write(record)
        return self.snapshot()

    def set_runtime(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record WHICH model is driving this run.

        SimAgent harnesses whatever model pi routes, so a result is only
        attributable and comparable if the run says which one produced it.
        This is provenance about the run, not an event in the world's history,
        so it is deliberately NOT a journal record: writing one would shift
        every sequence number and change what a branch prefix means.
        """
        if self._closed:
            raise RuntimeError("kernel transport is finalized")
        if not isinstance(payload, dict):
            raise ValueError("runtime payload must be an object")
        for field in ("provider", "model"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"runtime payload needs a non-empty {field}")
        self.run.runtime_info = {k: payload[k] for k in sorted(payload)}
        return self.snapshot()

    def annotate(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Journal narrative metadata without changing proof or world state."""
        if self._closed:
            raise RuntimeError("kernel transport is finalized")
        if kind not in _ANNOTATION_KINDS:
            raise ValueError(f"unsupported annotation kind {kind!r}")
        if not isinstance(payload, dict):
            raise ValueError("annotation payload must be an object")
        if kind == "user_comment":
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("user_comment text must be non-empty")
            if not isinstance(payload.get("target"), dict):
                raise ValueError("user_comment target must be an object")
        before = self.snapshot()
        entry = self.run.trace.annotate(kind, payload)
        self.journal_seq += 1
        after = self.snapshot()
        if after["stateHash"] != before["stateHash"]:
            raise RuntimeError("annotation changed kernel state")
        self._write(
            {
                "event": "annotation",
                "seq": self.journal_seq,
                "kind": kind,
                "payload": payload,
                "traceStep": entry["step"],
                "stateHash": after["stateHash"],
            }
        )
        return after

    def stop(self, summary: str = "session stopped by the user") -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("kernel transport is finalized")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("stop summary must be non-empty")
        self.run.stop()
        self.run.summary = summary
        self.journal_seq += 1
        state = _state(self.run)
        self._write(
            {
                "event": "stop",
                "seq": self.journal_seq,
                "summary": summary,
                "stateHash": _state_hash(state),
                "traceStep": self.run.trace.steps,
            }
        )
        return self.snapshot()

    def _replay(self, source: str | Path, through: int | None) -> None:
        header, records = _read_records(source)
        if header.get("version") != JOURNAL_VERSION:
            raise KernelReplayError(
                f"unsupported journal version {header.get('version')!r}; expected {JOURNAL_VERSION}"
            )
        if header.get("specId") != self.run.spec.id:
            raise KernelReplayError(
                f"journal spec {header.get('specId')!r} != requested {self.run.spec.id!r}"
            )
        initial = self.snapshot()["stateHash"]
        if initial != header.get("stateHash"):
            raise KernelReplayError("initial kernel state does not match journal header")

        max_seq = max((int(entry.get("seq", 0)) for entry in records), default=0)
        limit = max_seq if through is None else through
        if not isinstance(limit, int) or limit < 0 or limit > max_seq:
            raise KernelReplayError(f"invalid replay prefix {limit!r}; journal tip is {max_seq}")
        expected_seq = 1
        for entry in records:
            seq = int(entry.get("seq", 0))
            if seq > limit:
                break
            if seq != expected_seq:
                raise KernelReplayError(
                    f"journal sequence is not contiguous at {seq}; expected {expected_seq}"
                )
            event = entry.get("event")
            if event == "call":
                result = self.call_tool(
                    str(entry.get("toolCallId") or ""),
                    str(entry.get("tool") or ""),
                    dict(entry.get("args") or {}),
                )
                if result["isError"] != bool(entry.get("isError")):
                    raise KernelReplayError(f"replay error status diverged at event {seq}")
            elif event == "user_action":
                result = self.user_action(
                    str(entry.get("tool") or ""), dict(entry.get("args") or {})
                )
                if result["isError"] != bool(entry.get("isError")):
                    raise KernelReplayError(f"replay error status diverged at event {seq}")
            elif event == "note":
                result = self.note_thought(
                    str(entry.get("text") or ""), str(entry.get("kind") or "")
                )
            elif event == "annotation":
                result = self.annotate(
                    str(entry.get("kind") or ""), dict(entry.get("payload") or {})
                )
            elif event == "stop":
                result = self.stop(str(entry.get("summary") or ""))
            else:  # pragma: no cover - _read_records filters this closed vocabulary
                raise KernelReplayError(f"unsupported journal event {event!r}")
            if result["stateHash"] != entry.get("stateHash"):
                raise KernelReplayError(f"replay state diverged at event {seq}")
            expected_seq += 1
        if self.journal_seq != limit:
            raise KernelReplayError(
                f"replayed {self.journal_seq} events but prefix requested {limit}"
            )

    def finalize(self) -> dict[str, Any]:
        if self._closed:
            return {"alreadyFinalized": True, **self.snapshot()}
        proof, report, artifacts = self.run.finalize()
        state = _state(self.run)
        result = {
            "proof": _jsonable(proof),
            "report": _jsonable(report),
            "artifacts": _jsonable(artifacts),
            "journalSeq": self.journal_seq,
            "traceStep": self.run.trace.steps,
            "journalPath": str(self.path.resolve()),
            "state": state,
            "stateHash": _state_hash(state),
            "finished": self.run.finished,
        }
        self._write({"event": "end", **result})
        self._fh.close()
        self._closed = True
        return result


def _load_spec(problem_id: str | None, spec_path: str | None) -> ProblemSpec:
    if bool(problem_id) == bool(spec_path):
        raise ValueError("provide exactly one of --problem-id or --spec")
    return get_bundled(problem_id) if problem_id else ProblemSpec.load(spec_path)


def serve(transport: KernelTransport, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    """Serve strict LF-delimited JSON until ``finalize`` or EOF."""
    try:
        for raw in stdin:
            request_id: Any = None
            request: dict[str, Any] = {}
            try:
                request = json.loads(raw)
                if not isinstance(request, dict):
                    raise ValueError("request must be a JSON object")
                request_id = request.get("id")
                op = request.get("op")
                if op == "describe":
                    result = transport.describe()
                elif op == "snapshot":
                    result = transport.snapshot()
                elif op == "userAction":
                    result = transport.user_action(
                        request.get("name"), request.get("args") or {}
                    )
                elif op == "call":
                    result = transport.call_tool(
                        request.get("toolCallId"), request.get("name"), request.get("args") or {}
                    )
                elif op == "note":
                    result = transport.note_thought(
                        request.get("text"), request.get("kind") or "text"
                    )
                elif op == "runtime":
                    result = transport.set_runtime(request.get("payload") or {})
                elif op == "annotate":
                    result = transport.annotate(
                        request.get("kind"), request.get("payload") or {}
                    )
                elif op == "stop":
                    result = transport.stop(
                        request.get("summary") or "session stopped by the user"
                    )
                elif op == "finalize":
                    result = transport.finalize()
                else:
                    raise ValueError(f"unsupported operation {op!r}")
                response = {"id": request_id, "ok": True, "result": result}
            except Exception as exc:  # fail closed, but keep protocol synchronized
                response = {
                    "id": request_id,
                    "ok": False,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
            stdout.flush()
            if request.get("op") == "finalize" and response["ok"]:
                return
    finally:
        if not transport._closed:
            transport.finalize()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SimAgent kernel JSONL transport")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--problem-id", help="bundled problem id")
    source.add_argument("--spec", help="path to a ProblemSpec JSON file")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--replay-journal")
    parser.add_argument("--replay-through", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        spec = _load_spec(args.problem_id, args.spec)
        transport = KernelTransport(
            spec,
            args.out_dir,
            replay_journal=args.replay_journal,
            replay_through=args.replay_through,
        )
        serve(transport)
        return 0
    except Exception as exc:
        print(f"kernel transport failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
