"""Regression tests for the run-to-run variance appendix generator."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import pytest

from harness.schemas.canonical_json import compute_manifest_signature
from paper.data.generate_tables import TableDataError
from paper.data.generate_variance_appendix import MODELS, collect, render
from paper.data.tests.test_generate_tables import (
    TRACK_A_TASK_1,
    TRACK_A_TASK_2,
    _write_track_a_manifest,
)

TASK_IDS = [TRACK_A_TASK_1, TRACK_A_TASK_2]
# Achievable with two tasks that are each either fully passing (66.6666666667) or
# fully failing (0.0) via _write_track_a_manifest's passing flag: three distinct,
# exactly-known aggregate values, enough to exercise mean/std/range arithmetic
# without needing arbitrary non-achievable scores.
BOTH_PASS = 66.66666666666667
ONE_PASS = 33.333333333333336
NONE_PASS = 0.0


def _write_run(
    root: Path, model: str, *, failing_tasks: frozenset[str] = frozenset()
) -> float:
    # _write_track_a_summary nests as <root>/<run_name>/<run_name>/summary.json; the
    # variance generator expects <root>/<model>/summary.json (matching
    # results/eval-16384's layout), so write directly with real, dimensionally
    # consistent per-task manifests (score_manifest independently recomputes PPA
    # from these, GTFS-007/GTFS-042) rather than placeholder pointers.
    model_dir = root / model
    manifests = {}
    for task_id in TASK_IDS:
        manifests[task_id] = _write_track_a_manifest(
            model_dir / task_id / "sample_1.json",
            task_id=task_id,
            provider="anthropic",
            model=model,
            passing=task_id not in failing_tasks,
        )
    aggregate = statistics.fmean(m["task_score"] for m in manifests.values())
    raw = {
        "suite_version": "v0.2",
        "prompt_version": "track-a-rtl-v1",
        "provider": "anthropic",
        "model": model,
        "temperature": 0.0,
        "official": True,
        "samples_per_task": 1,
        "task_ids": TASK_IDS,
        "tasks": {
            task_id: {
                "scores": [manifest["task_score"]],
                "mean_score": manifest["task_score"],
                "samples": [
                    {
                        "sample": 1,
                        "score": manifest["task_score"],
                        "manifest": f"{task_id}/sample_1.json",
                        "manifest_signature": manifest["signature"],
                    }
                ],
                "skipped": False,
                "skip_reason": None,
            }
            for task_id, manifest in manifests.items()
        },
        "aggregate_mean": aggregate,
        "tokens_in": sum(m["tokens_in"] for m in manifests.values()),
        "tokens_out": sum(m["tokens_out"] for m in manifests.values()),
        "cost_usd": sum(m["cost_usd"] for m in manifests.values()),
        "timestamp": "2026-07-30T12:00:00.000000Z",
    }
    raw["signature"] = compute_manifest_signature(raw)
    (model_dir / "summary.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return aggregate


@pytest.fixture
def three_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    tasks_root = tmp_path / "tasks"
    for task_id in TASK_IDS:
        (tasks_root / task_id).mkdir(parents=True)
        (tasks_root / task_id / "task.yaml").write_text(f"id: {task_id}\n", encoding="utf-8")
    import paper.data.generate_variance_appendix as gva

    monkeypatch.setattr(gva, "TASKS_ROOT", tasks_root)

    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    run3 = tmp_path / "run3"
    # run1: both tasks pass: run2: one fails: run3: both fail -- three distinct,
    # exactly-known aggregate scores per model (same pattern for all three models,
    # since this fixture only needs *different*, checkable values, not specific ones).
    for model in MODELS:
        _write_run(run1, model, failing_tasks=frozenset())
        _write_run(run2, model, failing_tasks=frozenset({TRACK_A_TASK_2}))
        _write_run(run3, model, failing_tasks=frozenset(TASK_IDS))
    return run1, run2, run3


def test_collect_computes_mean_std_range_matching_stdlib(
    three_runs: tuple[Path, Path, Path],
) -> None:
    run1, run2, run3 = three_runs
    results, condition_bound = collect(run1, run2, run3)

    assert set(results) == set(MODELS)
    assert condition_bound is False  # these fixtures never set max_output_tokens
    opus = results["claude-opus-4-8"]
    assert opus["runs"] == pytest.approx([BOTH_PASS, ONE_PASS, NONE_PASS])
    assert opus["mean"] == pytest.approx(statistics.fmean([BOTH_PASS, ONE_PASS, NONE_PASS]))
    assert opus["std"] == pytest.approx(statistics.stdev([BOTH_PASS, ONE_PASS, NONE_PASS]))
    assert opus["range"] == pytest.approx(BOTH_PASS - NONE_PASS)
    assert opus["single_run"] == pytest.approx(BOTH_PASS)  # run 1's own value, not the mean

    tex = render(results)
    assert "claude-opus-4-8 & 33.33 & 33.33 & 66.67 & 66.67" in tex


def test_tampered_run_is_refused(three_runs: tuple[Path, Path, Path]) -> None:
    run1, run2, run3 = three_runs
    summary_path = run2 / "claude-opus-4-8" / "summary.json"
    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    raw["aggregate_mean"] = 999.0
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(TableDataError, match="unsigned or tampered"):
        collect(run1, run2, run3)


def test_untouched_children_but_forged_aggregate_is_refused(
    three_runs: tuple[Path, Path, Path],
) -> None:
    """GTFS-042's exact reproduction: only the summary's own aggregate_mean moves
    (re-signed over the forgery), every real child manifest is untouched."""

    run1, run2, run3 = three_runs
    summary_path = run2 / "claude-opus-4-8" / "summary.json"
    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    raw["aggregate_mean"] = 98.0
    raw["signature"] = compute_manifest_signature(raw)
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(TableDataError, match="does not match the mean of"):
        collect(run1, run2, run3)


def test_wrong_provider_is_refused(three_runs: tuple[Path, Path, Path]) -> None:
    run1, run2, run3 = three_runs
    summary_path = run1 / "claude-opus-4-8" / "summary.json"
    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    raw["provider"] = "openai"
    raw["signature"] = compute_manifest_signature(raw)
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(TableDataError, match="provider must be anthropic"):
        collect(run1, run2, run3)


def test_non_official_run_is_refused(three_runs: tuple[Path, Path, Path]) -> None:
    run1, run2, run3 = three_runs
    summary_path = run3 / "claude-haiku-4-5-20251001" / "summary.json"
    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    raw["official"] = False
    raw["signature"] = compute_manifest_signature(raw)
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(TableDataError, match="official must be true"):
        collect(run1, run2, run3)


def test_wrong_task_set_is_refused(three_runs: tuple[Path, Path, Path]) -> None:
    run1, run2, run3 = three_runs
    summary_path = run2 / "claude-sonnet-4-6" / "summary.json"
    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    raw["task_ids"] = [TRACK_A_TASK_1]
    del raw["tasks"][TRACK_A_TASK_2]
    raw["signature"] = compute_manifest_signature(raw)
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(TableDataError, match="canonical 60-task suite"):
        collect(run1, run2, run3)


def test_missing_run_is_refused(three_runs: tuple[Path, Path, Path]) -> None:
    run1, run2, run3 = three_runs
    (run3 / "claude-opus-4-8" / "summary.json").unlink()

    with pytest.raises(TableDataError, match="missing variance-study run"):
        collect(run1, run2, run3)
