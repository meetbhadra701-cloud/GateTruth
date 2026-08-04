"""Unit tests for nightly planning and failure aggregation."""

import shutil
from datetime import date
from pathlib import Path

import pytest

from scripts import nightly
from scripts.nightly import aggregate_failures, rotation_for_day, run_nightly

REPO_ROOT = Path(__file__).resolve().parents[2]


TASKS = [f"task_{index:02d}" for index in range(60)]


def test_rotation_exact_slots_and_ten_night_coverage() -> None:
    assert rotation_for_day(TASKS, 1) == TASKS[:6]
    assert rotation_for_day(TASKS, 10) == TASKS[54:60]
    assert rotation_for_day(TASKS, 11) == TASKS[:6]
    selected = [task for day in range(1, 11) for task in rotation_for_day(TASKS, day)]
    assert selected == TASKS
    assert len(set(selected)) == 60


def test_failure_aggregation_is_stable_and_complete() -> None:
    acceptance = [
        {"task": "good", "status": "pass"},
        {"task": "bad", "status": "fail"},
    ]
    mutation = [
        {"task": "weak", "status": "fail"},
        {"task": "strong", "status": "pass"},
    ]

    assert aggregate_failures(acceptance, mutation, {"status": "fail"}) == [
        "acceptance:bad",
        "mutation:weak",
        "site",
    ]
    assert aggregate_failures(
        [{"task": "good", "status": "pass"}],
        [{"task": "strong", "status": "pass"}],
        {"status": "pass"},
    ) == []


def test_run_nightly_delegates_git_sha_to_harness_git_not_its_own_implementation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """nightly.py used to shell out to plain `git rev-parse` itself, which refuses to
    run at all ("detected dubious ownership") whenever the repo is owned by a
    different user than the one running it -- exactly every sandboxed docker run in
    this project (ci.yml/pages.yml/nightly.yml all stage source this way). That made
    the git_sha field in every real nightly report silently read "unknown". Fixed by
    deleting that duplicate, inferior implementation entirely and delegating to
    harness.git_provenance.harness_git(), which already has its own dedicated test
    suite (harness/tests/test_git_provenance.py) covering the dubious-ownership case
    directly and, separately, GATETRUTH_GIT_COMMIT/GITHUB_SHA env var support -- the
    only way to recover real provenance from ci.yml's .git-free `git archive`
    snapshot, where no git invocation can help at all.

    root=tmp_path with only the real tasks/ tree copied in (task_ids() requires
    exactly 60 real task.yaml files even in --only-task mode) and the three scoring
    stages monkeypatched out: this proves run_nightly()'s own wiring -- that its
    result dict's git_sha field actually comes from harness_git() -- without shelling
    out to `python -m harness.cli`/`harness.mutate` (which would need the harness
    package importable from cwd=tmp_path) or touching the real repo's results/."""

    shutil.copytree(REPO_ROOT / "tasks", tmp_path / "tasks")
    monkeypatch.setattr(
        nightly,
        "_run_acceptance",
        lambda task, root, work_root: {"task": task, "status": "pass", "score": 66.67, "error": None},
    )
    monkeypatch.setattr(
        nightly,
        "_run_mutation",
        lambda task, root, work_root: {"task": task, "status": "pass", "kill_rate": 100.0, "error": None},
    )
    monkeypatch.setattr(nightly, "_run_site", lambda root: {"status": "pass", "error": None})
    monkeypatch.delenv("GATETRUTH_GIT_COMMIT", raising=False)
    monkeypatch.delenv("SILICONBENCH_GIT_COMMIT", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setenv("GATETRUTH_GIT_COMMIT", "abc123def456abc123def456abc123def456abc")

    summary, _line = run_nightly(
        run_date=date(2026, 1, 2), only_task="t1_gray_counter", root=tmp_path
    )

    assert summary["git_sha"] == "abc123def456abc123def456abc123def456abc"
    assert summary["status"] == "PASS"
