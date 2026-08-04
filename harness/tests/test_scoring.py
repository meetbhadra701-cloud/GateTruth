import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness import runner
from harness.schemas.canonical_json import compute_manifest_signature
from harness.schemas.manifest import ResultManifest, load_manifest
from harness.scoring import (
    PpaMetrics,
    load_reference_metrics,
    ppa_from_metrics,
    score_manifest,
    task_score_from_ppa,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _resigned(data: dict) -> dict:
    data = dict(data)
    data["signature"] = compute_manifest_signature(data)
    return data


def _dimensionally_consistent_manifest() -> dict:
    """A toy_task manifest whose stage metrics genuinely correspond to ppa=1.0
    against the committed toy_task reference (unlike fixtures/valid_manifest.json,
    which uses hand-picked round numbers for structural schema tests and is not
    dimensionally consistent with the reference -- fine for schema tests, wrong for
    score_manifest's metrics-recomputation tests, which need a real match)."""

    reference = load_reference_metrics("toy_task")
    data = json.loads((FIXTURES / "valid_manifest.json").read_text())
    for stage in data["stages"]:
        if stage["stage"] == 3:
            stage["area_um2"] = reference.area_um2
        elif stage["stage"] == 4:
            stage["wns_ns"] = reference.clock_target_ns - reference.delay_ns
        elif stage["stage"] == 5:
            stage["power_mw"] = reference.power_mw
    data["ppa"] = 1.0
    data["task_score"] = task_score_from_ppa(1.0)
    return _resigned(data)


def test_reference_score_formula():
    assert math.isclose(task_score_from_ppa(1.0), 66.66666666666667)


def test_ppa_cap():
    assert task_score_from_ppa(99.0) == 100.0


def test_gate_zero():
    assert task_score_from_ppa(0.0) == 0.0
    with pytest.raises(ValidationError):
        load_manifest("harness/tests/fixtures/bad_manifests/gate_fail_nonzero_score.json")


def test_negative_ppa_rejected():
    with pytest.raises(ValueError):
        task_score_from_ppa(-0.1)


def test_committed_reference_metrics_cover_canonical_suite():
    raw = json.loads(
        Path("harness/reference_metrics.json").read_text(encoding="utf-8")
    )

    assert raw["schema_version"] == "1"
    assert len(raw["tasks"]) == 60
    assert set(raw["tasks"]) == {
        task.parent.name for task in Path("tasks").glob("*/task.yaml")
    }


def test_reference_metrics_score_against_themselves():
    reference = load_reference_metrics("t2_sync_fifo")

    assert ppa_from_metrics(reference, reference) == 1.0
    assert math.isclose(
        task_score_from_ppa(ppa_from_metrics(reference, reference)),
        66.66666666666667,
    )


def test_two_passing_designs_with_different_ppa_get_different_scores(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        runner,
        "run_lint",
        lambda _submission: (
            {"stage": 0, "name": "lint", "status": "pass", "warnings": 0},
            "",
        ),
    )
    monkeypatch.setattr(
        runner,
        "run_sim",
        lambda *_args, **_kwargs: (
            {
                "stage": 1,
                "name": "sim",
                "status": "pass",
                "tests_run": 1,
                "tests_passed": 1,
            },
            "",
            None,
            None,
        ),
    )
    monkeypatch.setattr(
        runner,
        "run_formal",
        lambda *_args: (
            {"stage": 2, "name": "formal", "status": "skip"},
            "",
        ),
    )
    flow_results = iter(
        [
            _passing_ppa_stages(area_um2=100.0, power_mw=1.0),
            _passing_ppa_stages(area_um2=50.0, power_mw=0.5),
        ]
    )
    monkeypatch.setattr(
        runner,
        "run_ppa_flows",
        lambda *_args: (next(flow_results), ""),
    )
    monkeypatch.setattr(
        runner,
        "load_reference_metrics",
        lambda _task_id: PpaMetrics(100.0, 5.0, 1.0, 10.0),
    )
    submission = tmp_path / "submission.sv"
    submission.write_text("module toy; endmodule\n", encoding="utf-8")

    baseline = runner.run_task(
        "toy_task",
        submission,
        tmp_path / "baseline.json",
    )
    optimized = runner.run_task(
        "toy_task",
        submission,
        tmp_path / "optimized.json",
    )

    assert baseline.ppa == 1.0
    assert optimized.ppa > baseline.ppa
    assert optimized.task_score > baseline.task_score
    assert optimized.task_score == 100.0


def test_score_manifest_accepts_a_metrics_consistent_manifest(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(_dimensionally_consistent_manifest()), encoding="utf-8"
    )

    assert math.isclose(score_manifest(manifest_path), 66.66666666666667)


def test_score_manifest_rejects_a_forged_ppa_with_unchanged_metrics(tmp_path):
    """GTFS-007: the canonical-JSON signature is tamper-evident, not
    tamper-preventing -- an attacker can hand-edit ppa/task_score and re-sign over
    the forgery. score_manifest must independently recompute PPA from the stage
    metrics rather than trusting the stored value, so this must be rejected even
    though the signature itself is internally consistent."""

    data = _dimensionally_consistent_manifest()
    data["ppa"] = 1.5
    data["task_score"] = task_score_from_ppa(1.5)
    forged = _resigned(data)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(forged), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match metrics-derived ppa"):
        score_manifest(manifest_path)


def test_score_manifest_rejects_unexecuted_lint_scoring_nonzero(tmp_path):
    """GTFS-006: skip is a legitimate state for formal (stage 2, task.yaml-driven)
    but must never let lint (stage 0) or sim (stage 1) count as if they had run
    and passed -- a manifest that skips a mandatory correctness gate and still
    claims a nonzero score must be rejected."""

    data = _dimensionally_consistent_manifest()
    for stage in data["stages"]:
        if stage["stage"] == 0:
            stage["status"] = "skip"
            stage.pop("warnings", None)
    forged = _resigned(data)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(forged), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match metrics-derived ppa"):
        score_manifest(manifest_path)


def test_passing_sim_stage_with_zero_tests_run_is_rejected():
    """GTFS-006: a 'passing' simulation stage that ran zero tests must be rejected
    at the schema level, not just at the scoring level -- the runner never produces
    this shape, but nothing previously stopped a hand-built manifest from claiming it."""

    data = _dimensionally_consistent_manifest()
    for stage in data["stages"]:
        if stage["stage"] == 1:
            stage["tests_run"] = 0
            stage["tests_passed"] = 0
    with pytest.raises(ValidationError, match="at least one test"):
        ResultManifest.model_validate(_resigned(data))


def _passing_ppa_stages(
    *,
    area_um2: float,
    power_mw: float,
) -> list[dict[str, object]]:
    return [
        {
            "stage": 3,
            "name": "synth",
            "status": "pass",
            "area_um2": area_um2,
            "cell_count": 10,
        },
        {
            "stage": 4,
            "name": "sta",
            "status": "pass",
            "wns_ns": 5.0,
            "tns_ns": 0.0,
            "fmax_mhz": 200.0,
        },
        {
            "stage": 5,
            "name": "power",
            "status": "pass",
            "power_mw": power_mw,
        },
    ]
