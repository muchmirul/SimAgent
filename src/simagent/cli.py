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


def _resolve_spec(args) -> ProblemSpec:
    if args.spec:
        return ProblemSpec.load(args.spec)
    if args.problem:
        return get(args.problem)
    if args.conjecture:
        from .llm import formalize

        return formalize(args.conjecture, model=args.model)
    raise SystemExit("give a bundled problem id, --spec spec.json, or --conjecture 'text' (see `simagent list`)")


def _cmd_solve(args) -> int:
    spec = _resolve_spec(args)
    out = args.out or str(Path("runs") / f"{spec.id}-seed{args.seed}")
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
    if args.problem:
        spec = get(args.problem)
        source_args = ["--problem-id", args.problem]
    elif args.spec:
        spec = ProblemSpec.load(args.spec)
        source_args = ["--spec", str(Path(args.spec).resolve())]
    elif args.conjecture:
        from .llm import formalize

        spec = formalize(args.conjecture)
        source_args = []
    else:
        raise SystemExit(
            "give a bundled problem id, --spec spec.json, or --conjecture 'text' (see `simagent list`)"
        )
    out = Path(args.out or Path("runs") / f"agent-{spec.id}").resolve()
    if args.conjecture:
        out.mkdir(parents=True, exist_ok=True)
        spec_path = out / "input.spec.json"
        spec.save(spec_path)
        source_args = ["--spec", str(spec_path)]
    repo_root = Path(__file__).resolve().parents[2]
    pi_cli = Path(os.environ.get("SIMAGENT_PI_CLI", repo_root / "agent" / "dist" / "cli.js"))
    if not pi_cli.is_file():
        raise SystemExit(
            f"pi runtime is not built: {pi_cli} (run `cd agent && npm ci && npm run build`)"
        )
    node = os.environ.get("SIMAGENT_PI_NODE") or shutil.which("node")
    if not node:
        raise SystemExit("Node.js >=22.19 is required for pi agent mode")
    command = [
        node,
        str(pi_cli),
        "run",
        *source_args,
        "--out-dir",
        str(out),
        "--thinking",
        args.thinking,
        "--max-turns",
        str(args.max_turns),
    ]
    if args.provider or args.model:
        if not (args.provider and args.model):
            raise SystemExit("--provider and --model must be given together")
        command.extend(["--provider", args.provider, "--model", args.model])
    else:
        print(
            "no --provider/--model given: pi routes the first authenticated "
            "vision model it has. SimAgent harnesses whichever one that is; "
            "the run records it in runtime.json and agent_summary.md."
        )
    code = subprocess.run(command, cwd=repo_root, check=False).returncode
    who = out / "runtime.json"
    if who.is_file():
        info = json.loads(who.read_text())
        print(f"Model: {info.get('provider')}/{info.get('model')}")
    return code


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
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _cmd_formalize(args) -> int:
    from .llm import formalize

    spec = formalize(args.text, model=args.model)
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

    s = sub.add_parser("solve", help="run the full pipeline on a conjecture")
    s.add_argument("problem", nargs="?", help="bundled problem id (see `simagent list`)")
    s.add_argument("--spec", help="path to a spec.json (e.g. from `simagent formalize`)")
    s.add_argument("--conjecture", help="natural-language conjecture (uses the Claude API)")
    s.add_argument("--trials", type=int, default=2000)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--out", help="output directory (default runs/<id>-seed<seed>)")
    s.add_argument("--render-manim", action="store_true", help="render the Manim scene (needs manim)")
    s.add_argument("--llm-proof", action="store_true", help="ask the LLM for a proof sketch (uses the API)")
    s.add_argument("--model", help="Claude model id (default claude-opus-4-8; env SIMAGENT_MODEL)")
    s.set_defaults(fn=_cmd_solve)

    pl = sub.add_parser("play", help="interactive sandbox REPL with a live-updating 3D preview")
    pl.add_argument("problem", nargs="?", help="bundled problem id (see `simagent list`)")
    pl.add_argument("--spec", help="path to a spec.json")
    pl.add_argument("--out", help="play directory (default runs/play-<id>)")
    pl.set_defaults(fn=_cmd_play)

    a = sub.add_parser("agent", help="let a pi-managed LLM live in the sandbox: see, act, prove")
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

    f = sub.add_parser("formalize", help="conjecture text -> validated spec.json (uses the Claude API)")
    f.add_argument("text")
    f.add_argument("--out", help="output path (default <id>.spec.json)")
    f.add_argument("--model")
    f.set_defaults(fn=_cmd_formalize)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
