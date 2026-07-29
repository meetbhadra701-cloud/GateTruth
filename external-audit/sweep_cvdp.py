"""Measure whether the pinned public CVDP split contains usable golden RTL."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable

from fetch_vendor import AUDIT_ROOT, LOCK_PATH, tree_hash

DATASET_FILENAME = "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl"
EXPECTED_ROWS = 302
RTL_SUFFIXES = (".v", ".sv", ".vh", ".svh")
MODULE_RE = re.compile(r"\bmodule\s+[A-Za-z_][A-Za-z0-9_$]*")
NOTICE_ID_RE = re.compile(r"^#\s+(cvdp_[A-Za-z0-9_.-]+)\s*$", re.MULTILINE)


def _load_lock() -> dict[str, dict[str, Any]]:
    raw = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    return dict(raw["vendors"])


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: row is not an object")
            rows.append(row)
    return rows


def _nonempty_output_sources(output: object) -> list[str]:
    if not isinstance(output, dict):
        return []
    candidates: list[str] = []
    response = output.get("response")
    if isinstance(response, str) and response.strip() and MODULE_RE.search(response):
        candidates.append("response")
    context = output.get("context")
    if isinstance(context, dict):
        for name, value in sorted(context.items()):
            if (
                isinstance(name, str)
                and name.lower().endswith(RTL_SUFFIXES)
                and isinstance(value, str)
                and value.strip()
            ):
                candidates.append(name)
    return candidates


def _public_example_solutions(harness: Path) -> dict[str, list[str]]:
    solutions: dict[str, list[str]] = {}
    example_root = harness / "example_dataset"
    for path in sorted(example_root.glob("*nonagentic*with_solutions.jsonl")):
        for row in _load_jsonl(path):
            row_id = row.get("id")
            if not isinstance(row_id, str):
                continue
            sources = _nonempty_output_sources(row.get("output"))
            if sources:
                solutions[row_id] = sources
    return solutions


def _first_category(categories: object) -> str:
    if isinstance(categories, list) and categories and isinstance(categories[0], str):
        return categories[0]
    return "uncategorized"


def _row_report(
    row: dict[str, Any],
    *,
    oss_ids: set[str],
    example_solutions: dict[str, list[str]],
) -> dict[str, Any]:
    row_id = row.get("id")
    if not isinstance(row_id, str) or not row_id:
        raise ValueError("CVDP row has no string id")
    output_sources = _nonempty_output_sources(row.get("output"))
    example_sources = example_solutions.get(row_id, [])
    oss_origin_declared = any(
        row_id == oss_id or row_id.startswith(f"{oss_id}_")
        for oss_id in oss_ids
    )
    if output_sources:
        golden_source: str | None = "output-field"
    elif example_sources:
        golden_source = "oss-repo"
    else:
        golden_source = None
    return {
        "category": _first_category(row.get("categories")),
        "golden_source": golden_source,
        "has_golden": golden_source is not None,
        "oss_origin_declared": oss_origin_declared,
        "row_id": row_id,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _verify_hashes(
    roots: Iterable[tuple[str, Path, dict[str, Any]]],
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for key, root, record in roots:
        actual = tree_hash(root)
        expected = str(record["content_sha256"])
        if actual != expected:
            raise ValueError(
                f"{key} vendor hash mismatch: expected {expected}, found {actual}"
            )
        hashes[key] = actual
    return hashes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=AUDIT_ROOT / "vendor" / "cvdp-benchmark-dataset",
    )
    parser.add_argument(
        "--harness",
        type=Path,
        default=AUDIT_ROOT / "vendor" / "cvdp_benchmark",
    )
    parser.add_argument("--out", type=Path, default=AUDIT_ROOT / "results" / "cvdp")
    args = parser.parse_args(argv)

    dataset = args.dataset.resolve()
    harness = args.harness.resolve()
    lock = _load_lock()
    roots = [
        ("cvdp-dataset", dataset, lock["cvdp-dataset"]),
        ("cvdp-harness", harness, lock["cvdp-harness"]),
    ]
    before_hashes = _verify_hashes(roots)

    dataset_file = dataset / DATASET_FILENAME
    rows = _load_jsonl(dataset_file)
    if len(rows) != EXPECTED_ROWS:
        raise ValueError(f"expected {EXPECTED_ROWS} CVDP rows, found {len(rows)}")
    notice = (dataset / "NOTICE").read_text(encoding="utf-8", errors="replace")
    oss_ids = set(NOTICE_ID_RE.findall(notice))
    example_solutions = _public_example_solutions(harness)
    row_reports = sorted(
        (
            _row_report(
                row,
                oss_ids=oss_ids,
                example_solutions=example_solutions,
            )
            for row in rows
        ),
        key=lambda item: item["row_id"],
    )
    after_hashes = _verify_hashes(roots)
    if after_hashes != before_hashes:
        raise RuntimeError("CVDP vendor tree changed during sweep")

    usable_rows = sum(bool(row["has_golden"]) for row in row_reports)
    report = {
        "dataset_content_sha256": before_hashes["cvdp-dataset"],
        "dataset_file": DATASET_FILENAME,
        "dataset_revision": lock["cvdp-dataset"]["revision"],
        "harness_commit": lock["cvdp-harness"]["revision"],
        "harness_content_sha256": before_hashes["cvdp-harness"],
        "oss_origin_rows": sum(bool(row["oss_origin_declared"]) for row in row_reports),
        "rows": row_reports,
        "schema_version": "1.0",
        "total_rows": len(row_reports),
        "usable_rows": usable_rows,
        "withheld_output_rows": sum(not bool(row["has_golden"]) for row in row_reports),
        "withheld_statement_confirmed": (
            "excluded the reference solutions" in
            (harness / "README.md").read_text(encoding="utf-8", errors="replace")
        ),
    }
    write_json(args.out / "gap_report.json", report)
    print(
        f"CVDP golden gap: usable_rows={usable_rows}/{len(row_reports)} "
        f"oss_origins_declared={report['oss_origin_rows']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
