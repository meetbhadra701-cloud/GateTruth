"""Regression tests for GTFS-014: validate_track_b_semantics must recompute
objective truth from a manifest's own recorded stages/metrics, not trust the
top-level disqualified/objective_pass/task_score fields directly."""

from __future__ import annotations

import pytest

from harness.schemas.canonical_json import compute_manifest_signature
from harness.schemas.manifest_b import TrackBManifest
from harness.trackb import validate_track_b_semantics


def _resigned(data: dict) -> dict:
    data = dict(data)
    data["signature"] = compute_manifest_signature(data)
    return data


def _passing_toy_trackb_manifest() -> dict:
    """toy_taskB is behavior_preserving: true, objective type area_reduction --
    exercises the SEC-required branch with a real resolvable task."""

    return _resigned(
        {
            "task_id": "toy_taskB",
            "suite_version": "v0.2",
            "track": "B",
            "docker_digest": "sha256:" + "ab" * 32,
            "docker_digest_source": "env",
            "platform": "linux/amd64",
            "submission_dir": "/tmp/fixture/submission",
            "submission_sha256": None,
            "disqualified": False,
            "disqualification_reason": None,
            "objective_type": "area_reduction",
            "objective_pass": True,
            "stages": [
                {"stage": 0, "name": "lint", "status": "pass", "warnings": 0},
                {
                    "stage": 1,
                    "name": "sim",
                    "status": "pass",
                    "tests_run": 4,
                    "tests_passed": 4,
                },
                {"stage": 2, "name": "sec", "status": "pass"},
                {"stage": 3, "name": "objective", "status": "pass"},
            ],
            "sec": {"status": "pass", "backend": "yosys-equiv", "seconds": 1.2},
            "ppa_delta": {
                "design": {
                    "area_um2": 80.0,
                    "wns_ns": 1.0,
                    "tns_ns": 0.0,
                    "fmax_mhz": 100.0,
                    "power_mw": 0.5,
                },
                "baseline": {
                    "area_um2": 100.0,
                    "wns_ns": 2.0,
                    "tns_ns": 0.0,
                    "fmax_mhz": 100.0,
                    "power_mw": 1.0,
                },
                "area_ratio": 0.8,
                "power_ratio": 0.5,
                "wns_delta_ns": -1.0,
            },
            "task_score": 100.0,
            "wall_clock_s": 12.5,
            "provider": "local",
            "model": "fixture",
            "temperature": 0.0,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "tool_calls": 0,
            "baseline_review": None,
            "tb_review": None,
            "hidden_module_sha256": None,
            "hidden_test_count": None,
            "timestamp": "2026-08-04T00:00:00Z",
            "signature": "0" * 64,
        }
    )


def test_accepts_a_genuinely_passing_manifest():
    manifest = TrackBManifest.model_validate(_passing_toy_trackb_manifest())
    validate_track_b_semantics(manifest)  # must not raise


def test_rejects_the_ticket_probe_all_stages_skipped_sec_failed():
    """GTFS-014's exact reproduction: every stage skip, sec.status fail, nonsensical
    PPA ratios inserted, yet objective_pass/task_score still claim full success."""

    data = _passing_toy_trackb_manifest()
    data["stages"] = [
        {"stage": 0, "name": "lint", "status": "skip"},
        {"stage": 1, "name": "sim", "status": "skip"},
        {"stage": 2, "name": "correctness", "status": "skip"},
        {"stage": 3, "name": "objective", "status": "skip"},
    ]
    data["sec"] = {"status": "fail", "backend": None, "seconds": None}
    data["ppa_delta"] = {
        "design": None,
        "baseline": None,
        "area_ratio": 99.0,
        "power_ratio": 99.0,
        "wns_delta_ns": -999.0,
    }
    manifest = TrackBManifest.model_validate(_resigned(data))

    with pytest.raises(ValueError, match="never legitimately skipped"):
        validate_track_b_semantics(manifest)


def test_rejects_sec_gate_faked_as_passed_when_stage_says_fail():
    data = _passing_toy_trackb_manifest()
    data["sec"] = {"status": "pass", "backend": "yosys-equiv", "seconds": 1.0}
    for stage in data["stages"]:
        if stage["stage"] == 2:
            stage["status"] = "fail"
    manifest = TrackBManifest.model_validate(_resigned(data))

    with pytest.raises(ValueError, match="sec.status must be"):
        validate_track_b_semantics(manifest)


def test_accepts_a_sec_timeout_recorded_as_stage_fail():
    """run_sec() folds a Yosys timeout into stage status "fail" but records
    sec.status="timeout" -- this asymmetry is legitimate, not a mismatch."""

    data = _passing_toy_trackb_manifest()
    data["objective_pass"] = False
    data["task_score"] = 0.0
    data["sec"] = {"status": "timeout", "backend": "yosys-equiv", "seconds": None}
    for stage in data["stages"]:
        if stage["stage"] == 2:
            stage["status"] = "fail"
        elif stage["stage"] == 3:
            stage["status"] = "fail"
    manifest = TrackBManifest.model_validate(_resigned(data))

    validate_track_b_semantics(manifest)  # must not raise


def test_rejects_forged_ppa_area_ratio():
    data = _passing_toy_trackb_manifest()
    data["ppa_delta"]["area_ratio"] = 0.1  # real design/baseline ratio is 0.8
    manifest = TrackBManifest.model_validate(_resigned(data))

    with pytest.raises(ValueError, match="area_ratio"):
        validate_track_b_semantics(manifest)


def test_rejects_objective_pass_without_a_passing_objective_stage():
    data = _passing_toy_trackb_manifest()
    for stage in data["stages"]:
        if stage["stage"] == 3:
            stage["status"] = "fail"
    manifest = TrackBManifest.model_validate(_resigned(data))

    with pytest.raises(ValueError, match="stage 3"):
        validate_track_b_semantics(manifest)


def test_accepts_a_legitimately_disqualified_manifest():
    data = _passing_toy_trackb_manifest()
    data["disqualified"] = True
    data["disqualification_reason"] = "malformed submission: missing design directory"
    data["objective_pass"] = False
    data["task_score"] = 0.0
    data["stages"] = [
        {"stage": 0, "name": "lint", "status": "skip"},
        {"stage": 1, "name": "sim", "status": "skip"},
        {"stage": 2, "name": "correctness", "status": "skip"},
        {"stage": 3, "name": "objective", "status": "skip"},
    ]
    data["sec"] = {"status": "skip", "backend": None, "seconds": None}
    data["ppa_delta"] = {
        "design": None,
        "baseline": None,
        "area_ratio": None,
        "power_ratio": None,
        "wns_delta_ns": None,
    }
    manifest = TrackBManifest.model_validate(_resigned(data))

    validate_track_b_semantics(manifest)  # must not raise
