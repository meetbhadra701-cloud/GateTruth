"""Unit tests for nightly planning and failure aggregation."""

import subprocess
from pathlib import Path

from scripts.nightly import _git_sha, aggregate_failures, rotation_for_day

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


def test_git_sha_resolves_the_real_commit_even_under_dubious_ownership():
    """Mirrors paper/data/tests/test_generate_tables.py's identical test: nightly.py
    has its own separate _git_sha() implementation with the same bug that one had
    (plain `git rev-parse` refuses to run under a bind mount owned by a different
    user, which is exactly ci.yml's own source-staging pattern)."""

    sha = _git_sha(REPO_ROOT)

    assert sha != "unknown"
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)
    expected = subprocess.run(
        ["git", "-c", f"safe.directory={REPO_ROOT}", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert sha == expected
