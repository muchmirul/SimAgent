"""P6 CLI cutover: `simagent agent` launches the TypeScript pi runtime."""
import json
from pathlib import Path
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


def _fake_pi(monkeypatch, tmp_path, outcomes):
    """Stand in for the node runtime: record the command, write the metrics
    the real kernel would have written, and report the exit code."""
    import json as json_mod

    calls: list[list[str]] = []
    cli = tmp_path / "cli.js"
    cli.write_text("")
    monkeypatch.setenv("SIMAGENT_PI_CLI", str(cli))
    monkeypatch.setenv("SIMAGENT_PI_NODE", "/nonexistent/node")

    class Finished:
        def __init__(self, code):
            self.returncode = code

    def fake_run(command, **kwargs):
        calls.append(list(command))
        out = Path(command[command.index("--out-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        verified_by, ended_by, code = outcomes[len(calls) - 1]
        (out / "metrics.json").write_text(json_mod.dumps(
            {"format": "metrics/1", "verified_by": verified_by,
             "ended_by": ended_by, "turns": 12}))
        return Finished(code)

    monkeypatch.setattr("simagent.cli.subprocess.run", fake_run)
    return calls


def test_a_single_round_still_runs_in_the_directory_it_was_given(tmp_path, monkeypatch):
    """The default is one round, and it must look exactly like it always did."""
    calls = _fake_pi(monkeypatch, tmp_path, [("none", "stop", 0)])
    args = _agent_args(tmp_path, problem="circumcenter-in-triangle")

    assert _cmd_agent(args) == 0
    assert len(calls) == 1
    assert calls[0][calls[0].index("--out-dir") + 1] == str(Path(args.out).resolve())
    assert "--adopt" not in calls[0]
    assert not (Path(args.out) / "loop.json").exists()


def test_each_round_adopts_the_one_before_it(tmp_path, monkeypatch):
    """A turn budget becomes a pause: round 2 continues round 1's world."""
    calls = _fake_pi(monkeypatch, tmp_path,
                     [("none", "stop", 0), ("none", "stop", 0), ("none", "stop", 0)])
    args = _agent_args(tmp_path, problem="circumcenter-in-triangle", rounds=3)

    assert _cmd_agent(args) == 0
    assert len(calls) == 3
    assert "--adopt" not in calls[0]
    for index in (1, 2):
        adopted = calls[index][calls[index].index("--adopt") + 1]
        assert adopted.endswith(f"round-{index}")
        assert calls[index][calls[index].index("--out-dir") + 1].endswith(
            f"round-{index + 1}")

    record = json.loads((Path(args.out) / "loop.json").read_text())
    assert record["stopped"] == "the declared budget of 3 round(s) ran out"
    assert [r["round"] for r in record["rounds"]] == [1, 2, 3]


def test_the_loop_stops_the_moment_the_kernel_stamps_one(tmp_path, monkeypatch):
    """The stopping rule is mechanical: a stamp exists, or the budget is spent.
    Nothing here reads the model's opinion of whether it is done."""
    calls = _fake_pi(monkeypatch, tmp_path,
                     [("none", "stop", 0), ("sandbox", "finish", 0), ("none", "stop", 0)])
    args = _agent_args(tmp_path, problem="circumcenter-in-triangle", rounds=3)

    assert _cmd_agent(args) == 0
    assert len(calls) == 2, "round 3 must never start once round 2 is stamped"
    record = json.loads((Path(args.out) / "loop.json").read_text())
    assert record["stopped"] == "the kernel stamped sandbox"


def test_a_broken_runtime_is_not_retried_by_the_loop(tmp_path, monkeypatch):
    calls = _fake_pi(monkeypatch, tmp_path, [("none", "", 2), ("none", "stop", 0)])
    args = _agent_args(tmp_path, problem="circumcenter-in-triangle", rounds=2)

    assert _cmd_agent(args) == 2
    assert len(calls) == 1
    record = json.loads((Path(args.out) / "loop.json").read_text())
    assert record["stopped"] == "the runtime exited 2"


def test_a_round_that_wrote_no_metrics_is_not_treated_as_settled(tmp_path, monkeypatch):
    """A crash before finalize leaves no metrics.json. A missing file must read
    as 'nothing was established', never as a stamp — and the loop must not keep
    paying a model to replay a history that produced nothing."""
    cli = tmp_path / "cli.js"
    cli.write_text("")
    monkeypatch.setenv("SIMAGENT_PI_CLI", str(cli))
    monkeypatch.setenv("SIMAGENT_PI_NODE", "/nonexistent/node")

    class Finished:
        returncode = 0

    calls: list[list[str]] = []
    monkeypatch.setattr("simagent.cli.subprocess.run",
                        lambda command, **kw: (calls.append(list(command)), Finished())[1])
    args = _agent_args(tmp_path, problem="circumcenter-in-triangle", rounds=4)

    assert _cmd_agent(args) == 0
    assert len(calls) == 1, "a round with no acts must not buy three more"
    record = json.loads((Path(args.out) / "loop.json").read_text())
    assert all(r["verified_by"] == "none" for r in record["rounds"])
    assert record["stopped"] == "round 1 recorded no acts of its own"


def test_an_unreadable_metrics_file_does_not_kill_the_loop(tmp_path, monkeypatch):
    """Losing loop.json to a JSON error would throw away the record of every
    round that already ran, including the money they cost."""
    cli = tmp_path / "cli.js"
    cli.write_text("")
    monkeypatch.setenv("SIMAGENT_PI_CLI", str(cli))
    monkeypatch.setenv("SIMAGENT_PI_NODE", "/nonexistent/node")

    class Finished:
        returncode = 0

    def fake_run(command, **kwargs):
        out = Path(command[command.index("--out-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "metrics.json").write_text("{not json at all")
        return Finished()

    monkeypatch.setattr("simagent.cli.subprocess.run", fake_run)
    args = _agent_args(tmp_path, problem="circumcenter-in-triangle", rounds=2)

    assert _cmd_agent(args) == 0
    record = json.loads((Path(args.out) / "loop.json").read_text())
    assert record["rounds"][0]["verified_by"] == "none"
    assert record["rounds"][0]["ended_by"] == "unreadable metrics.json"


def test_a_failed_round_is_never_credited_with_a_stale_stamp(tmp_path, monkeypatch):
    """A child that dies at startup leaves whatever an earlier invocation of
    the same --out wrote. Reading it would report a stamp this round did not
    earn, and would end the loop on a lie."""
    cli = tmp_path / "cli.js"
    cli.write_text("")
    monkeypatch.setenv("SIMAGENT_PI_CLI", str(cli))
    monkeypatch.setenv("SIMAGENT_PI_NODE", "/nonexistent/node")

    stale = Path(_agent_args(tmp_path).out) / "round-1"
    stale.mkdir(parents=True)
    (stale / "metrics.json").write_text(json.dumps(
        {"verified_by": "sandbox+lean", "ended_by": "finish", "turns": 30}))

    class Died:
        returncode = 3

    monkeypatch.setattr("simagent.cli.subprocess.run", lambda command, **kw: Died())
    args = _agent_args(tmp_path, problem="circumcenter-in-triangle", rounds=2)

    assert _cmd_agent(args) == 3
    record = json.loads((Path(args.out) / "loop.json").read_text())
    assert record["rounds"][0]["verified_by"] == "none"
    assert record["stopped"] == "the runtime exited 3"


def test_rounds_below_one_is_refused_rather_than_rounded_up(tmp_path, monkeypatch):
    """Rounding 0 up to 1 spends a model run the caller asked not to have."""
    import pytest

    calls = _fake_pi(monkeypatch, tmp_path, [("none", "stop", 0)])
    args = _agent_args(tmp_path, problem="circumcenter-in-triangle", rounds=0)

    with pytest.raises(SystemExit, match="--rounds must be at least 1"):
        _cmd_agent(args)
    assert calls == []


def test_adopt_reaches_the_runtime_on_a_single_round(tmp_path, monkeypatch):
    """The plain `--adopt` case has no loop around it, so nothing else would
    catch the flag being dropped between argparse and the node command."""
    calls = _fake_pi(monkeypatch, tmp_path, [("none", "stop", 0)])
    prior = tmp_path / "earlier-run"
    prior.mkdir()
    args = _agent_args(tmp_path, problem="circumcenter-in-triangle",
                       adopt=str(prior))

    assert _cmd_agent(args) == 0
    assert calls[0][calls[0].index("--adopt") + 1] == str(prior)
    assert calls[0][calls[0].index("--out-dir") + 1] == str(Path(args.out).resolve())


def test_the_agent_parser_really_has_adopt_and_rounds():
    """_cmd_agent reads args.adopt and args.rounds. If the parser never
    produced them, every test above would still pass on its SimpleNamespace
    while the real command line silently ignored both flags."""
    from simagent.cli import main

    import pytest

    parsed = {}

    def capture(args):
        parsed.update(vars(args))
        return 0

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("simagent.cli._cmd_agent", capture)
        main(["agent", "circumcenter-in-triangle", "--adopt", "runs/prior",
              "--rounds", "4"])

    assert parsed["adopt"] == "runs/prior"
    assert parsed["rounds"] == 4


def _capture_web(patch):
    """Route _cmd_web into a dict instead of starting a server."""
    parsed = {}

    def capture(args):
        parsed.update(vars(args))
        return 0

    patch.setattr("simagent.cli._cmd_web", capture)
    return parsed


def test_bare_simagent_opens_the_notebook():
    """`simagent` with no subcommand is the one-shot entry.

    A usage dump helps nobody who typed the program's own name, and this is the
    command the tool is used through.
    """
    from simagent.cli import main

    import pytest

    with pytest.MonkeyPatch.context() as patch:
        parsed = _capture_web(patch)
        assert main([]) == 0

    assert parsed["cmd"] == "web"
    assert parsed["port"] == 8642 and parsed["host"] == "localhost"


def test_bare_simagent_forwards_the_flags_typed_after_it():
    """`simagent --port 9000` must mean what `simagent web --port 9000` means,
    or the short form is a trap that silently ignores what you asked for."""
    from simagent.cli import main

    import pytest

    with pytest.MonkeyPatch.context() as patch:
        parsed = _capture_web(patch)
        assert main(["--port", "9000", "--no-browser"]) == 0

    assert parsed["port"] == 9000 and parsed["no_browser"] is True


def test_a_named_subcommand_still_rejects_an_unknown_flag():
    """Forwarding is only for the bare command. Relaxing it everywhere would
    turn every typo into a silently ignored argument."""
    from simagent.cli import main

    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["solve", "circumcenter-in-triangle", "--bogus"])
    assert exc.value.code == 2


def test_a_misspelled_subcommand_fails_instead_of_opening_the_notebook():
    """`simagent bnch` must not quietly become `simagent web bnch`.

    That is why only a leading FLAG routes to the notebook: a bare word is
    still read as a subcommand, so a typo says so instead of opening a page
    with a problem id nobody has.
    """
    from simagent.cli import main

    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["bnch"])
    assert exc.value.code == 2


def test_the_top_level_help_still_lists_every_command(capsys):
    """`-h` must survive the bare-command rule, or the other seven commands
    become undiscoverable from the tool itself."""
    from simagent.cli import main

    import pytest

    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for command in ("list", "bench", "solve", "play", "agent", "web", "formalize"):
        assert command in out


def test_the_pi_preflight_never_stops_the_notebook_from_starting(capsys):
    """The sandbox is the whole UI minus the model and needs no pi at all.

    If a missing pi runtime could fail the command, an unbuilt `agent/dist`
    would cost the user the sample/nudge/certify/view surface too, which works
    with no model anywhere.
    """
    from simagent.cli import _preflight_pi
    from simagent.pi_agent import PiAgentError

    class Broken:
        def models(self):
            raise PiAgentError("NOT_BUILT", "pi runtime is not built: run npm run build")

    _preflight_pi(Broken())  # must not raise
    out = capsys.readouterr().out
    assert "NOT_BUILT" in out and "npm run build" in out
    assert "sandbox works without it" in out


def test_the_preflight_names_the_default_model_rather_than_leaving_it_blank():
    """With no --provider/--model pi hands over its first authenticated model,
    so an unnamed model is still a choice that was made. Saying which one keeps
    it provenance rather than a blank."""
    from simagent.cli import _preflight_pi

    class Routed:
        def models(self):
            return [{"provider": "p", "id": "first", "vision": False},
                    {"provider": "p", "id": "second", "vision": True}]

    import io
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _preflight_pi(Routed())
    out = buffer.getvalue()
    assert "2 model(s), 1 with vision" in out
    assert "p/first" in out
