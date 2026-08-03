"""Regression tests for the run-to-run variance appendix generator."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import pytest

from harness.schemas.canonical_json import compute_manifest_signature
from paper.data.generate_tables import TableDataError
from paper.data.generate_variance_appendix import MODELS, collect, render


def _write_run(root: Path, model: str, *, aggregate_score: float, task_ids: list[str]) -> None:
    # _write_track_a_summary nests as <root>/<run_name>/<run_name>/summary.json; the variance
    # generator expects <root>/<model>/summary.json (matching results/eval-16384's layout), so
    # write directly rather than reusing the double-nested helper.
    model_dir = root / model
    model_dir.mkdir(parents=True, exist_ok=True)
    scores = {task_id: aggregate_score for task_id in task_ids}
    raw = {
        "suite_version": "v0.2",
        "prompt_version": "track-a-rtl-v1",
        "provider": "anthropic",
        "model": model,
        "temperature": 0.0,
        "official": True,
        "samples_per_task": 1,
        "task_ids": task_ids,
        "tasks": {
            task_id: {
                "scores": [score],
                "mean_score": score,
                "samples": [{"sample": 1, "score": score, "manifest": "x", "manifest_signature": "0" * 64}],
                "skipped": False,
                "skip_reason": None,
            }
            for task_id, score in scores.items()
        },
        "aggregate_mean": statistics.fmean(scores.values()),
        "tokens_in": 100,
        "tokens_out": 50,
        "cost_usd": 0.01,
        "timestamp": "2026-07-30T12:00:00.000000Z",
    }
    raw["signature"] = compute_manifest_signature(raw)
    (model_dir / "summary.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def three_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    tasks_root = tmp_path / "tasks"
    task_ids = ["t1_alpha", "t2_beta"]
    for task_id in task_ids:
        (tasks_root / task_id).mkdir(parents=True)
        (tasks_root / task_id / "task.yaml").write_text(f"id: {task_id}\n", encoding="utf-8")
    import paper.data.generate_variance_appendix as gva

    monkeypatch.setattr(gva, "TASKS_ROOT", tasks_root)

    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    run3 = tmp_path / "run3"
    scores = {
        "claude-opus-4-8": (40.0, 44.0, 48.0),
        "claude-sonnet-4-6": (39.0, 43.0, 47.0),
        "claude-haiku-4-5-20251001": (30.0, 31.0, 32.0),
    }
    for model, (s1, s2, s3) in scores.items():
        _write_run(run1, model, aggregate_score=s1, task_ids=task_ids)
        _write_run(run2, model, aggregate_score=s2, task_ids=task_ids)
        _write_run(run3, model, aggregate_score=s3, task_ids=task_ids)
    return run1, run2, run3


def test_collect_computes_mean_std_range_matching_stdlib(
    three_runs: tuple[Path, Path, Path],
) -> None:
    run1, run2, run3 = three_runs
    results = collect(run1, run2, run3)

    assert set(results) == set(MODELS)
    opus = results["claude-opus-4-8"]
    assert opus["runs"] == [40.0, 44.0, 48.0]
    assert opus["mean"] == pytest.approx(44.0)
    assert opus["std"] == pytest.approx(statistics.stdev([40.0, 44.0, 48.0]))
    assert opus["range"] == pytest.approx(8.0)
    assert opus["single_run"] == pytest.approx(40.0)  # run 1's own value, not the mean

    tex = render(results)
    assert "claude-opus-4-8 & 44.00 & 4.00 & 8.00 & 40.00" in tex


def test_tampered_run_is_refused(three_runs: tuple[Path, Path, Path]) -> None:
    run1, run2, run3 = three_runs
    summary_path = run2 / "claude-opus-4-8" / "summary.json"
    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    raw["aggregate_mean"] = 999.0
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(TableDataError, match="unsigned or tampered"):
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
    raw["task_ids"] = ["t1_alpha"]
    del raw["tasks"]["t2_beta"]
    raw["signature"] = compute_manifest_signature(raw)
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(TableDataError, match="canonical 60-task suite"):
        collect(run1, run2, run3)


def test_missing_run_is_refused(three_runs: tuple[Path, Path, Path]) -> None:
    run1, run2, run3 = three_runs
    (run3 / "claude-opus-4-8" / "summary.json").unlink()

    with pytest.raises(TableDataError, match="missing variance-study run"):
        collect(run1, run2, run3)
