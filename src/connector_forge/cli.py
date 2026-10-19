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
    args = parser.parse_args(argv)
    if args.command == "eval":
        return cmd_eval(args)
    parser.print_help()
    return 0
