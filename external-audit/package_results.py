"""Package raw external-audit JSON into deterministic review artifacts."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

AUDIT_ROOT = Path(__file__).resolve().parent
DEFAULT_CATALOG = AUDIT_ROOT / "results" / "rtllm" / "sweep_report.json"
DEFAULT_FINAL = AUDIT_ROOT / "results" / "rtllm" / "final"
DEFAULT_REDO = AUDIT_ROOT / "results" / "rtllm" / "redo"
DEFAULT_METADATA = AUDIT_ROOT / "results" / "rtllm" / "determinism.json"
DEFAULT_SUMMARY = AUDIT_ROOT / "results" / "summary.md"
DEFAULT_CVDP_GAP = AUDIT_ROOT / "results" / "cvdp" / "gap_report.json"


def _load_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return raw


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _catalog_ids(catalog_path: Path) -> list[str]:
    catalog = _load_json(catalog_path)
    designs = catalog.get("designs")
    if not isinstance(designs, list):
        raise ValueError(f"{catalog_path}: missing designs list")
    ids = sorted(str(item["design_id"]) for item in designs)
    if len(ids) != len(set(ids)):
        raise ValueError(f"{catalog_path}: duplicate design ids")
    return ids


def _load_reports(
    final_dir: Path,
    catalog_path: Path,
) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for design_id in _catalog_ids(catalog_path):
        path = final_dir / f"{design_id}.json"
        if not path.is_file():
            raise ValueError(f"missing final report: {path}")
        report = _load_json(path)
        if report.get("task_id") != design_id:
            raise ValueError(f"{path}: task_id does not match filename")
        if report.get("status") not in {"audited", "unsupported"}:
            raise ValueError(f"{path}: invalid status {report.get('status')!r}")
        reports[design_id] = report
    return reports


def select_sample(
    reports: dict[str, dict[str, Any]],
    seed: int,
) -> tuple[list[str], list[str]]:
    """Return eligible ids and the ticket-defined deterministic 20% sample."""
    eligible = sorted(
        design_id
        for design_id, report in reports.items()
        if report["status"] == "audited"
    )
    if not eligible:
        raise ValueError("no audited designs are eligible for determinism sampling")
    sample_size = max(1, len(eligible) // 5)
    sampled = random.Random(seed).sample(eligible, k=sample_size)
    return eligible, sampled


def _sync_sample(
    source_dir: Path,
    destination_dir: Path,
    sampled: list[str],
) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    expected = {f"{design_id}.json" for design_id in sampled}
    for existing in destination_dir.glob("*.json"):
        if existing.name not in expected:
            existing.unlink()
    for design_id in sampled:
        source = source_dir / f"{design_id}.json"
        if not source.is_file():
            raise ValueError(f"missing sampled report: {source}")
        destination = destination_dir / source.name
        destination.write_bytes(source.read_bytes())


def _markdown_cell(value: Any) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "<br>")
        .replace("\n", "<br>")
        .replace("\r", "<br>")
    )


def _summary_markdown(
    reports: dict[str, dict[str, Any]],
    seed: int,
    sampled: list[str],
    cvdp_gap: dict[str, Any],
) -> str:
    audited = [report for report in reports.values() if report["status"] == "audited"]
    unsupported = [
        report for report in reports.values() if report["status"] == "unsupported"
    ]
    mutants = sum(int(report["mutants_total"]) for report in audited)
    killed = sum(int(report["killed"]) for report in audited)
    survived = sum(int(report["survived"]) for report in audited)
    indeterminate = sum(int(report["indeterminate"]) for report in audited)

    lines = [
        "# External Mutation Audit Summary",
        "",
        "Generated from the committed per-design JSON reports. Counts and kill rates",
        "below are not entered by hand.",
        "",
        "## RTLLM",
        "",
        f"- Seed: `{seed}`",
        f"- Designs reported: {len(reports)}",
        f"- Audited: {len(audited)}",
        f"- Unsupported: {len(unsupported)}",
        f"- Mutants: {mutants}",
        f"- Killed: {killed}",
        f"- Survived: {survived}",
        f"- Indeterminate: {indeterminate}",
        f"- Aggregate kill fraction: {killed}/{mutants}",
        f"- Determinism sample ({len(sampled)}): "
        + ", ".join(f"`{design_id}`" for design_id in sampled),
        "- Determinism result: byte-identical per-design JSON",
        "",
        "### Per-design results",
        "",
        "| Design | Status | Mutants | Killed | Survived | Indeterminate | Kill rate (%) | Notes |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for design_id in sorted(reports):
        report = reports[design_id]
        values = (
            design_id,
            report["status"],
            report["mutants_total"],
            report["killed"],
            report["survived"],
            report["indeterminate"],
            report["kill_rate"],
            report.get("notes", ""),
        )
        lines.append("| " + " | ".join(_markdown_cell(value) for value in values) + " |")

    lines.extend(
        [
            "",
            "## CVDP",
            "",
            f"- Rows inspected: {cvdp_gap['total_rows']}",
            f"- Rows with usable golden RTL: {cvdp_gap['usable_rows']}",
            f"- Rows with withheld outputs: {cvdp_gap['withheld_output_rows']}",
            "- Result: no mutation-kill audit; see `results/cvdp/FINDING.md`.",
            "",
        ]
    )
    return "\n".join(lines)


def package_results(
    *,
    final_dir: Path,
    redo_dir: Path,
    catalog_path: Path,
    seed: int,
    metadata_path: Path,
    summary_path: Path,
    cvdp_gap_path: Path,
) -> dict[str, Any]:
    reports = _load_reports(final_dir, catalog_path)
    summary = _load_json(final_dir / "summary.json")
    if summary.get("seed") != seed:
        raise ValueError(
            f"{final_dir / 'summary.json'}: seed {summary.get('seed')} != {seed}"
        )

    eligible, sampled = select_sample(reports, seed)
    mismatches: list[str] = []
    for design_id in sampled:
        first = final_dir / f"{design_id}.json"
        second = redo_dir / f"{design_id}.json"
        if not second.is_file() or first.read_bytes() != second.read_bytes():
            mismatches.append(design_id)
    if mismatches:
        raise ValueError(
            "determinism mismatch for sampled designs: " + ", ".join(mismatches)
        )

    _sync_sample(final_dir, final_dir / "determinism-sample", sampled)
    _sync_sample(redo_dir, redo_dir / "determinism-sample", sampled)
    metadata = {
        "schema_version": "1.0",
        "seed": seed,
        "eligible_count": len(eligible),
        "sample_size": len(sampled),
        "sampled_ids": sampled,
        "byte_identical": True,
    }
    _write_json(metadata_path, metadata)
    cvdp_gap = _load_json(cvdp_gap_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        _summary_markdown(reports, seed, sampled, cvdp_gap),
        encoding="utf-8",
        newline="\n",
    )
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final-dir", type=Path, default=DEFAULT_FINAL)
    parser.add_argument("--redo-dir", type=Path, default=DEFAULT_REDO)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--cvdp-gap", type=Path, default=DEFAULT_CVDP_GAP)
    args = parser.parse_args(argv)

    metadata = package_results(
        final_dir=args.final_dir,
        redo_dir=args.redo_dir,
        catalog_path=args.catalog,
        seed=args.seed,
        metadata_path=args.metadata,
        summary_path=args.summary,
        cvdp_gap_path=args.cvdp_gap,
    )
    print("sampled_ids=" + ",".join(metadata["sampled_ids"]))
    print(
        "determinism=byte-identical "
        f"files={metadata['sample_size']} eligible={metadata['eligible_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
