"""Regression tests for the hardened RTLLM per-design audit appendix generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper.data.generate_audit_appendix import AuditAppendixDataError, load_designs, render

DESIGN_IDS = ["alpha", "beta", "gamma"]


def _design(
    task_id: str,
    *,
    status: str = "audited",
    mutants_total: int = 4,
    killed: int = 3,
    survived: int = 1,
    indeterminate: int = 0,
    schema_version: str = "1.0",
    seed: int = 20260729,
    vendor_commit: str = "a" * 40,
    notes: str = "baseline passed under Icarus Verilog-2012",
) -> dict:
    kill_rate = 0.0 if mutants_total == 0 else round(100.0 * killed / mutants_total, 4)
    return {
        "task_id": task_id,
        "status": status,
        "schema_version": schema_version,
        "seed": seed,
        "vendor_commit": vendor_commit,
        "mutants_total": mutants_total,
        "killed": killed,
        "survived": survived,
        "indeterminate": indeterminate,
        "kill_rate": kill_rate,
        "notes": notes,
    }


def _write_fixture(
    root: Path,
    *,
    designs: list[dict],
    catalog_ids: list[str] | None = None,
    harness_git: str = "b" * 40,
) -> tuple[Path, Path]:
    audit_dir = root / "final-g2012"
    audit_dir.mkdir(parents=True)
    for d in designs:
        (audit_dir / f"{d['task_id']}.json").write_text(
            json.dumps(d, indent=2), encoding="utf-8"
        )

    audited = [d for d in designs if d["status"] == "audited"]
    unsupported = [d for d in designs if d["status"] == "unsupported"]
    summary = {
        "schema_version": "1.0",
        "seed": 20260729,
        "vendor_commit": "a" * 40,
        "designs_requested": len(catalog_ids or DESIGN_IDS),
        "status_counts": {"audited": len(audited), "unsupported": len(unsupported)},
        "tool_versions": {"harness_git": harness_git},
    }
    (audit_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    catalog_path = root / "sweep_report.json"
    catalog = {
        "benchmark": "rtllm",
        "designs": [{"design_id": task_id} for task_id in (catalog_ids or DESIGN_IDS)],
    }
    catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    return audit_dir, catalog_path


def _valid_designs() -> list[dict]:
    return [_design(task_id) for task_id in DESIGN_IDS]


def test_valid_fixture_renders_pooled_totals(tmp_path: Path) -> None:
    audit_dir, catalog_path = _write_fixture(tmp_path, designs=_valid_designs())

    audited, unsupported = load_designs(audit_dir, catalog_path, expected_count=3)

    assert len(audited) == 3
    assert unsupported == []
    tex = render(audit_dir, catalog_path, expected_count=3)
    assert r"\textbf{Pooled (3 audited)}" in tex
    assert r"\textbf{12}" in tex  # total mutants = 3 designs * 4 mutants_total each
    assert r"\textbf{9}" in tex  # total killed = 3 designs * 3 killed each
    assert r"\textbf{75.0\%}" in tex  # 9 killed / 12 total


def test_count_invariant_violation_is_refused(tmp_path: Path) -> None:
    bad = _valid_designs()
    bad[0]["survived"] = 99  # killed+survived+indeterminate now != mutants_total
    audit_dir, catalog_path = _write_fixture(tmp_path, designs=bad)

    with pytest.raises(AuditAppendixDataError, match="!= mutants_total"):
        load_designs(audit_dir, catalog_path, expected_count=3)


def test_kill_rate_arithmetic_violation_is_refused(tmp_path: Path) -> None:
    bad = _valid_designs()
    bad[0]["kill_rate"] = 12.5  # does not match 3/4 = 75.0
    audit_dir, catalog_path = _write_fixture(tmp_path, designs=bad)

    with pytest.raises(AuditAppendixDataError, match="kill_rate"):
        load_designs(audit_dir, catalog_path, expected_count=3)


def test_missing_design_is_refused(tmp_path: Path) -> None:
    designs = [_design(task_id) for task_id in DESIGN_IDS[:2]]
    audit_dir, catalog_path = _write_fixture(tmp_path, designs=designs)

    with pytest.raises(AuditAppendixDataError, match="design set mismatch"):
        load_designs(audit_dir, catalog_path, expected_count=3)


def test_duplicate_design_result_is_refused(tmp_path: Path) -> None:
    audit_dir, catalog_path = _write_fixture(tmp_path, designs=_valid_designs())
    # a second file for the same design_id, at a different filename
    (audit_dir / "alpha_dup.json").write_text(
        json.dumps(_design("alpha"), indent=2), encoding="utf-8"
    )

    with pytest.raises(AuditAppendixDataError, match="duplicate design result"):
        load_designs(audit_dir, catalog_path, expected_count=3)


def test_inconsistent_seed_across_designs_is_refused(tmp_path: Path) -> None:
    bad = _valid_designs()
    bad[0]["seed"] = 1
    audit_dir, catalog_path = _write_fixture(tmp_path, designs=bad)

    with pytest.raises(AuditAppendixDataError, match="seed"):
        load_designs(audit_dir, catalog_path, expected_count=3)


def test_inconsistent_vendor_commit_across_designs_is_refused(tmp_path: Path) -> None:
    bad = _valid_designs()
    bad[0]["vendor_commit"] = "c" * 40
    audit_dir, catalog_path = _write_fixture(tmp_path, designs=bad)

    with pytest.raises(AuditAppendixDataError, match="vendor_commit"):
        load_designs(audit_dir, catalog_path, expected_count=3)


def test_verilog_2001_note_on_a_g2012_run_is_refused(tmp_path: Path) -> None:
    bad = _valid_designs()
    bad[0]["notes"] = "baseline passed under Icarus Verilog-2001"
    audit_dir, catalog_path = _write_fixture(tmp_path, designs=bad)

    with pytest.raises(AuditAppendixDataError, match="Verilog-2001 condition"):
        load_designs(audit_dir, catalog_path, expected_count=3)


def test_summary_status_counts_mismatch_is_refused(tmp_path: Path) -> None:
    audit_dir, catalog_path = _write_fixture(tmp_path, designs=_valid_designs())
    summary_path = audit_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["status_counts"] = {"audited": 1, "unsupported": 2}
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    with pytest.raises(AuditAppendixDataError, match="status_counts"):
        load_designs(audit_dir, catalog_path, expected_count=3)


def test_unavailable_harness_git_is_refused(tmp_path: Path) -> None:
    audit_dir, catalog_path = _write_fixture(
        tmp_path, designs=_valid_designs(), harness_git="unavailable"
    )

    with pytest.raises(AuditAppendixDataError, match="harness_git is unavailable"):
        load_designs(audit_dir, catalog_path, expected_count=3)


def test_unsupported_designs_render_as_dashes(tmp_path: Path) -> None:
    designs = [
        _design("alpha"),
        _design("beta"),
        _design(
            "gamma",
            status="unsupported",
            mutants_total=0,
            killed=0,
            survived=0,
            indeterminate=0,
            notes="Icarus compile failed (exit 1) under -g2012",
        ),
    ]
    audit_dir, catalog_path = _write_fixture(tmp_path, designs=designs)

    tex = render(audit_dir, catalog_path, expected_count=3)
    assert r"\texttt{gamma} & --- & --- & --- & --- & --- & \texttt{unsupported}" in tex
    assert r"\textbf{Pooled (2 audited)}" in tex
