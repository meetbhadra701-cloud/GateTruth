"""Regression tests for the hardened 16,384-token Track A table generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.schemas.canonical_json import compute_manifest_signature
from paper.data.generate_tables import TableDataError
from paper.data.generate_tracka_16384 import collect, render
from paper.data.tests.test_generate_tables import _write_track_a_summary

MODELS = [
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "gpt-5",
    "gpt-5-mini",
    "google/gemini-2.5-pro",
    "meta-llama/llama-4-maverick",
]
PROVIDER_OF = {
    "claude-opus-4-8": "anthropic",
    "claude-sonnet-4-6": "anthropic",
    "claude-haiku-4-5-20251001": "anthropic",
    "gpt-5": "openai",
    "gpt-5-mini": "openai",
    "google/gemini-2.5-pro": "openrouter",
    "meta-llama/llama-4-maverick": "openrouter",
}


def _write_all_seven(root: Path, *, task_ids: list[str], scores: dict[str, list[float]]) -> None:
    for model in MODELS:
        per_task_scores = scores[model]
        aggregate = sum(per_task_scores) / len(per_task_scores)
        _write_track_a_summary(
            root,
            run_name=model,
            provider=PROVIDER_OF[model],
            model=model,
            task_ids=task_ids,
            aggregate_score=aggregate,
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.01,
        )
        # _write_track_a_summary always writes a single passing task; overwrite
        # per-task mean_score directly to control pass@1 for this test.
        summary_path = root / model / model / "summary.json"
        raw = json.loads(summary_path.read_text(encoding="utf-8"))
        for task_id, score in zip(task_ids, per_task_scores, strict=True):
            raw["tasks"][task_id]["mean_score"] = score
            raw["tasks"][task_id]["scores"] = [score]
        raw["signature"] = compute_manifest_signature(raw)
        summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")


def test_collect_computes_pass_count_and_mean_ppa(tmp_path: Path) -> None:
    task_ids = ["t1_alpha", "t2_beta"]
    scores = {model: [66.6666666667, 0.0] for model in MODELS}
    root = tmp_path / "eval-16384"
    _write_all_seven(root, task_ids=task_ids, scores=scores)

    rows = collect(root, frozenset(task_ids))

    assert len(rows) == 7
    for row in rows:
        assert row.pass_count == 1
        assert row.tasks == 2
        assert row.mean_ppa_passed == pytest.approx(1.0)

    tex = render(rows)
    assert "1/2" in tex


def test_wrong_model_count_is_refused(tmp_path: Path) -> None:
    task_ids = ["t1_alpha"]
    root = tmp_path / "eval-16384"
    for model in MODELS[:6]:
        _write_track_a_summary(
            root,
            run_name=model,
            provider=PROVIDER_OF[model],
            model=model,
            task_ids=task_ids,
            aggregate_score=66.67,
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
        )

    with pytest.raises(TableDataError, match="expected 7 models"):
        collect(root, frozenset(task_ids))


def test_tampered_summary_is_refused(tmp_path: Path) -> None:
    task_ids = ["t1_alpha"]
    root = tmp_path / "eval-16384"
    for model in MODELS:
        _write_track_a_summary(
            root,
            run_name=model,
            provider=PROVIDER_OF[model],
            model=model,
            task_ids=task_ids,
            aggregate_score=66.67,
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
        )
    summary_path = root / "gpt-5" / "gpt-5" / "summary.json"
    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    raw["cost_usd"] = 999.0
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(TableDataError, match="unsigned or tampered"):
        collect(root, frozenset(task_ids))


def test_duplicate_complete_run_is_refused(tmp_path: Path) -> None:
    task_ids = ["t1_alpha"]
    root = tmp_path / "eval-16384"
    for model in MODELS:
        _write_track_a_summary(
            root,
            run_name=model,
            provider=PROVIDER_OF[model],
            model=model,
            task_ids=task_ids,
            aggregate_score=66.67,
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
        )
    # A second, equally complete run for the same model at a different path.
    _write_track_a_summary(
        root,
        run_name="gpt-5-archived-copy",
        provider="openai",
        model="gpt-5",
        task_ids=task_ids,
        aggregate_score=99.0,
        tokens_in=10,
        tokens_out=5,
        cost_usd=0.001,
    )

    with pytest.raises(TableDataError, match="ambiguous Track A official run"):
        collect(root, frozenset(task_ids))
