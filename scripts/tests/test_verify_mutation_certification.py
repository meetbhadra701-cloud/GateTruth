"""Regression tests for the mutation-certification staleness gate (GTFS-030)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.git_provenance import harness_git
from harness.mutate import run_mutation
from harness.runner import runtime_docker_digest_info
from harness.schemas.canonical_json import compute_manifest_signature
from harness.schemas.mutation_certification import (
    MutationCertificationSummary,
    load_mutation_certification_summary,
)
from scripts.verify_mutation_certification import (
    DEFAULT_SUMMARY,
    CertificationCheckError,
    check_summary,
)

TASK_ID = "t1_gray_counter"


def test_real_committed_summary_predates_the_signed_schema_and_is_refused() -> None:
    """The 60 real committed per-task reports and their summary.json were produced
    before GTFS-030 added provenance hashes and a signature -- schema_version 2, no
    task_package_sha256/reference_rtl_sha256/public_testbench_sha256/harness_git/
    signature at all. check_summary() must refuse to silently treat that as either
    fresh or stale; it genuinely cannot be staleness-checked."""

    with pytest.raises(CertificationCheckError, match="cannot be staleness-checked"):
        check_summary(DEFAULT_SUMMARY)


@pytest.fixture(scope="module")
def real_signed_summary(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """One real mutation certification run for the fastest real task, wrapped in a
    genuinely signed schema_version=4 summary -- exactly what
    scripts/certify_mutation.py now produces per task, built here directly to avoid
    paying for all 60 tasks in a routine test run."""

    report = run_mutation(task_id=TASK_ID, min_kill=95.0, seed=1337, jobs=1, official=True)
    assert report["status"] == "ok", report.get("status_reason")
    task_entry = {
        "status": report["status"],
        "total_generated": report["total_generated"],
        "indeterminate": report["indeterminate"],
        "kill_rate": report["kill_rate"],
        "killed": report["killed"],
        "survived": report["survived"],
        "stillborn": report["stillborn"],
        "setup_errors": report["setup_errors"],
        "formal_only_kills": report["formal_only_kills"],
        "total": report["total"],
        "task_package_sha256": report["task_package_sha256"],
        "reference_rtl_sha256": report["reference_rtl_sha256"],
        "public_testbench_sha256": report["public_testbench_sha256"],
        "hidden_module_sha256": report["hidden_module_sha256"],
        "hidden_test_count": report["hidden_test_count"],
    }
    docker_digest, docker_digest_source = runtime_docker_digest_info()
    summary = {
        "schema_version": 4,
        "all_above_floor": task_entry["kill_rate"] >= 95.0,
        "any_unsupported": False,
        "docker_digest": docker_digest,
        "docker_digest_source": docker_digest_source,
        "harness_git": harness_git(),
        "jobs": 1,
        "metric": "simulation_testbench_kill_rate",
        "min_kill": 95.0,
        "official": True,
        "seed": 1337,
        "tasks": {TASK_ID: task_entry},
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "signature": "0" * 64,
    }
    summary["signature"] = compute_manifest_signature(summary)
    MutationCertificationSummary.model_validate(summary)
    return summary


def _write(path: Path, summary: dict) -> Path:
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return path


def test_fresh_real_certification_passes_the_staleness_check(
    real_signed_summary: dict, tmp_path: Path
) -> None:
    path = _write(tmp_path / "fresh.json", real_signed_summary)

    report = check_summary(path)

    assert report.ok
    assert report.fresh == [TASK_ID]
    assert report.stale == []


@pytest.mark.parametrize(
    "field,expected_reason",
    [
        ("task_package_sha256", "task package"),
        ("reference_rtl_sha256", "reference RTL"),
        ("public_testbench_sha256", "public testbench"),
    ],
)
def test_drifted_provenance_hash_is_reported_stale(
    real_signed_summary: dict, tmp_path: Path, field: str, expected_reason: str
) -> None:
    """Tampers only the recorded hash (not any real task file), then re-signs --
    this is exactly the shape a real drifted task would have: the committed
    certification's recorded hash no longer matches what's on disk right now."""

    import copy

    tampered = copy.deepcopy(real_signed_summary)
    tampered["tasks"][TASK_ID][field] = "0" * 64
    tampered["signature"] = compute_manifest_signature(tampered)
    path = _write(tmp_path / "stale.json", tampered)

    report = check_summary(path)

    assert not report.ok
    assert len(report.stale) == 1
    stale_task, reason = report.stale[0]
    assert stale_task == TASK_ID
    assert expected_reason in reason


def test_tampered_signature_is_refused_not_silently_trusted(
    real_signed_summary: dict, tmp_path: Path
) -> None:
    import copy

    tampered = copy.deepcopy(real_signed_summary)
    tampered["all_above_floor"] = not tampered["all_above_floor"]
    # Deliberately do NOT recompute the signature -- this must be caught as a
    # tampered/forged summary, not silently accepted and then staleness-checked.
    path = _write(tmp_path / "forged.json", tampered)

    with pytest.raises(CertificationCheckError, match="cannot be staleness-checked"):
        check_summary(path)

    with pytest.raises(ValidationError):
        load_mutation_certification_summary(path)
