"""Command-line interface for SiliconBench."""

from __future__ import annotations

import argparse
import json
import re
import runpy
import sys
from pathlib import Path

from harness.agentb import run_agent_task
from harness.evalagent import estimate_agent_cost, eval_agent, track_b_task_ids
from harness.evalmodel import estimate_model_cost, eval_model, task_ids_for_tier
from harness.providers.anthropic import AnthropicProvider
from harness.providers.mock import MockCompletionProvider, MockProvider
from harness.providers.openai import OpenAIProvider
from harness.providers.openrouter import OpenRouterProvider
from harness.runner import resolve_task, run_task
from harness.trackb import run_track_b
from harness.scoring import score_manifest
from harness.spend import SpendCapExceeded


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="siliconbench")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a task submission")
    run.add_argument("--task", required=True)
    run.add_argument("--submission", required=True)
    run.add_argument("--out", default="results/tmp/manifest.json")
    run.add_argument("--official", action="store_true", help="require Meet sign-off for an official run")

    run_b = sub.add_parser("run-b", help="run a Track B evaluator package")
    run_b.add_argument("--task", required=True)
    run_b.add_argument("--submission-dir", required=True)
    run_b.add_argument("--out", default="results/tmp/manifest_b.json")
    run_b.add_argument("--official", action="store_true")

    run_agent = sub.add_parser("run-agent", help="run a Track B agent")
    run_agent.add_argument("--task", required=True)
    run_agent.add_argument(
        "--provider",
        choices=["mock", "anthropic", "openai", "openrouter"],
        required=True,
    )
    run_agent.add_argument("--script")
    run_agent.add_argument("--model")
    run_agent.add_argument(
        "--run-name",
        default="dev",
        help="canonical result group: results/agent/<run-name>/<model>/<task>.json",
    )
    run_agent.add_argument("--out", help="override the canonical agent result path")
    run_agent.add_argument("--official", action="store_true")

    score = sub.add_parser("score", help="print task_score from a manifest")
    score.add_argument("--manifest", required=True)

    eval_model_parser = sub.add_parser("eval-model", help="run Track A model generation")
    selection = eval_model_parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--tasks", help="comma-separated Track A task ids")
    selection.add_argument("--tier", choices=["T1", "T2", "T3", "all"])
    eval_model_parser.add_argument(
        "--provider",
        choices=["mock", "anthropic", "openai", "openrouter"],
        required=True,
    )
    eval_model_parser.add_argument("--model", required=True)
    eval_model_parser.add_argument("--out")
    eval_model_parser.add_argument("--samples", type=int, default=1)
    eval_model_parser.add_argument("--temperature", type=float, default=0.0)
    eval_model_parser.add_argument("--official", action="store_true")
    eval_model_parser.add_argument(
        "--estimate-only",
        action="store_true",
        help="print worst-case cost without provider calls or output files",
    )
    eval_model_parser.add_argument("--script", help="JSON list of raw completions for mock")

    eval_agent_parser = sub.add_parser("eval-agent", help="run Track B agent evaluation")
    agent_selection = eval_agent_parser.add_mutually_exclusive_group(required=True)
    agent_selection.add_argument("--tasks", help="comma-separated Track B task ids")
    agent_selection.add_argument("--all-b", action="store_true", help="run every Track B task")
    eval_agent_parser.add_argument(
        "--provider",
        choices=["mock", "anthropic", "openai", "openrouter"],
        required=True,
    )
    eval_agent_parser.add_argument("--model")
    eval_agent_parser.add_argument("--out")
    eval_agent_parser.add_argument("--official", action="store_true")
    eval_agent_parser.add_argument(
        "--estimate-only",
        action="store_true",
        help="print worst-case cost without provider calls or output files",
    )
    eval_agent_parser.add_argument("--script", help="JSON action list for each mock task")

    site_parser = sub.add_parser("site", help="build the static leaderboard site")
    site_parser.add_argument("--results", default="results/eval")
    site_parser.add_argument("--agent-results", default="results/agent")
    site_parser.add_argument("--out", default="site/build")

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
        manifest = run_task(
            args.task,
            args.submission,
            args.out,
            official=args.official,
        )
        print(Path(args.out))
        print(f"task_score={manifest.task_score}")
        return 0
    if args.command == "run-b":
        manifest = run_track_b(
            args.task,
            args.submission_dir,
            args.out,
            official=args.official,
        )
        print(Path(args.out))
        print(f"task_score={manifest.task_score}")
        print(f"objective_pass={manifest.objective_pass}")
        print(f"disqualified={manifest.disqualified}")
        return 0
    if args.command == "run-agent":
        if args.provider == "mock":
            if not args.script:
                print("--script is required for provider mock", file=sys.stderr)
                return 2
            script = json.loads(Path(args.script).read_text(encoding="utf-8"))
            if not isinstance(script, list):
                print("mock script must be a JSON list", file=sys.stderr)
                return 2
            provider = MockProvider(script)
        else:
            if not args.model:
                print("--model is required for real providers", file=sys.stderr)
                return 2
            providers = {
                "anthropic": AnthropicProvider,
                "openai": OpenAIProvider,
                "openrouter": OpenRouterProvider,
            }
            provider = providers[args.provider](args.model)
        output = Path(args.out) if args.out else _default_agent_output(
            args.run_name,
            str(getattr(provider, "model", "agent")),
            args.task,
        )
        manifest = run_agent_task(
            args.task,
            provider,
            out=output,
            official=args.official,
        )
        print(output)
        print(f"task_score={manifest.task_score}")
        print(f"objective_pass={manifest.objective_pass}")
        print(f"budget_exceeded={manifest.budget_exceeded}")
        print(f"tokens_in={manifest.tokens_in}")
        print(f"tokens_out={manifest.tokens_out}")
        print(f"cost_usd={manifest.cost_usd}")
        return 0
    if args.command == "score":
        print(score_manifest(args.manifest))
        return 0
    if args.command == "eval-model":
        if args.samples < 1:
            print("--samples must be at least 1", file=sys.stderr)
            return 2
        if args.temperature < 0:
            print("--temperature must be nonnegative", file=sys.stderr)
            return 2
        if args.tasks:
            task_ids = [task.strip() for task in args.tasks.split(",") if task.strip()]
            if not task_ids:
                print("--tasks must contain at least one task id", file=sys.stderr)
                return 2
        else:
            task_ids = task_ids_for_tier(args.tier)
        try:
            if args.estimate_only:
                estimate = estimate_model_cost(
                    task_ids,
                    args.provider,
                    args.model,
                    samples=args.samples,
                    official=args.official,
                )
                print("estimate_only=true")
                print(f"tasks_requested={len(task_ids)}")
                print(f"projected_total_usd={estimate:.6f}")
                return 0
            if not args.out:
                print("--out is required unless --estimate-only is used", file=sys.stderr)
                return 2
            if args.provider == "mock":
                if not args.script:
                    print("--script is required for provider mock", file=sys.stderr)
                    return 2
                responses = json.loads(Path(args.script).read_text(encoding="utf-8"))
                if not isinstance(responses, list):
                    print("mock completion script must be a JSON list", file=sys.stderr)
                    return 2
                provider = MockCompletionProvider(
                    responses,
                    model=args.model,
                    temperature=args.temperature,
                )
            else:
                providers = {
                    "anthropic": AnthropicProvider,
                    "openai": OpenAIProvider,
                    "openrouter": OpenRouterProvider,
                }
                provider = providers[args.provider](
                    args.model,
                    temperature=args.temperature,
                )
            summary = eval_model(
                task_ids,
                provider,
                out_dir=args.out,
                samples=args.samples,
                official=args.official,
            )
        except (OSError, ValueError, SpendCapExceeded) as exc:
            print(f"eval-model refused: {exc}", file=sys.stderr)
            return 2
        print(f"summary_signature={summary['signature']}")
        print(f"aggregate_mean={summary['aggregate_mean']}")
        print(f"cost_usd={summary['cost_usd']}")
        return 0
    if args.command == "eval-agent":
        if args.tasks:
            task_ids = [task.strip() for task in args.tasks.split(",") if task.strip()]
            if not task_ids:
                print("--tasks must contain at least one task id", file=sys.stderr)
                return 2
        else:
            task_ids = track_b_task_ids()
        try:
            if args.estimate_only:
                if not args.model:
                    print("--model is required for --estimate-only", file=sys.stderr)
                    return 2
                estimate = estimate_agent_cost(
                    task_ids,
                    args.provider,
                    args.model,
                    official=args.official,
                )
                print("estimate_only=true")
                print(f"tasks_requested={len(task_ids)}")
                print(f"projected_total_usd={estimate:.6f}")
                return 0
            if not args.out:
                print("--out is required unless --estimate-only is used", file=sys.stderr)
                return 2
            if args.provider == "mock":
                if not args.script:
                    print("--script is required for provider mock", file=sys.stderr)
                    return 2
                actions = json.loads(Path(args.script).read_text(encoding="utf-8"))
                if not isinstance(actions, list) or not all(
                    isinstance(action, dict) for action in actions
                ):
                    print("mock agent script must be a JSON object list", file=sys.stderr)
                    return 2
                provider = MockProvider(actions * len(task_ids))
                if args.model:
                    provider.model = args.model
            else:
                if not args.model:
                    print("--model is required for real providers", file=sys.stderr)
                    return 2
                providers = {
                    "anthropic": AnthropicProvider,
                    "openai": OpenAIProvider,
                    "openrouter": OpenRouterProvider,
                }
                provider = providers[args.provider](args.model)
            summary = eval_agent(
                task_ids,
                provider,
                out_dir=args.out,
                official=args.official,
            )
        except (OSError, ValueError, SpendCapExceeded) as exc:
            print(f"eval-agent refused: {exc}", file=sys.stderr)
            return 2
        print(f"summary_signature={summary['signature']}")
        print(f"objective_met_rate={summary['objective_met_rate']}")
        print(f"cost_usd={summary['cost_usd']}")
        return 0
    if args.command == "site":
        generator_path = Path(__file__).resolve().parents[1] / "site" / "generate.py"
        namespace = runpy.run_path(str(generator_path))
        try:
            built = namespace["generate_site"](
                args.results,
                args.out,
                agent_results_root=args.agent_results,
            )
        except namespace["SiteGenerationError"] as exc:
            print(f"site generation refused: {exc}", file=sys.stderr)
            return 2
        for path in built.values():
            print(path)
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


def _default_agent_output(run_name: str, model: str, task_id: str) -> Path:
    return Path("results/agent") / _path_component(run_name) / _path_component(model) / (
        f"{_path_component(task_id)}.json"
    )


def _path_component(value: str) -> str:
    component = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return component or "run"


if __name__ == "__main__":
    raise SystemExit(main())
