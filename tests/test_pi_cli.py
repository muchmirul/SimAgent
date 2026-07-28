"""P6 CLI cutover: `simagent agent` launches the TypeScript pi runtime."""
from types import SimpleNamespace

from simagent.cli import _cmd_agent


def test_agent_cli_launches_pi_with_bundled_identity(tmp_path, monkeypatch):
    pi_cli = tmp_path / "cli.js"
    pi_cli.write_text("// test placeholder")
    monkeypatch.setenv("SIMAGENT_PI_CLI", str(pi_cli))
    monkeypatch.setenv("SIMAGENT_PI_NODE", "/test/node")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr("simagent.cli.subprocess.run", fake_run)
    args = SimpleNamespace(
        problem="circumcenter-in-triangle",
        spec=None,
        conjecture=None,
        out=str(tmp_path / "run"),
        provider="openai-codex",
        model="gpt-5.4",
        thinking="medium",
        max_turns=12,
        images=False,
    )
    assert _cmd_agent(args) == 7
    command = captured["command"]
    # numbers-first: the run says which sensory channel it gave the model, so a
    # later reader of the trace knows which evaluation arm it was
    assert command[command.index("--images") + 1] == "false"
    assert command[:3] == ["/test/node", str(pi_cli), "run"]
    assert command[command.index("--problem-id") + 1] == "circumcenter-in-triangle"
    assert "--spec" not in command, "bundled identity must survive into the proof trust check"
    assert command[command.index("--provider") + 1 : command.index("--provider") + 4] == [
        "openai-codex",
        "--model",
        "gpt-5.4",
    ]


def test_pi_client_sends_the_ops_the_service_declares(monkeypatch):
    """These wrappers are the only thing binding Python names to service ops.

    A rename on either side is silent otherwise: the request goes out, the
    service rejects an unknown op, and the failure surfaces far from the cause.
    """
    from simagent.pi_agent import PiAgentClient

    sent = []

    def fake_request(self, op, *, timeout=30.0, **payload):
        sent.append((op, payload))
        return {"ok": True}

    monkeypatch.setattr(PiAgentClient, "_request", fake_request)
    client = PiAgentClient("/tmp/does-not-need-to-exist")

    client.user_action("run-1", "set_var", {"name": "T", "values": [0.0, 0.0]})
    assert sent[-1] == (
        "userAction",
        {"run": "run-1", "tool": "set_var", "args": {"name": "T", "values": [0.0, 0.0]}},
    )

    client.structured(
        system="s", prompt="p", tool_name="emit_claim",
        tool_description="d", schema={"type": "object"},
    )
    op, payload = sent[-1]
    assert op == "structured"
    assert payload["toolName"] == "emit_claim" and payload["schema"] == {"type": "object"}
    # Omitted rather than sent as null: pi picks when nothing is named, and a
    # null provider would be a request for a model called None.
    assert "provider" not in payload and "model" not in payload

    client.structured(
        system="s", prompt="p", tool_name="t", tool_description="d",
        schema={}, provider="somewhere", model="some-model",
    )
    assert sent[-1][1]["provider"] == "somewhere"
    assert sent[-1][1]["model"] == "some-model"


def test_formalize_cli_passes_provider_and_model_through(monkeypatch):
    """Both are needed together, so dropping either one silently re-pins the
    formalizer to whatever pi happens to authenticate first."""
    from simagent.cli import _cmd_formalize

    seen = {}

    class FakeClaim:
        id = "fake-claim"

        def save(self, path):
            seen["saved"] = str(path)

    def fake_formalize(text, model=None, provider=None, **kwargs):
        seen.update({"text": text, "model": model, "provider": provider})
        return FakeClaim()

    monkeypatch.setattr("simagent.llm.formalize", fake_formalize)
    args = SimpleNamespace(
        text="every triangle has three sides",
        out=None,
        provider="somewhere",
        model="some-model",
    )
    assert _cmd_formalize(args) == 0
    assert seen["provider"] == "somewhere" and seen["model"] == "some-model"
    assert seen["saved"] == "fake-claim.spec.json"


