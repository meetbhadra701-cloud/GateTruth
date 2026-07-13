"""Unit tests for nightly planning and failure aggregation."""

from scripts.nightly import aggregate_failures, rotation_for_day


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
