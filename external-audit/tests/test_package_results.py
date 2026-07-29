from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

AUDIT_ROOT = Path(__file__).resolve().parents[1]
if str(AUDIT_ROOT) not in sys.path:
    sys.path.insert(0, str(AUDIT_ROOT))

from package_results import package_results, select_sample  # noqa: E402


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _fixture(tmp_path: Path, seed: int = 20260729) -> dict[str, Path | int]:
    ids = ["alpha", "beta", "delta", "gamma", "unsupported"]
    catalog = tmp_path / "catalog.json"
    _write_json(
        catalog,
        {
            "benchmark": "rtllm",
            "designs": [{"design_id": design_id} for design_id in ids],
        },
    )
    final = tmp_path / "final"
    redo = tmp_path / "redo"
    reports = {}
    for index, design_id in enumerate(ids):
        status = "unsupported" if design_id == "unsupported" else "audited"
        total = 0 if status == "unsupported" else 10
        killed = 0 if status == "unsupported" else index + 1
        report = {
            "task_id": design_id,
            "status": status,
            "mutants_total": total,
            "killed": killed,
            "survived": total - killed,
            "indeterminate": 0,
            "kill_rate": 0.0 if total == 0 else 10.0 * killed,
            "notes": "fixture",
        }
        reports[design_id] = report
        _write_json(final / f"{design_id}.json", report)
    _write_json(
        final / "summary.json",
        {"seed": seed, "designs": list(reports.values()), "tasks": list(reports.values())},
    )
    _, sampled = select_sample(reports, seed)
    for design_id in sampled:
        (redo / f"{design_id}.json").parent.mkdir(parents=True, exist_ok=True)
        (redo / f"{design_id}.json").write_bytes(
            (final / f"{design_id}.json").read_bytes()
        )
    cvdp_gap = tmp_path / "gap.json"
    _write_json(
        cvdp_gap,
        {"total_rows": 302, "usable_rows": 0, "withheld_output_rows": 302},
    )
    return {
        "catalog": catalog,
        "cvdp_gap": cvdp_gap,
        "final": final,
        "redo": redo,
        "seed": seed,
    }


def test_package_results_is_deterministic_and_covers_every_design(tmp_path):
    fixture = _fixture(tmp_path)
    metadata = tmp_path / "determinism.json"
    summary = tmp_path / "summary.md"
    kwargs = {
        "final_dir": fixture["final"],
        "redo_dir": fixture["redo"],
        "catalog_path": fixture["catalog"],
        "seed": fixture["seed"],
        "metadata_path": metadata,
        "summary_path": summary,
        "cvdp_gap_path": fixture["cvdp_gap"],
    }

    first = package_results(**kwargs)
    first_metadata = metadata.read_bytes()
    first_summary = summary.read_bytes()
    second = package_results(**kwargs)

    assert first == second
    assert first["eligible_count"] == 4
    assert first["sample_size"] == 1
    assert first["byte_identical"] is True
    assert metadata.read_bytes() == first_metadata
    assert summary.read_bytes() == first_summary
    text = summary.read_text(encoding="utf-8")
    assert [text.count(f"| {design_id} |") for design_id in sorted(
        ["alpha", "beta", "delta", "gamma", "unsupported"]
    )] == [1, 1, 1, 1, 1]


def test_package_results_rejects_sample_mismatch(tmp_path):
    fixture = _fixture(tmp_path)
    reports = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in fixture["final"].glob("*.json")
        if path.name != "summary.json"
    }
    _, sampled = select_sample(reports, fixture["seed"])
    mismatch = fixture["redo"] / f"{sampled[0]}.json"
    mismatch.write_text('{"tampered": true}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="determinism mismatch"):
        package_results(
            final_dir=fixture["final"],
            redo_dir=fixture["redo"],
            catalog_path=fixture["catalog"],
            seed=fixture["seed"],
            metadata_path=tmp_path / "determinism.json",
            summary_path=tmp_path / "summary.md",
            cvdp_gap_path=fixture["cvdp_gap"],
        )
