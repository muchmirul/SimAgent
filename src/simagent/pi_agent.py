"""Thin Python client for the TypeScript pi control service.

The service owns provider auth, model turns, steering, and pi session branches.
Python only transports commands and continues to own the math kernel behind
``kernel_transport.py``. No response from this module can mint a verdict.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any


class PiAgentError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class PiAgentClient:
    """Correlated LF-delimited client for ``agent/dist/service.js``."""

    def __init__(self, runs_root: str | Path, *, repo_root: str | Path | None = None):
        self.repo_root = Path(repo_root or Path(__file__).resolve().parents[2]).resolve()
        self.runs_root = Path(runs_root).resolve()
        self._process: subprocess.Popen[str] | None = None
        self._pending: dict[str, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._stderr: deque[str] = deque(maxlen=40)
        self._sequence = 0
        self._closed = False

    def _service_path(self) -> Path:
        configured = os.environ.get("SIMAGENT_PI_SERVICE")
        if configured:
            return Path(configured).expanduser().resolve()
        return self.repo_root / "agent" / "dist" / "service.js"

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None:
            if self._process.poll() is None:
                return self._process
            detail = "\n".join(self._stderr).strip()
            raise PiAgentError(
                "EXITED", "pi agent service exited" + (f": {detail}" if detail else "")
            )
        with self._start_lock:
            if self._closed:
                raise PiAgentError("CLOSED", "pi agent service is closed")
            if self._process is not None:
                if self._process.poll() is None:
                    return self._process
                raise PiAgentError("EXITED", "pi agent service exited")
            service = self._service_path()
            if not service.is_file():
                raise PiAgentError(
                    "NOT_BUILT",
                    f"pi runtime is not built: {service} (run `cd agent && npm ci && npm run build`)",
                )
            node = os.environ.get("SIMAGENT_PI_NODE") or shutil.which("node")
            if not node:
                raise PiAgentError("NO_NODE", "Node.js >=22.19 is required for pi agent mode")
            self.runs_root.mkdir(parents=True, exist_ok=True)
            args = [
                node,
                str(service),
                "--runs-root",
                str(self.runs_root),
                "--repo-root",
                str(self.repo_root),
                "--python-path",
                sys.executable,
                "--session-dir",
                str(self.runs_root / ".pi-sessions"),
            ]
            self._process = subprocess.Popen(
                args,
                cwd=self.repo_root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
            threading.Thread(target=self._read_stdout, daemon=True).start()
            threading.Thread(target=self._read_stderr, daemon=True).start()
            return self._process

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        failure: Exception | None = None
        try:
            for raw in process.stdout:
                try:
                    response = json.loads(raw)
                    request_id = response.get("id")
                    if not isinstance(request_id, str):
                        raise ValueError("response has no string id")
                except (ValueError, json.JSONDecodeError) as exc:
                    failure = PiAgentError("PROTOCOL", f"invalid pi service response: {exc}")
                    break
                with self._pending_lock:
                    waiting = self._pending.pop(request_id, None)
                if waiting is None:
                    failure = PiAgentError("PROTOCOL", f"unexpected pi response id {request_id}")
                    break
                waiting.put(response)
        finally:
            detail = "\n".join(self._stderr).strip()
            error = failure or PiAgentError(
                "EXITED",
                "pi agent service exited" + (f": {detail}" if detail else ""),
            )
            with self._pending_lock:
                pending = list(self._pending.values())
                self._pending.clear()
            for waiting in pending:
                waiting.put(error)

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            self._stderr.append(line.rstrip())

    def _request(self, op: str, *, timeout: float = 30.0, **payload) -> Any:
        process = self._ensure_process()
        if process.stdin is None:
            raise PiAgentError("EXITED", "pi agent service has no stdin")
        waiting: queue.Queue = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._sequence += 1
            request_id = f"py-{self._sequence}"
            self._pending[request_id] = waiting
        frame = json.dumps({"id": request_id, "op": op, **payload}, separators=(",", ":")) + "\n"
        try:
            with self._write_lock:
                process.stdin.write(frame)
                process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise PiAgentError("EXITED", f"could not write to pi agent service: {exc}") from exc
        try:
            response = waiting.get(timeout=timeout)
        except queue.Empty as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise PiAgentError("TIMEOUT", f"pi agent service timed out during {op}") from exc
        if isinstance(response, Exception):
            raise response
        if not response.get("ok"):
            error = response.get("error") or {}
            raise PiAgentError(
                str(error.get("code") or "INTERNAL"),
                str(error.get("message") or "pi request failed"),
            )
        return response.get("result")

    def start(
        self,
        *,
        problem_id: str | None = None,
        spec_path: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        thinking_level: str = "medium",
        max_turns: int = 40,
        run_base: str | None = None,
        images: bool = False,
    ) -> dict:
        payload: dict[str, Any] = {
            "thinkingLevel": thinking_level,
            "maxTurns": max_turns,
            # numbers-first: pictures go to the notebook, and to the model only
            # when this run is the image arm
            "images": bool(images),
        }
        if problem_id is not None:
            payload["problemId"] = problem_id
        if spec_path is not None:
            payload["specPath"] = str(Path(spec_path).resolve())
        if provider is not None:
            payload["provider"] = provider
        if model is not None:
            payload["model"] = model
        if run_base is not None:
            payload["runBase"] = run_base
        return self._request("start", timeout=60.0, **payload)

    def status(self, run: str) -> dict:
        return self._request("status", timeout=10.0, run=run)

    def events(self, run: str, after: int = 0) -> dict:
        return self._request("events", timeout=10.0, run=run, after=after)

    def comment(self, run: str, text: str, target: dict) -> dict:
        return self._request("comment", run=run, text=text, target=target)

    def pause(self, run: str) -> dict:
        """Hold the model at its next settled boundary; human moves still run."""
        return self._request("pause", run=run)

    def resume(self, run: str) -> dict:
        return self._request("resume", run=run)

    def user_action(self, run: str, tool: str, args: dict) -> dict:
        """The human's own world move inside a live run (transport only)."""
        return self._request("userAction", run=run, tool=tool, args=args)

    def stop(self, run: str) -> dict:
        return self._request("stop", timeout=60.0, run=run)

    def branch(
        self,
        run: str,
        step: int,
        *,
        comment: str | None = None,
        target: dict | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"run": run, "step": step}
        if comment is not None:
            payload["comment"] = comment
        if target is not None:
            payload["target"] = target
        return self._request("branch", timeout=120.0, **payload)

    def structured(
        self,
        *,
        system: str,
        prompt: str,
        tool_name: str,
        tool_description: str,
        schema: dict,
        provider: str | None = None,
        model: str | None = None,
    ) -> dict:
        """One schema-shaped question to whatever model pi routes.

        Transport only: the reply is raw model output, and nothing here can
        make it valid. `validate_claim` remains the gate.
        """
        payload: dict = {
            "system": system,
            "prompt": prompt,
            "toolName": tool_name,
            "toolDescription": tool_description,
            "schema": schema,
        }
        if provider is not None:
            payload["provider"] = provider
        if model is not None:
            payload["model"] = model
        return self._request("structured", timeout=300.0, **payload)

    def models(self) -> list[dict]:
        return self._request("models", timeout=30.0)

    def close(self) -> None:
        if self._closed:
            return
        process = self._process
        if process is not None and process.poll() is None:
            try:
                self._request("shutdown", timeout=30.0)
            except PiAgentError:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self._closed = True