def _agent_args(tmp_path, **over):
    base = dict(
        problem=None, spec=None, conjecture=None,
        out=str(tmp_path / "run"), provider=None, model=None,
        thinking="medium", max_turns=12, images=False, approve_claim=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _fake_formalizer(monkeypatch, claim, formalizer="faux/model"):
    from simagent.llm import Formalization

    def fake(text, **kwargs):
        return Formalization(claim=claim, source_text=text,
                             formalizer=formalizer, attempts=1)

    monkeypatch.setattr("simagent.llm.formalize_recorded", fake)


def test_a_changed_bound_cannot_start_an_agent_silently(tmp_path, monkeypatch):
    """The failure this gate exists for: the formalizer answers a NEARBY
    question, the kernel settles that one perfectly, and every artifact reports
    success. Nothing downstream can catch it, so it is caught here."""
    import json

    import pytest

    from simagent.core.claim import Claim
    from simagent.intake import Intake
    from simagent.library import get

    drifted = json.loads(json.dumps(get("positive-quadratic").to_json()))
    drifted["spaces"][0]["high"] = float(drifted["spaces"][0]["high"]) + 5.0
    _fake_formalizer(monkeypatch, Claim.from_json(drifted))

    launched = []
    monkeypatch.setattr("simagent.cli.subprocess.run",
                        lambda command, **kw: launched.append(command))

    args = _agent_args(tmp_path, conjecture="is this quadratic positive?")
    with pytest.raises(SystemExit) as stop:
        _cmd_agent(args)

    assert "has not been approved" in str(stop.value)
    assert "--approve-claim" in str(stop.value)
    assert launched == [], "no agent process may start on an unapproved claim"

    # the record is on disk even though the run was refused, so the reader can
    # see exactly what would have run
    record = Intake.load(tmp_path / "run")
    assert record.source_text == "is this quadratic positive?"
    assert record.formalizer == "faux/model"
    assert record.needs_approval


def test_approval_of_a_stale_hash_is_refused(tmp_path, monkeypatch):
    """Approving by hash is what makes approval specific. A hash from an
    earlier formalization must not unlock a re-formalized claim."""
    import pytest

    from simagent.library import get

    _fake_formalizer(monkeypatch, get("positive-quadratic"))
    monkeypatch.setattr("simagent.cli.subprocess.run",
                        lambda command, **kw: (_ for _ in ()).throw(
                            AssertionError("must not launch")))

    args = _agent_args(tmp_path, conjecture="words", approve_claim="0" * 64)
    with pytest.raises(SystemExit) as stop:
        _cmd_agent(args)
    assert "re-read the claim" in str(stop.value)


def test_the_right_hash_lets_the_run_start(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS

    from simagent.intake import Intake, claim_hash
    from simagent.library import get

    pi_cli = tmp_path / "cli.js"
    pi_cli.write_text("// test placeholder")
    monkeypatch.setenv("SIMAGENT_PI_CLI", str(pi_cli))
    monkeypatch.setenv("SIMAGENT_PI_NODE", "/test/node")
    claim = get("positive-quadratic")
    _fake_formalizer(monkeypatch, claim)
    monkeypatch.setattr("simagent.cli.subprocess.run",
                        lambda command, **kw: NS(returncode=0))

    args = _agent_args(tmp_path, conjecture="words", approve_claim=claim_hash(claim))
    assert _cmd_agent(args) == 0
    assert Intake.load(tmp_path / "run").approved


def test_approving_on_the_cli_does_not_re_formalize(tmp_path, monkeypatch):
    """The CLI gate must be passable too.

    The formalizer is a model call and drifts between calls, so if approving
    re-formalized, the new claim would carry a new hash, the approval would
    never match, and the flow would be an infinite loop of printed claims.
    """
    from types import SimpleNamespace as NS

    from simagent.intake import Intake, claim_hash
    from simagent.library import get

    pi_cli = tmp_path / "cli.js"
    pi_cli.write_text("// test placeholder")
    monkeypatch.setenv("SIMAGENT_PI_CLI", str(pi_cli))
    monkeypatch.setenv("SIMAGENT_PI_NODE", "/test/node")
    monkeypatch.chdir(tmp_path)  # pending claims live under ./runs

    calls = []
    variants = [get("positive-quadratic"), get("sum-of-squares-vs-linear")]

    def drifting(text, **kw):
        from simagent.llm import Formalization

        claim = variants[min(len(calls), len(variants) - 1)]
        calls.append(text)
        return Formalization(claim=claim, source_text=text,
                             formalizer="faux/model", attempts=1)

    monkeypatch.setattr("simagent.llm.formalize_recorded", drifting)
    monkeypatch.setattr("simagent.cli.subprocess.run",
                        lambda command, **kw: NS(returncode=0))

    import pytest

    first = _agent_args(tmp_path, conjecture="words")
    with pytest.raises(SystemExit) as stop:
        _cmd_agent(first)
    shown = claim_hash(variants[0])
    assert shown in str(stop.value)
    assert len(calls) == 1

    second = _agent_args(tmp_path, conjecture="words", approve_claim=shown)
    assert _cmd_agent(second) == 0
    assert len(calls) == 1, "approval re-ran the formalizer and got a different claim"
    assert Intake.load(tmp_path / "run").approved
