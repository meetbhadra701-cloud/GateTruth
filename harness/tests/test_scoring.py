import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness import runner
from harness.schemas.manifest import load_manifest
from harness.scoring import (
    PpaMetrics,
    load_reference_metrics,
    ppa_from_metrics,
    task_score_from_ppa,
)


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
