"""simagent CLI.

  simagent list
  simagent solve circumcenter-in-tetrahedron --trials 2000 --render-manim
  simagent solve --conjecture "every triangle's incenter lies inside it"
  simagent formalize "..." --out my_spec.json
  simagent solve --spec my_spec.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import answer as answer_mod
from . import rounds as rounds_mod
from .library import all_specs, get
from .pipeline import run_problem
from .spec import ProblemSpec


def _cmd_list(_args) -> int:
    for spec in all_specs():
        print(f"{spec.id:32s}  [{spec.quantifier}]  {spec.title}")
    return 0


def _cmd_bench(args) -> int:
    """One number for the whole harness. Exit non-zero when it slips, so a
    regression is a failure and not a paragraph someone has to read."""
    from . import benchmark

    rows = benchmark.run_all(trials=args.trials, seed=args.seed)
    print(benchmark.format_report(rows))
    return 0 if all(r.ok for r in rows) else 1


def _cmd_eval(args) -> int:
    """Does the loop help? bench cannot say; this can.

    Model arms cost real API calls, so nothing runs until the arms are named.
    """
    from . import evaluate

    manifest = evaluate.load_manifest(args.manifest)
    arms = tuple(args.arms or ["search"])
    unknown = [a for a in arms if a not in evaluate.ARMS]
    if unknown:
        raise SystemExit(f"unknown arm(s) {unknown}; choose from {list(evaluate.ARMS)}")
    if args.dry_run:
        print(json.dumps(manifest, indent=2))
        return 0
    if args.provider or args.model:
        if not (args.provider and args.model):
            raise SystemExit("--provider and --model must be given together")
    out = args.out or str(Path("runs") / f"eval-{manifest.get('name', 'run')}")
    report = evaluate.run(manifest, out, arms=arms, provider=args.provider,
                          model=args.model)
    print()
    print(evaluate.format_report(report))
    print(f"\nRecord: {Path(out) / 'eval.json'}")
    return 0


def _resolve_spec(args) -> ProblemSpec:
    return _resolve_with_intake(args)[0]


def _resolve_with_intake(args):
    """The spec plus the record of where it came from.

    Every entry point goes through here so no run can start without saying what
    the user asked and who translated it.
    """
    from . import intake as intake_mod
    from .llm import FormalizeError as FormalizeErr, FormalizeRefused

    if args.spec:
        spec = ProblemSpec.load(args.spec)
        return spec, intake_mod.record(spec, str(args.spec), "spec-file")
    if args.problem:
        spec = get(args.problem)
        return spec, intake_mod.record(spec, args.problem, "bundled")
    if args.conjecture:
        from .core.claim import Claim
        from .llm import formalize_recorded

        # Approving names ONE claim by hash. Re-formalizing here would produce
        # a differently worded claim with a different hash, so the approval
        # could never match and the gate would be unpassable. Load back the
        # exact claim that was shown instead.
        approved = getattr(args, "approve_claim", None)
        pending = intake_mod.load_pending(approved) if approved else None
        if pending is not None:
            return Claim.from_json(pending.claim_json), pending

        try:
            made = formalize_recorded(
                args.conjecture, model=args.model,
                provider=getattr(args, "provider", None),
            )
        except FormalizeErr as broke:
            # Not a refusal: the model could not produce the structured answer.
            # A traceback here would read as a harness crash, which it is not.
            raise SystemExit(
                f"The formalizer could not answer.\n  {broke}\n"
                "  Name a model with --provider/--model: with none given, pi uses "
                "whichever model it lists first, and not every model supports the "
                "structured tool call the formalizer needs."
            ) from broke
        except FormalizeRefused as refused:
            # A refusal is an answer, not a crash: the vocabulary cannot state
            # this conjecture, and inventing a nearby one would settle a
            # different question under the user's words.
            raise SystemExit(
                "The formalizer refused this conjecture rather than substitute a "
                f"nearby one.\n  Reason: {refused.reason}\n"
                f"  Refused by: {refused.formalizer or 'unrecorded model'}"
            ) from refused
        return made.claim, intake_mod.record(
            made.claim, made.source_text, "conjecture", formalizer=made.formalizer,
        )
    raise SystemExit("give a bundled problem id, --spec spec.json, or --conjecture 'text' (see `simagent list`)")


def _cmd_solve(args) -> int:
    spec, intake = _resolve_with_intake(args)
    out = args.out or str(Path("runs") / f"{spec.id}-seed{args.seed}")
    Path(out).mkdir(parents=True, exist_ok=True)
    intake.save(out)
    if intake.source_kind == "conjecture":
        # A translated question is shown before the run, because this is the
        # last moment the reader can tell the harness it is answering the
        # wrong thing.
        from . import intake as intake_mod

        print(intake_mod.render_text(intake))
        print()
    result = run_problem(
        spec,
        out,
        trials=args.trials,
        seed=args.seed,
        render_manim=args.render_manim,
        llm_proof=args.llm_proof,
        llm_model=args.model,
    )
    print(f"\n== {spec.title} ==")
    for line in result.log:
        print(f"  {line}")
    print(f"\nVerdict: {answer_mod.verdict_text(result.report, result.proof)}")
    print(f"Asked: {intake.source_text.strip()}")
    print(f"Claim reviewed: {intake.review_state} (claim {intake.claim_hash[:12]}…)")
    print(f"Run dir: {result.out_dir}")
    for name, path in sorted(result.artifacts.items()):
        print(f"  {name:12s} {path}")
    return 0


def _cmd_play(args) -> int:
    from .play import launch

    if args.spec:
        spec = ProblemSpec.load(args.spec)
    elif args.problem:
        spec = get(args.problem)
    else:
        raise SystemExit("give a bundled problem id or --spec spec.json (see `simagent list`)")
    launch(spec, args.out or str(Path("runs") / f"play-{spec.id}"))
    return 0


def _cmd_agent(args) -> int:
    from . import intake as intake_mod

    spec, intake = _resolve_with_intake(args)
    if args.problem:
        source_args = ["--problem-id", args.problem]
    elif args.spec:
        source_args = ["--spec", str(Path(args.spec).resolve())]
    else:
        source_args = []
    out = Path(args.out or Path("runs") / f"agent-{spec.id}").resolve()
    if args.conjecture:
        out.mkdir(parents=True, exist_ok=True)
        spec_path = out / "input.spec.json"
        spec.save(spec_path)
        source_args = ["--spec", str(spec_path)]
    out.mkdir(parents=True, exist_ok=True)
    if getattr(args, "approve_claim", None):
        try:
            intake.approve(args.approve_claim)
        except ValueError as exc:
            intake.save(out)
            raise SystemExit(f"{exc}\n\n{intake_mod.render_text(intake)}") from exc
    intake.save(out)
    if intake.needs_approval:
        # The gate: a model translated the user's words, and nobody has said
        # the translation is right. Running now would settle whatever the
        # translation says while reporting it as the user's question.
        # The claim is kept so approving it re-uses THIS one rather than paying
        # for a fresh formalization that would carry a different hash.
        intake_mod.save_pending(intake)
        print(intake_mod.render_text(intake))
        raise SystemExit(
            "\nThis claim has not been approved, so no agent will run.\n"
            "Read the claim above. If it is your question, re-run the same "
            "command with:\n"
            f"  --approve-claim {intake.claim_hash}"
        )
    if intake.source_kind == "conjecture":
        print(f"Approved claim {intake.claim_hash[:12]}… translated by {intake.formalizer}")
    repo_root = Path(__file__).resolve().parents[2]
    pi_cli = Path(os.environ.get("SIMAGENT_PI_CLI", repo_root / "agent" / "dist" / "cli.js"))
    if not pi_cli.is_file():
        raise SystemExit(
            f"pi runtime is not built: {pi_cli} (run `cd agent && npm ci && npm run build`)"
        )
    node = os.environ.get("SIMAGENT_PI_NODE") or shutil.which("node")
    if not node:
        raise SystemExit("Node.js >=22.19 is required for pi agent mode")
    base_command = [
        node,
        str(pi_cli),
        "run",
        *source_args,
        "--thinking",
        args.thinking,
        "--max-turns",
        str(args.max_turns),
        "--images",
        "true" if args.images else "false",
    ]
    # flush=True: the child's stderr is unbuffered, so without this a failure
    # from the runtime prints BEFORE this line and reads as if the run started.
    print(
        "Senses: pictures are sent to the model as well as numbers."
        if args.images
        else "Senses: numbers and text only (--images adds pictures). "
             "Renders are still written for the notebook.",
        flush=True,
    )
    if args.provider or args.model:
        if not (args.provider and args.model):
            raise SystemExit("--provider and --model must be given together")
        base_command.extend(["--provider", args.provider, "--model", args.model])
    else:
        print(
            "no --provider/--model given: pi routes the first authenticated "
            + ("vision " if args.images else "")
            + "model it has. SimAgent harnesses whichever one that is; "
            "the run records it in runtime.json and agent_summary.md."
        )

    # One round is one run of the model against its turn budget. More than one
    # makes the budget a pause instead of an ending: each later round adopts the
    # previous one, so the world and the journal carry over. Both stopping
    # rules are mechanical — a kernel stamp, or the budget the caller declared.
    # `or 1` would be wrong here: it turns an explicit 0 into 1, which is the
    # bug this check exists to prevent.
    requested = getattr(args, "rounds", 1)
    rounds = 1 if requested is None else int(requested)
    if rounds < 1:
        # Silently rounding up to 1 would spend a model run the caller asked
        # not to have.
        raise SystemExit(f"--rounds must be at least 1, got {rounds}")
    adopt_next = getattr(args, "adopt", None)
    records: list[dict] = []
    stopped = ""
    for index in range(1, rounds + 1):
        round_out = rounds_mod.round_dir(out, index, rounds)
        if rounds > 1:
            # Each round is a run in its own right, so it carries the same
            # contract: answer.md there must still name the user's question and
            # whether the translation was approved.
            round_out.mkdir(parents=True, exist_ok=True)
            intake.save(round_out)
        command = [*base_command, "--out-dir", str(round_out)]
        if adopt_next:
            command.extend(["--adopt", str(adopt_next)])
            print(
                f"\n== round {index} of {rounds}: continuing {adopt_next} ==\n"
                "  (its acts replay into this world first, which takes as long "
                "as they did to run)",
                flush=True,
            )
        elif rounds > 1:
            print(f"\n== round {index} of {rounds} ==", flush=True)
        code = subprocess.run(command, cwd=repo_root, check=False).returncode
        record = rounds_mod.read_round(index, round_out, code)
        records.append(record)
        stopped = rounds_mod.stop_reason(record)
        if stopped:
            break
        adopt_next = str(round_out)
    else:
        stopped = rounds_mod.budget_spent(rounds)

    last = Path(records[-1]["dir"])
    who = last / "runtime.json"
    if who.is_file():
        info = json.loads(who.read_text())
        print(f"Model: {info.get('provider')}/{info.get('model')}")
    if rounds > 1:
        (out / "loop.json").write_text(
            json.dumps({"format": "loop/1", "rounds": records, "stopped": stopped},
                       indent=2)
        )
        for record in records:
            print(f"  round {record['round']}: {record['turns']} turns, "
                  f"ended {record['ended_by'] or 'unrecorded'}, "
                  f"verified_by {record['verified_by']}")
        print(f"Loop ended after {len(records)} round(s): {stopped}.")
        print(f"Record: {out / 'loop.json'}")
    handoff = last / "handoff.md"
    if handoff.is_file():
        print(f"Handoff: {handoff}")
    return records[-1]["exit_code"]


def _loopback_sockets(port: int) -> list:
    """Listen on BOTH loopback addresses, 127.0.0.1 and ::1.

    "localhost" is one name for two addresses, and nothing guarantees a browser
    and a Python process resolve it the same way. On this machine it resolves
    to ::1, so a server bound only to 127.0.0.1 answers curl and refuses the
    browser: the page never loads and every later change looks broken. Binding
    both ends that class of bug. It is still loopback only, so nothing is
    exposed to the network.
    """
    import socket

    sockets = []
    for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            s = socket.socket(family, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s.bind((address, port))
            s.listen(2048)
            s.set_inheritable(True)
            sockets.append(s)
        except OSError as exc:  # one family missing is fine; both is not
            print(f"note: cannot listen on {address}:{port} ({exc})")
    return sockets


def _cmd_web(args) -> int:
    import threading
    import webbrowser

    import uvicorn

    from .web import create_app

    app = create_app(out_root=args.out or "runs/web")
    url = f"http://{args.host}:{args.port}"
    if args.problem:
        url += f"/?problem={args.problem}"
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    print(f"SimAgent sandbox: {url}")
    config = uvicorn.Config(app, log_level="warning")
    if args.host == "localhost":
        sockets = _loopback_sockets(args.port)
        if not sockets:
            raise SystemExit(f"port {args.port} is busy on both loopback addresses")
        uvicorn.Server(config).run(sockets=sockets)
    else:  # an explicit --host: bind exactly what was asked for
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _cmd_formalize(args) -> int:
    from .llm import formalize

    spec = formalize(args.text, model=args.model, provider=args.provider)
    out = args.out or f"{spec.id}.spec.json"
    spec.save(out)
    print(f"spec written: {out}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="simagent",
        description="Sandbox-first harness for math conjectures: simulate, visualize, search, formalize.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list bundled problems").set_defaults(fn=_cmd_list)

    b = sub.add_parser("bench", help="run every known-answer problem; print one pass rate")
    b.add_argument("--trials", type=int, default=400)
    b.add_argument("--seed", type=int, default=0)
    b.set_defaults(fn=_cmd_bench)

    e = sub.add_parser(
        "eval",
        help="does the loop help? same tasks, same budget, several arms, mechanical scores",
    )
    e.add_argument("--manifest", help="path to an eval/1 manifest (default: the bundled one)")
    e.add_argument(
        "--arms", nargs="+", metavar="ARM",
        help="which arms to run: search (offline floor), text (numbers-first loop), "
             "images (the same loop with pictures). Default: search only, because "
             "the model arms spend real API calls",
    )
    e.add_argument("--provider", help="pi provider id (requires --model)")
    e.add_argument("--model", help="pi model id (requires --provider)")
    e.add_argument("--out", help="output directory (default runs/eval-<name>)")
    e.add_argument("--dry-run", action="store_true",
                   help="print the manifest that would run and stop")
    e.set_defaults(fn=_cmd_eval)

    s = sub.add_parser("solve", help="run the full pipeline on a conjecture")
    s.add_argument("problem", nargs="?", help="bundled problem id (see `simagent list`)")
    s.add_argument("--spec", help="path to a spec.json (e.g. from `simagent formalize`)")
    s.add_argument("--conjecture", help="natural-language conjecture (formalized by a pi-routed model)")
    s.add_argument("--trials", type=int, default=2000)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--out", help="output directory (default runs/<id>-seed<seed>)")
    s.add_argument("--render-manim", action="store_true", help="render the Manim scene (needs manim)")
    s.add_argument("--llm-proof", action="store_true", help="ask the LLM for a proof sketch (uses the API)")
    s.add_argument("--provider", help="pi provider id for formalization (requires --model)")
    s.add_argument("--model", help="pi model id (default: pi's first authenticated model)")
    s.set_defaults(fn=_cmd_solve)

    pl = sub.add_parser("play", help="interactive sandbox REPL with a live-updating 3D preview")
    pl.add_argument("problem", nargs="?", help="bundled problem id (see `simagent list`)")
    pl.add_argument("--spec", help="path to a spec.json")
    pl.add_argument("--out", help="play directory (default runs/play-<id>)")
    pl.set_defaults(fn=_cmd_play)

    a = sub.add_parser("agent", help="let a pi-managed LLM live in the sandbox: act, measure, prove")
    a.add_argument("problem", nargs="?", help="bundled problem id (see `simagent list`)")
    a.add_argument("--spec", help="path to a spec.json")
    a.add_argument("--conjecture", help="natural-language conjecture (formalized first)")
    a.add_argument("--provider", help="pi provider id (requires --model)")
    a.add_argument("--model", help="pi model id (requires --provider)")
    a.add_argument(
        "--thinking",
        choices=["off", "minimal", "low", "medium", "high", "xhigh", "max"],
        default="medium",
    )
    a.add_argument("--max-turns", type=int, default=40)
    a.add_argument(
        "--images",
        action="store_true",
        help="also send rendered pictures to the model (default: numbers and "
             "text only; renders are written for the notebook either way, and "
             "this flag makes vision a model requirement)",
    )
    a.add_argument(
        "--approve-claim",
        metavar="HASH",
        help="approve the formalized claim with this exact hash (required before an "
             "agent runs on --conjecture input; the hash is printed by a first run)",
    )
    a.add_argument(
        "--adopt",
        metavar="RUN_DIR",
        help="continue an earlier run: its journal is replayed into this world "
             "and hash-checked, then re-opened so the work carries on",
    )
    a.add_argument(
        "--rounds",
        type=int,
        default=1,
        help="run this many rounds, each adopting the one before it (default 1). "
             "Rounds land in <out>/round-N and stop early the moment the kernel "
             "stamps a result",
    )
    a.add_argument("--out", help="output directory (default runs/agent-<id>)")
    a.set_defaults(fn=_cmd_agent)

    w = sub.add_parser("web", help="browser sandbox: live 3D UI + Manim rendering")
    w.add_argument("problem", nargs="?", help="problem to open first (see `simagent list`)")
    # localhost, not 127.0.0.1: on a machine where localhost resolves to ::1
    # a 127.0.0.1 bind simply does not answer http://localhost, and the
    # browser fails or stalls on the IPv6 attempt first. Still loopback only,
    # because the notebook has no authentication.
    w.add_argument("--host", default="localhost")
    w.add_argument("--port", type=int, default=8642)
    w.add_argument("--out", help="run directory root (default runs/web)")
    w.add_argument("--no-browser", action="store_true")
    w.set_defaults(fn=_cmd_web)

    f = sub.add_parser(
        "formalize", help="conjecture text -> validated spec.json (via a pi-routed model)"
    )
    f.add_argument("text")
    f.add_argument("--out", help="output path (default <id>.spec.json)")
    f.add_argument("--provider", help="pi provider id (requires --model)")
    f.add_argument("--model", help="pi model id (default: pi's first authenticated model)")
    f.set_defaults(fn=_cmd_formalize)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
