"""Offline-rescore signed Track A official results with real PPA metrics."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from datetime import date
from pathlib import Path
from statistics import fmean
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.schemas.canonical_json import compute_manifest_signature  # noqa: E402
from harness.schemas.manifest import ResultManifest  # noqa: E402
from harness.scoring import (  # noqa: E402
    PpaMetrics,
    correctness_gates_passed,
    delay_from_wns,
    load_reference_metrics,
    ppa_from_metrics,
    ppa_gates_passed,
    task_score_from_ppa,
)
from paper.data.generate_tables import generate_tables  # noqa: E402

EXPECTED_MANIFESTS = 420
EXPECTED_SUMMARIES = 7
EXPECTED_SCORES = {
    "claude-opus-4-8": 46.91,
    "claude-sonnet-4-6": 45.03,
    "claude-haiku-4-5-20251001": 33.58,
    "gpt-5-mini": 33.44,
    "gpt-5": 31.64,
    "meta-llama/llama-4-maverick": 25.52,
    "google/gemini-2.5-pro": 17.83,
}
TRACKED_PAPER_TABLES = (
    "eval_table.tex",
    "mutation_table.tex",
    "tasks_table.tex",
    "trackb_table.tex",
)


class RescoreError(ValueError):
    """Raised when official data cannot be deterministically rescored."""


def build_rescore(
    eval_dir: Path,
) -> tuple[dict[Path, str], dict[str, float], list[dict[str, Any]]]:
    """Return desired JSON bytes, aggregate scores, and signed summaries."""

    updates: dict[Path, str] = {}
    aggregates: dict[str, float] = {}
    summaries: list[dict[str, Any]] = []
    manifest_count = 0
    summary_paths = sorted(eval_dir.glob("**/summary.json"))
    if len(summary_paths) != EXPECTED_SUMMARIES:
        raise RescoreError(
            f"expected {EXPECTED_SUMMARIES} official summaries, "
            f"found {len(summary_paths)}"
        )

    for summary_path in summary_paths:
        summary = _load_signed_json(summary_path)
        tasks = summary.get("tasks")
        if not isinstance(tasks, dict) or len(tasks) != 60:
            raise RescoreError(f"official summary is not a 60-task run: {summary_path}")
        all_scores: list[float] = []
        for task_id, entry in tasks.items():
            if not isinstance(entry, dict):
                raise RescoreError(f"malformed task entry {task_id}: {summary_path}")
            samples = entry.get("samples")
            if not isinstance(samples, list) or not samples:
                raise RescoreError(f"missing samples for {task_id}: {summary_path}")
            scores: list[float] = []
            for sample in samples:
                if not isinstance(sample, dict):
                    raise RescoreError(f"malformed sample for {task_id}: {summary_path}")
                relative = sample.get("manifest")
                if not isinstance(relative, str):
                    raise RescoreError(
                        f"missing manifest path for {task_id}: {summary_path}"
                    )
                manifest_path = (summary_path.parent / relative).resolve()
                if not manifest_path.is_relative_to(summary_path.parent.resolve()):
                    raise RescoreError(f"manifest escapes run directory: {relative}")
                raw = _load_signed_json(manifest_path)
                rescored = rescore_manifest(raw)
                updates[manifest_path] = _render(rescored)
                score = float(rescored["task_score"])
                scores.append(score)
                sample["score"] = score
                sample["manifest_signature"] = rescored["signature"]
                manifest_count += 1
            entry["scores"] = scores
            entry["mean_score"] = float(fmean(scores))
            if entry.get("skipped") is not True:
                all_scores.extend(scores)
        summary["aggregate_mean"] = (
            float(fmean(all_scores)) if all_scores else 0.0
        )
        summary["signature"] = compute_manifest_signature(summary)
        updates[summary_path] = _render(summary)
        model = summary.get("model")
        if not isinstance(model, str) or not model:
            raise RescoreError(f"summary has no model: {summary_path}")
        aggregates[model] = float(summary["aggregate_mean"])
        summaries.append(summary)

    if manifest_count != EXPECTED_MANIFESTS:
        raise RescoreError(
            f"expected {EXPECTED_MANIFESTS} official manifests, "
            f"found {manifest_count}"
        )
    return updates, aggregates, summaries


def rescore_manifest(raw: dict[str, Any]) -> dict[str, Any]:
    """Recompute one signed manifest using only its stored physical metrics."""

    manifest = ResultManifest.model_validate(raw)
    if correctness_gates_passed(manifest) and ppa_gates_passed(manifest):
        stages = {stage.stage: stage for stage in manifest.stages}
        synth = stages[3]
        sta = stages[4]
        power = stages[5]
        reference = load_reference_metrics(manifest.task_id)
        if (
            synth.area_um2 is None
            or sta.wns_ns is None
            or power.power_mw is None
        ):
            raise RescoreError(f"{manifest.task_id} is missing passing PPA metrics")
        try:
            measured = PpaMetrics(
                area_um2=synth.area_um2,
                delay_ns=delay_from_wns(
                    reference.clock_target_ns,
                    sta.wns_ns,
                ),
                power_mw=power.power_mw,
                clock_target_ns=reference.clock_target_ns,
            )
        except ValueError:
            _fail_invalid_ppa_stages(raw)
            ppa = 0.0
        else:
            ppa = ppa_from_metrics(reference, measured)
    else:
        ppa = 0.0
    raw["ppa"] = ppa
    raw["task_score"] = task_score_from_ppa(ppa) if ppa > 0 else 0.0
    raw["signature"] = compute_manifest_signature(raw)
    ResultManifest.model_validate(raw)
    return raw


def _fail_invalid_ppa_stages(raw: dict[str, Any]) -> None:
    for stage in raw["stages"]:
        if stage.get("stage") not in {3, 4, 5}:
            continue
        stage["status"] = "fail"
        for key in (
            "area_um2",
            "cell_count",
            "wns_ns",
            "tns_ns",
            "fmax_mhz",
            "power_mw",
        ):
            stage.pop(key, None)


def _load_signed_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RescoreError(f"cannot read signed JSON {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RescoreError(f"signed JSON must be an object: {path}")
    if raw.get("signature") != compute_manifest_signature(raw):
        raise RescoreError(f"unsigned or tampered JSON: {path}")
    return raw


def _render(raw: dict[str, Any]) -> str:
    return json.dumps(raw, indent=2) + "\n"


def _data_marker(summaries: list[dict[str, Any]]) -> tuple[date, str]:
    dates: list[date] = []
    signatures: list[str] = []
    for summary in summaries:
        timestamp = summary.get("timestamp")
        signature = summary.get("signature")
        if not isinstance(timestamp, str) or len(timestamp) < 10:
            raise RescoreError("official summary has an invalid timestamp")
        if not isinstance(signature, str):
            raise RescoreError("official summary has no signature")
        dates.append(date.fromisoformat(timestamp[:10]))
        signatures.append(signature)
    digest = hashlib.sha256("".join(sorted(signatures)).encode("ascii")).hexdigest()
    return max(dates), f"official-data-{digest[:12]}"


def _generate_paper_tables(
    *,
    summaries: list[dict[str, Any]],
    eval_dir: Path,
    output: Path,
) -> None:
    generated_date, marker = _data_marker(summaries)
    generate_tables(
        out_dir=output,
        eval_dir=eval_dir,
        generated_date=generated_date,
        git_sha=marker,
    )


def _check_expected_scores(aggregates: dict[str, float]) -> None:
    if set(aggregates) != set(EXPECTED_SCORES):
        missing = sorted(set(EXPECTED_SCORES) - set(aggregates))
        extra = sorted(set(aggregates) - set(EXPECTED_SCORES))
        raise RescoreError(f"official model mismatch: missing={missing}, extra={extra}")
    for model, expected in EXPECTED_SCORES.items():
        actual = aggregates[model]
        if not math.isclose(actual, expected, abs_tol=0.01):
            raise RescoreError(
                f"{model} score {actual:.6f} does not match target {expected:.2f}"
            )


def _print_scores(aggregates: dict[str, float]) -> None:
    print("model                              SiliconScore")
    for model, score in sorted(
        aggregates.items(),
        key=lambda item: (-item[1], item[0]),
    ):
        print(f"{model:<34} {score:>12.6f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-dir", default="results/eval/official")
    parser.add_argument("--paper-out", default="paper/data/build")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    eval_dir = Path(args.eval_dir)
    paper_out = Path(args.paper_out)

    try:
        updates, aggregates, summaries = build_rescore(eval_dir)
        _check_expected_scores(aggregates)
        stale = [
            path
            for path, desired in updates.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != desired
        ]
        if args.check:
            if stale:
                raise RescoreError(
                    f"{len(stale)} official JSON files need offline rescore"
                )
            with tempfile.TemporaryDirectory(prefix="sb-rescore-paper-") as temp:
                expected_dir = Path(temp)
                _generate_paper_tables(
                    summaries=summaries,
                    eval_dir=eval_dir,
                    output=expected_dir,
                )
                mismatched = [
                    name
                    for name in TRACKED_PAPER_TABLES
                    if (expected_dir / name).read_bytes()
                    != (paper_out / name).read_bytes()
                ]
                if mismatched:
                    raise RescoreError(
                        f"paper tables need regeneration: {', '.join(mismatched)}"
                    )
            print(
                "offline rescore check: PASS "
                f"({EXPECTED_MANIFESTS} manifests, {EXPECTED_SUMMARIES} summaries)"
            )
        else:
            for path in stale:
                path.write_text(updates[path], encoding="utf-8", newline="\n")
            _generate_paper_tables(
                summaries=summaries,
                eval_dir=eval_dir,
                output=paper_out,
            )
            print(
                f"offline rescore wrote {len(stale)} JSON files; "
                "paper tables regenerated"
            )
        _print_scores(aggregates)
        return 0
    except (OSError, RescoreError, ValueError) as exc:
        print(f"offline rescore failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
