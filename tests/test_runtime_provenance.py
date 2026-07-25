"""Which model produced a run.

SimAgent harnesses whatever model pi routes: that is the standard, not a
defect. But a result is only attributable and comparable if the run records
WHICH model produced it, and until now the only trace lived outside the run
directory in pi's own session log.
"""
import json

import pytest

from simagent.kernel_transport import KernelTransport
from simagent.library import get


def _transport(tmp_path):
    return KernelTransport(get("positive-quadratic"), out_dir=tmp_path)


def test_the_model_is_recorded_as_run_provenance(tmp_path):
    t = _transport(tmp_path)
    t.set_runtime({"provider": "openai-codex", "model": "gpt-5.4",
                   "thinkingLevel": "medium"})
    t.stop("done")
    t.finalize()
    info = json.loads((tmp_path / "runtime.json").read_text())
    assert info["provider"] == "openai-codex"
    assert info["model"] == "gpt-5.4"
    assert "openai-codex/gpt-5.4" in (tmp_path / "agent_summary.md").read_text()


def test_an_unrecorded_model_is_said_plainly(tmp_path):
    """Silence would read as 'this was the expected model'."""
    t = _transport(tmp_path)
    t.stop("done")
    t.finalize()
    assert not (tmp_path / "runtime.json").exists()
    assert "not recorded" in (tmp_path / "agent_summary.md").read_text()


@pytest.mark.parametrize("payload", [
    {}, {"provider": "p"}, {"model": "m"}, {"provider": "", "model": "m"},
    {"provider": "p", "model": "  "},
])
def test_an_incomplete_runtime_record_is_refused(tmp_path, payload):
    with pytest.raises(ValueError):
        _transport(tmp_path).set_runtime(payload)


def test_recording_the_model_does_not_touch_the_journal(tmp_path):
    """Provenance is about the RUN, not an event in the world's history.
    A journal record would shift every sequence number and change what a
    branch prefix means."""
    t = _transport(tmp_path)
    before = t.snapshot()
    t.set_runtime({"provider": "p", "model": "m"})
    after = t.snapshot()
    assert after["stateHash"] == before["stateHash"]
    assert after["journalSeq"] == before["journalSeq"]
