"""Regression test for the public contamination gate."""

from scripts.contamination_check import REPO_ROOT, run_checks


def test_repository_contamination_gate() -> None:
    report = run_checks(REPO_ROOT)
    assert report.track_a_tasks == 60
    assert report.hidden_markers == 0
    assert report.hidden_loaders == 68
    assert report.package_canaries == 70
