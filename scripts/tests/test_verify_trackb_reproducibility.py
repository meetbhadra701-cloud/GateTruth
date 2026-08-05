"""Regression tests for the Track B reproducibility verification gate (GTFS-052)."""

from __future__ import annotations

import shutil
from pathlib import Path

from harness.trackb import run_track_b
from scripts.verify_trackb_reproducibility import DEFAULT_ROOT, verify_directory

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "toy_taskB"
FIXTURE = REPO_ROOT / "harness" / "tests" / "fixtures" / "toy_taskB"
SOLUTION = REPO_ROOT / "harness" / "tests" / "fixtures" / "toy_taskB_solution" / "toy_trackb.sv"


def test_committed_official_results_are_all_legacy_unbound_with_zero_failures() -> None:
    """Every one of the 56 real committed official Track B manifests predates
    submission_sha256 (P0-3, 2026-08-03), so none of them can be reproduced --
    their design bytes were never retained anywhere durable. This must show up
    as legacy-unbound, never as a silent pass or a false failure. If a future
    official run is committed with submission_sha256 set but a missing or
    tampered design sidecar, this exact assertion starts failing against the
    real repository state -- that is the enforcement GTFS-052 asked for."""

    report = verify_directory(DEFAULT_ROOT)

    assert report.ok
    assert report.reproduced == []
    assert len(report.legacy_unbound) == 56
    assert report.failed == []


def _write_hash_bound_manifest(dest: Path) -> Path:
    submission = dest / "submission"
    shutil.copytree(FIXTURE, submission)
    shutil.copy2(SOLUTION, submission / "design" / "toy_trackb.sv")
    manifest_path = dest / TASK_ID / f"{TASK_ID}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = run_track_b(TASK_ID, submission, manifest_path)
    assert manifest.submission_sha256 is not None
    return manifest_path


def test_hash_bound_manifest_with_intact_sidecar_reproduces(tmp_path: Path) -> None:
    manifest_path = _write_hash_bound_manifest(tmp_path)
    shutil.copy2(SOLUTION, manifest_path.with_suffix(".sv"))

    report = verify_directory(tmp_path)

    assert report.ok
    assert report.reproduced == [str(manifest_path)]
    assert report.legacy_unbound == []
    assert report.failed == []


def test_hash_bound_manifest_with_missing_sidecar_is_reported_as_failed(
    tmp_path: Path,
) -> None:
    manifest_path = _write_hash_bound_manifest(tmp_path)

    report = verify_directory(tmp_path)

    assert not report.ok
    assert report.reproduced == []
    assert len(report.failed) == 1
    failed_path, reason = report.failed[0]
    assert failed_path == str(manifest_path)
    assert "design not found" in reason


def test_hash_bound_manifest_with_tampered_sidecar_is_reported_as_failed(
    tmp_path: Path,
) -> None:
    manifest_path = _write_hash_bound_manifest(tmp_path)
    sidecar = manifest_path.with_suffix(".sv")
    sidecar.write_text(
        SOLUTION.read_text(encoding="utf-8") + "\n// tampered\n", encoding="utf-8"
    )

    report = verify_directory(tmp_path)

    assert not report.ok
    assert len(report.failed) == 1
    failed_path, reason = report.failed[0]
    assert failed_path == str(manifest_path)
    assert "does not match the recorded submission_sha256" in reason


def test_legacy_manifest_without_submission_hash_is_not_a_failure(tmp_path: Path) -> None:
    manifest_path = _write_hash_bound_manifest(tmp_path)
    import json

    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["submission_sha256"] = None
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")

    report = verify_directory(tmp_path)

    assert report.ok
    assert report.reproduced == []
    assert report.legacy_unbound == [str(manifest_path)]
    assert report.failed == []


def test_summary_and_transcript_files_are_ignored(tmp_path: Path) -> None:
    manifest_path = _write_hash_bound_manifest(tmp_path)
    shutil.copy2(SOLUTION, manifest_path.with_suffix(".sv"))
    (manifest_path.parent / "summary.json").write_text("{}", encoding="utf-8")
    (manifest_path.parent / f"{TASK_ID}.transcript.json").write_text("[]", encoding="utf-8")

    report = verify_directory(tmp_path)

    assert report.ok
    assert report.reproduced == [str(manifest_path)]
