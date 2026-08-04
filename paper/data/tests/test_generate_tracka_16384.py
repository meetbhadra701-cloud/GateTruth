"""Regression tests for the hardened 16,384-token Track A table generator."""

from __future__ import annotations

from pathlib import Path

import pytest

from paper.data.generate_tables import TableDataError
from paper.data.generate_tracka_16384 import collect, render
from paper.data.tests.test_generate_tables import (
    TRACK_A_TASK_1,
    TRACK_A_TASK_2,
    _write_track_a_summary,
)

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


def _write_all_seven(
    root: Path, *, task_ids: list[str], failing_tasks: frozenset[str] = frozenset()
) -> None:
    for model in MODELS:
        _write_track_a_summary(
            root,
            run_name=model,
            provider=PROVIDER_OF[model],
            model=model,
            task_ids=task_ids,
            failing_tasks=failing_tasks,
        )


def test_collect_computes_pass_count_and_mean_ppa(tmp_path: Path) -> None:
    task_ids = [TRACK_A_TASK_1, TRACK_A_TASK_2]
    root = tmp_path / "eval-16384"
    _write_all_seven(root, task_ids=task_ids, failing_tasks=frozenset({TRACK_A_TASK_2}))

    rows = collect(root, frozenset(task_ids))

    assert len(rows) == 7
    for row in rows:
        assert row.pass_count == 1
        assert row.tasks == 2
        assert row.mean_ppa_passed == pytest.approx(1.0)

    tex = render(rows)
    assert "1/2" in tex


def test_wrong_model_count_is_refused(tmp_path: Path) -> None:
    task_ids = [TRACK_A_TASK_1]
    root = tmp_path / "eval-16384"
    for model in MODELS[:6]:
        _write_track_a_summary(
            root,
            run_name=model,
            provider=PROVIDER_OF[model],
            model=model,
            task_ids=task_ids,
        )

    with pytest.raises(TableDataError, match="expected 7 models"):
        collect(root, frozenset(task_ids))


def test_tampered_summary_is_refused(tmp_path: Path) -> None:
    task_ids = [TRACK_A_TASK_1]
    root = tmp_path / "eval-16384"
    for model in MODELS:
        _write_track_a_summary(
            root,
            run_name=model,
            provider=PROVIDER_OF[model],
            model=model,
            task_ids=task_ids,
        )
    summary_path = root / "gpt-5" / "gpt-5" / "summary.json"
    import json

    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    raw["cost_usd"] = 999.0
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(TableDataError, match="unsigned or tampered"):
        collect(root, frozenset(task_ids))


def test_duplicate_complete_run_is_refused(tmp_path: Path) -> None:
    task_ids = [TRACK_A_TASK_1]
    root = tmp_path / "eval-16384"
    for model in MODELS:
        _write_track_a_summary(
            root,
            run_name=model,
            provider=PROVIDER_OF[model],
            model=model,
            task_ids=task_ids,
        )
    # A second, equally complete run for the same model at a different path.
    _write_track_a_summary(
        root,
        run_name="gpt-5-archived-copy",
        provider="openai",
        model="gpt-5",
        task_ids=task_ids,
    )

    with pytest.raises(TableDataError, match="ambiguous Track A official run"):
        collect(root, frozenset(task_ids))
