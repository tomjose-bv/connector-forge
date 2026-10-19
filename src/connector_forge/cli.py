"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

from connector_forge import __version__

VARIANTS = ("reference",)


def _connector_path(root: Path, variant: str, set_name: str, scenario: str) -> Path:
    base = root / "connectors" / variant
    return (base / "heldout" if set_name == "heldout" else base) / f"{scenario}.py"


def cmd_eval(args: argparse.Namespace) -> int:
    from connector_forge.harness import evaluate
    from connector_forge.scenario import load

    root = Path(args.root)
    files = sorted((root / "scenarios" / args.set).glob("*.yaml"))
    if args.scenario:
        files = [f for f in files if f.stem in args.scenario]
    if not files:
        print("no scenarios found")
        return 1
    reports = []
    print(f"{'scenario':<45} {'full':>5} {'incr':>5} {'schema':>6} {'429':>4} {'viol':>4} {'secs':>6}")
    for f in files:
        r = evaluate(load(f), _connector_path(root, args.variant, args.set, f.stem))
        reports.append(r.to_dict())
        print(
            f"{r.scenario:<45} {r.full_sync_accuracy:>5.2f} {r.incremental_accuracy:>5.2f} "
            f"{r.schema_accuracy:>6.2f} {r.rate_limited:>4} {r.rate_violations:>4} {r.seconds:>6.2f}"
        )
        for e in r.errors:
            print(f"    error: {e}")
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "machine": f"{platform.system()} {platform.release()} {platform.machine()}",
            "python": platform.python_version(),
            "version": __version__,
            "set": args.set,
            "variant": args.variant,
        }
        out.write_text(json.dumps({"meta": meta, "reports": reports}, indent=2), encoding="utf-8")
        print(f"wrote {out}")
    return 0 if all(not r["errors"] for r in reports) else 1


def _meta(**extra) -> dict:
    return {
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "machine": f"{platform.system()} {platform.release()} {platform.machine()}",
        "processor": platform.processor(),
        "python": platform.python_version(),
        "version": __version__,
        **extra,
    }


def cmd_agent(args: argparse.Namespace, llm=None) -> int:
    from connector_forge.agents import AGENTS
    from connector_forge.llm import OllamaClient
    from connector_forge.scenario import load

    root = Path(args.root)
    files = sorted((root / "scenarios" / args.set).glob("*.yaml"))
    if args.scenario:
        files = [f for f in files if f.stem in args.scenario]
    if not files:
        print("no scenarios found")
        return 1
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out or root / "runs" / f"{stamp}-{args.variant}-{args.set}-s{args.seed}")
    results = []
    print(f"{'scenario':<45} {'full':>5} {'incr':>5} {'schema':>6} {'calls':>5} {'tokens':>7} {'secs':>6}")
    for f in files:
        client = llm or OllamaClient(model=args.model, seed=args.seed, temperature=args.temperature)
        res = AGENTS[args.variant](load(f), client, out / f.stem)
        results.append(res.to_dict())
        rep = res.report or {}
        print(
            f"{res.scenario:<45} {rep.get('full_sync_accuracy', 0):>5.2f} {rep.get('incremental_accuracy', 0):>5.2f} "
            f"{rep.get('schema_accuracy', 0):>6.2f} {res.llm_calls:>5} {res.prompt_tokens + res.output_tokens:>7} "
            f"{res.seconds:>6.1f}"
        )
        for e in ([res.error] if res.error else []) + rep.get("errors", [])[:2]:
            print(f"    error: {e[:160]}")
        (out / f.stem / "result.json").write_text(json.dumps(res.to_dict(), indent=2), encoding="utf-8")
    meta = _meta(set=args.set, variant=args.variant, model=args.model, seed=args.seed, temperature=args.temperature)
    (out / "summary.json").write_text(json.dumps({"meta": meta, "results": results}, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="connector-forge")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    ev = sub.add_parser("eval", help="evaluate connectors against scenarios")
    ev.add_argument("--set", choices=("dev", "heldout"), default="dev")
    ev.add_argument("--variant", choices=VARIANTS, default="reference")
    ev.add_argument("--scenario", action="append", help="limit to this scenario (repeatable)")
    ev.add_argument("--out", help="write a JSON report here")
    ev.add_argument("--root", default=".", help="project root with scenarios/ and connectors/")
    ag = sub.add_parser("agent", help="run an AI agent on scenarios (needs Ollama)")
    ag.add_argument("--variant", choices=("prompt", "probe"), required=True)
    ag.add_argument("--set", choices=("dev", "heldout"), default="dev")
    ag.add_argument("--scenario", action="append", help="limit to this scenario (repeatable)")
    ag.add_argument("--model", default="qwen2.5-coder:3b")
    ag.add_argument("--seed", type=int, default=1)
    ag.add_argument("--temperature", type=float, default=0.2)
    ag.add_argument("--out", help="run directory (default runs/<time>-<variant>-<set>-s<seed>)")
    ag.add_argument("--root", default=".", help="project root with scenarios/")
    args = parser.parse_args(argv)
    if args.command == "eval":
        return cmd_eval(args)
    if args.command == "agent":
        return cmd_agent(args)
    parser.print_help()
    return 0
