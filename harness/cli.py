"""Command-line interface for SiliconBench."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness.runner import resolve_task, run_task
from harness.scoring import score_manifest
from harness.spend import reserve_spend


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="siliconbench")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a task submission")
    run.add_argument("--task", required=True)
    run.add_argument("--submission", required=True)
    run.add_argument("--out", default="results/tmp/manifest.json")
    run.add_argument("--official", action="store_true", help="require Meet sign-off for an official run")

    score = sub.add_parser("score", help="print task_score from a manifest")
    score.add_argument("--manifest", required=True)

    eval_model = sub.add_parser("eval-model", help="provider skeleton")
    eval_model.add_argument("--provider", required=True)
    eval_model.add_argument("--model", required=True)
    eval_model.add_argument("--track", choices=["A", "B"], required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        if args.official:
            try:
                resolve_task(args.task).task_yaml.require_official_reviews()
            except ValueError as exc:
                print(f"official run refused: {exc}", file=sys.stderr)
                return 2
        manifest = run_task(args.task, args.submission, args.out)
        print(Path(args.out))
        print(f"task_score={manifest.task_score}")
        return 0
    if args.command == "score":
        print(score_manifest(args.manifest))
        return 0
    if args.command == "eval-model":
        reserve_spend(0.0, provider=args.provider, model=args.model)
        print("provider skeleton only; generation not implemented in SB-003")
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
