"""Regression tests for the hardened RTLLM per-design audit appendix generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper.data.generate_audit_appendix import (
    AUDIT_DIR,
    EXPECTED_DESIGN_COUNT,
    EXPECTED_GENERATION_FLAG,
    AuditAppendixDataError,
    load_designs,
    render,
)

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
    generation_flag: str | None = EXPECTED_GENERATION_FLAG,
    include_generation_flag: bool = True,
) -> dict:
    kill_rate = 0.0 if mutants_total == 0 else round(100.0 * killed / mutants_total, 4)
    data = {
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
    if include_generation_flag:
        data["generation_flag"] = generation_flag
    return data


def _write_fixture(
    root: Path,
    *,
    designs: list[dict],
    catalog_ids: list[str] | None = None,
    harness_git: str = "b" * 40,
    summary_generation_flag: str | None = EXPECTED_GENERATION_FLAG,
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
        "generation_flag": summary_generation_flag,
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


def test_wrong_generation_flag_is_refused(tmp_path: Path) -> None:
    """GTFS-040: a design whose actual recorded generation_flag is -g2001 must be
    refused, even if its free-text notes still (wrongly) describe -g2012 -- the notes
    are not the source of truth this validator checks anymore."""

    bad = _valid_designs()
    bad[0]["generation_flag"] = "-g2001"
    bad[0]["notes"] = "baseline passed under Icarus Verilog-2012"
    audit_dir, catalog_path = _write_fixture(tmp_path, designs=bad)

    with pytest.raises(AuditAppendixDataError, match="generation_flag='-g2001'"):
        load_designs(audit_dir, catalog_path, expected_count=3)


def test_all_designs_missing_generation_flag_is_a_legitimate_legacy_shape(
    tmp_path: Path,
) -> None:
    """GTFS-040: a whole run that entirely predates the generation_flag field --
    exactly the shape of the real committed evidence today -- is a legitimate,
    honestly-unverified legacy state, not an error. The condition claim rests on the
    same (weaker) notes-based provenance it always did; this fix's job is to stop a
    *future* run from silently drifting, not to retroactively invalidate a run that
    never had the chance to record this field at all."""

    bad = [
        _design(task_id, include_generation_flag=False) for task_id in DESIGN_IDS
    ]
    audit_dir, catalog_path = _write_fixture(
        tmp_path, designs=bad, summary_generation_flag=None
    )
    # summary_generation_flag=None still writes the *key* with value None in
    # _write_fixture()'s dict, which is presence=True -- pop it to match the real
    # legacy shape (key entirely absent), matching what a pre-GTFS-040 run.json
    # actually looks like.
    summary_path = audit_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    del summary["generation_flag"]
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    audited, unsupported = load_designs(audit_dir, catalog_path, expected_count=3)

    assert len(audited) == 3
    assert unsupported == []


def test_mixed_generation_flag_presence_across_designs_is_refused(
    tmp_path: Path,
) -> None:
    """A run where some per-design files have generation_flag and others don't is
    not a legitimate legacy shape -- it looks like a partial regeneration or other
    data-integrity problem, and must be refused, not silently treated as legacy."""

    mixed = _valid_designs()
    mixed[0] = _design(mixed[0]["task_id"], include_generation_flag=False)
    audit_dir, catalog_path = _write_fixture(tmp_path, designs=mixed)

    with pytest.raises(AuditAppendixDataError, match="mixed-provenance"):
        load_designs(audit_dir, catalog_path, expected_count=3)


def test_summary_generation_flag_mismatch_is_refused(tmp_path: Path) -> None:
    audit_dir, catalog_path = _write_fixture(
        tmp_path, designs=_valid_designs(), summary_generation_flag="-g2001"
    )

    with pytest.raises(AuditAppendixDataError, match="generation_flag"):
        load_designs(audit_dir, catalog_path, expected_count=3)


def test_summary_generation_flag_presence_disagrees_with_designs_is_refused(
    tmp_path: Path,
) -> None:
    """The designs all have generation_flag but summary.json entirely lacks the key
    (rather than merely having a wrong value) -- also refused, since a real run
    always writes the field to both or to neither."""

    audit_dir, catalog_path = _write_fixture(tmp_path, designs=_valid_designs())
    summary_path = audit_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    del summary["generation_flag"]
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    with pytest.raises(AuditAppendixDataError, match="generation_flag presence disagrees"):
        load_designs(audit_dir, catalog_path, expected_count=3)


def test_real_committed_audit_evidence_predates_generation_flag_but_still_loads() -> None:
    """Locks in the real, current state of results/external-audit/rtllm/final-g2012/:
    it predates GTFS-040 entirely (generation_flag absent from every per-design file
    and from summary.json), which is the legitimate legacy shape -- accepted, not
    refused, since a run that never had the chance to record this field is no worse
    off than it always was. If this test starts failing because the real evidence
    now carries generation_flag on some but not all files, that indicates a genuine
    data-integrity problem worth investigating, not a fixture to relax."""

    if not AUDIT_DIR.is_dir():
        pytest.skip("real external-audit results not present on this machine")

    audited, unsupported = load_designs()

    assert len(audited) + len(unsupported) == EXPECTED_DESIGN_COUNT


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
