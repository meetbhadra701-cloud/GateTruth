"""Generate the Track A run-to-run variance appendix from signed per-run manifests.

Reads three signed summary.json files per Anthropic model at the reported 16,384-token
condition: the already-committed single run (``results/eval-16384/<model>/summary.json``,
also Table 1's "single run" figure) as run 1, plus two fresh official re-runs
(``results/variance/run{2,3}/<model>/summary.json``) executed for exactly this purpose. This
closes the gap the paper previously disclosed in Appendix A: "the nine individual per-run
manifests this study is computed from are not currently committed to the repository alongside a
generator that reproduces the table's mean, standard deviation, and range from them." They now
are, and this script is that generator.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.schemas.canonical_json import compute_manifest_signature  # noqa: E402
from harness.schemas.manifest import load_manifest  # noqa: E402
from paper.data.generate_tables import (  # noqa: E402
    TableDataError,
    _referenced_manifest,
    _track_a_incomplete_reason,
    _track_a_validated_scores,
)

RUN1_ROOT = REPO_ROOT / "results" / "eval-16384"
RUN2_ROOT = REPO_ROOT / "results" / "variance" / "run2"
RUN3_ROOT = REPO_ROOT / "results" / "variance" / "run3"
OUT_PATH = REPO_ROOT / "paper" / "data" / "build" / "variance_table.tex"
TASKS_ROOT = REPO_ROOT / "tasks"

MODELS = ("claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001")


def _canonical_task_ids() -> frozenset[str]:
    return frozenset(path.parent.name for path in TASKS_ROOT.glob("*/task.yaml"))


def _load_summary(path: Path, *, model: str) -> tuple[dict, float, bool]:
    """Validate one run's summary and independently recompute its aggregate from
    its own signed child manifests -- a summary whose children are absent or
    untouched-but-forged (GTFS-042's exact reproduction: nine summary.json files
    copied into otherwise-empty run directories, no per-task manifests at all)
    used to be accepted purely on its own internal signature. Also checks
    whether every child manifest actually records the claimed 16,384-token
    condition; returns whether it does, since the historical variance-study
    manifests were captured before that field existed and may not."""

    if not path.is_file():
        raise TableDataError(f"missing variance-study run: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    signature = raw.get("signature")
    if not isinstance(signature, str) or signature != compute_manifest_signature(raw):
        raise TableDataError(f"unsigned or tampered summary: {path}")
    if raw.get("provider") != "anthropic":
        raise TableDataError(f"{path}: provider must be anthropic, got {raw.get('provider')!r}")
    if raw.get("model") != model:
        raise TableDataError(f"{path}: model {raw.get('model')!r} != expected {model!r}")
    if raw.get("official") is not True:
        raise TableDataError(f"{path}: official must be true for the variance study")
    expected = _canonical_task_ids()
    task_ids = raw.get("task_ids")
    if not isinstance(task_ids, list) or set(task_ids) != expected:
        raise TableDataError(f"{path}: task_ids do not match the canonical 60-task suite")
    aggregate = raw.get("aggregate_mean")
    if not isinstance(aggregate, (int, float)):
        raise TableDataError(f"{path}: aggregate_mean missing or non-numeric")

    reason = _track_a_incomplete_reason(raw, path, expected)
    if reason is not None:
        raise TableDataError(f"{path}: {reason}")
    per_task = _track_a_validated_scores(raw, path, expected)
    real_aggregate = statistics.fmean(score for score, _tokens, _cost in per_task.values())
    if not math.isclose(float(aggregate), real_aggregate, abs_tol=1e-6):
        raise TableDataError(
            f"{path}: aggregate_mean {aggregate} does not match the mean of "
            f"{len(per_task)} recomputed child task scores ({real_aggregate})"
        )

    condition_bound = True
    for task_id in expected:
        manifest_path = _referenced_manifest(
            path, raw["tasks"][task_id]["samples"][0].get("manifest")
        )
        max_output_tokens = load_manifest(manifest_path).max_output_tokens
        if max_output_tokens is None:
            condition_bound = False
        elif max_output_tokens != 16384:
            raise TableDataError(
                f"{path}: {task_id} manifest records max_output_tokens="
                f"{max_output_tokens}, not the claimed 16384"
            )

    return raw, real_aggregate, condition_bound


def collect(
    run1_root: Path = RUN1_ROOT, run2_root: Path = RUN2_ROOT, run3_root: Path = RUN3_ROOT
) -> tuple[dict[str, dict], bool]:
    """Returns (per-model results, whether every child manifest across all nine
    runs actually records the claimed 16,384-token condition). The second value
    is a real, checked fact, not an assumption -- see _load_summary."""

    results: dict[str, dict] = {}
    seen_signatures: set[str] = set()
    condition_bound = True
    for model in MODELS:
        runs = []
        for root in (run1_root, run2_root, run3_root):
            summary, real_aggregate, run_condition_bound = _load_summary(
                root / model / "summary.json", model=model
            )
            condition_bound = condition_bound and run_condition_bound
            if summary["signature"] in seen_signatures:
                raise TableDataError(
                    f"the same signed run appears twice in the variance study: "
                    f"{summary['signature']}"
                )
            seen_signatures.add(summary["signature"])
            runs.append(real_aggregate)
        mean = statistics.fmean(runs)
        std = statistics.stdev(runs)  # Bessel-corrected, n-1, matching the paper's caption
        results[model] = {
            "runs": runs,
            "mean": mean,
            "std": std,
            "range": max(runs) - min(runs),
            "single_run": runs[0],  # run 1 is the already-reported Table 1 figure
        }
    return results, condition_bound


def render(results: dict[str, dict]) -> str:
    lines = [
        "% generated by paper/data/generate_variance_appendix.py -- do not hand-edit",
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"Model & mean (n=3) & std & range & single run \\",
        r"\midrule",
    ]
    for model in MODELS:
        r = results[model]
        lines.append(
            f"{model} & {r['mean']:.2f} & {r['std']:.2f} & "
            f"{r['range']:.2f} & {r['single_run']:.2f} \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run1-root", type=Path, default=RUN1_ROOT)
    parser.add_argument("--run2-root", type=Path, default=RUN2_ROOT)
    parser.add_argument("--run3-root", type=Path, default=RUN3_ROOT)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args(argv)

    try:
        results, condition_bound = collect(args.run1_root, args.run2_root, args.run3_root)
    except TableDataError as exc:
        parser.exit(2, f"variance appendix generation refused: {exc}\n")

    rendered = render(results)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")
    for model in MODELS:
        r = results[model]
        print(
            f"  {model:30s} mean={r['mean']:.4f} std={r['std']:.4f} "
            f"range={r['range']:.4f} runs={[round(x, 4) for x in r['runs']]}"
        )
    if condition_bound:
        print("  16384-token condition: bound to every child manifest's max_output_tokens")
    else:
        print(
            "  16384-token condition: NOT cryptographically bound -- at least one child "
            "manifest predates the max_output_tokens field and records it as null; the "
            "condition holds only by directory-name/prose convention for those runs"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
