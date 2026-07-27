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
    )
    assert _cmd_agent(args) == 7
    command = captured["command"]
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
