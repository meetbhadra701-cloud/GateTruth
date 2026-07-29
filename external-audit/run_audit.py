"""Run a deterministic external mutation audit."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

AUDIT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = AUDIT_ROOT.parent
for import_root in (REPO_ROOT, AUDIT_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from auditor import RTLLMIcarusRunner, audit_design  # noqa: E402
from auditor.rtllm import IVERILOG  # noqa: E402
from fetch_vendor import tree_hash  # noqa: E402

DEFAULT_CATALOG = AUDIT_ROOT / "results" / "rtllm" / "sweep_report.json"
DEFAULT_VENDOR = AUDIT_ROOT / "vendor" / "RTLLM"
GIT_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_catalog(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("benchmark") != "rtllm" or not isinstance(raw.get("designs"), list):
        raise ValueError(f"{path}: not an RTLLM compatibility catalog")
    return raw


def _harness_git() -> str:
    for name in ("GATETRUTH_GIT_COMMIT", "SILICONBENCH_GIT_COMMIT", "GITHUB_SHA"):
        value = os.environ.get(name, "").lower()
        if GIT_SHA_RE.fullmatch(value):
            return value
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    value = result.stdout.strip().lower()
    return value if result.returncode == 0 and GIT_SHA_RE.fullmatch(value) else "unavailable"


def _iverilog_version() -> str:
    result = subprocess.run(
        [IVERILOG, "-V"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return "unavailable"


def _tool_versions() -> dict[str, str]:
    return {
        "harness_git": _harness_git(),
        "iverilog": _iverilog_version(),
        "python": platform.python_version(),
    }


def _select_designs(
    requested: str,
    catalog: dict[str, dict[str, Any]],
) -> list[str]:
    if requested == "all":
        return sorted(catalog)
    selected = sorted(set(part.strip() for part in requested.split(",") if part.strip()))
    if not selected:
        raise ValueError("--designs selected no design ids")
    missing = [design_id for design_id in selected if design_id not in catalog]
    if missing:
        raise ValueError(f"unknown RTLLM design ids: {', '.join(missing)}")
    return selected


def _golden_source(
    vendor_root: Path,
    entry: dict[str, Any],
) -> str:
    references = entry.get("reference_sources")
    if not isinstance(references, list) or not references:
        raise ValueError("catalog entry has no reference source")
    candidate = (vendor_root / str(references[0])).resolve()
    try:
        candidate.relative_to(vendor_root)
    except ValueError as exc:
        raise ValueError("reference source escapes vendor root") from exc
    return candidate.read_text(encoding="utf-8")


def run_rtllm_audit(
    *,
    catalog_path: Path,
    vendor_root: Path,
    designs: str,
    seed: int,
    out_dir: Path,
    timeout_s: float,
    retry_timeout_s: float,
) -> dict[str, Any]:
    raw_catalog = _load_catalog(catalog_path)
    expected_vendor_hash = str(raw_catalog["vendor_content_sha256"])
    vendor_root = vendor_root.resolve()
    before_hash = tree_hash(vendor_root)
    if before_hash != expected_vendor_hash:
        raise ValueError(
            "RTLLM vendor hash mismatch: "
            f"expected {expected_vendor_hash}, found {before_hash}"
        )

    entries = {
        str(entry["design_id"]): dict(entry)
        for entry in raw_catalog["designs"]
    }
    selected = _select_designs(designs, entries)
    tool_versions = _tool_versions()
    runner = RTLLMIcarusRunner(vendor_root, entries)
    results: list[dict[str, Any]] = []
    for design_id in selected:
        entry = entries[design_id]
        entry["_golden_source"] = _golden_source(vendor_root, entry)
        entry["_tool_versions"] = tool_versions
        entry["_vendor_commit"] = raw_catalog["vendor_commit"]
        result = audit_design(
            design_id,
            runner,
            seed,
            entry,
            timeout_s=timeout_s,
            retry_timeout_s=retry_timeout_s,
        )
        results.append(result)
        _write_json(out_dir / f"{design_id}.json", result)
        print(
            f"{design_id}: status={result['status']} "
            f"mutants={result['mutants_total']} kill_rate={result['kill_rate']:.4f}"
        )

    after_hash = tree_hash(vendor_root)
    if after_hash != before_hash:
        raise RuntimeError(
            f"RTLLM vendor tree changed during audit: {before_hash} -> {after_hash}"
        )
    status_counts = Counter(result["status"] for result in results)
    summary_designs = [
        {
            key: result[key]
            for key in (
                "task_id",
                "status",
                "mutants_total",
                "killed",
                "survived",
                "indeterminate",
                "kill_rate",
                "notes",
            )
        }
        for result in results
    ]
    summary = {
        "schema_version": "1.0",
        "suite": "rtllm",
        "seed": seed,
        "vendor_commit": raw_catalog["vendor_commit"],
        "vendor_content_sha256": before_hash,
        "tool_versions": tool_versions,
        "designs_requested": len(selected),
        "status_counts": dict(sorted(status_counts.items())),
        "designs": summary_designs,
        "tasks": summary_designs,
    }
    _write_json(out_dir / "summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("rtllm",), required=True)
    parser.add_argument("--designs", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--vendor", type=Path, default=DEFAULT_VENDOR)
    parser.add_argument("--timeout-s", type=float, default=20.0)
    parser.add_argument("--retry-timeout-s", type=float, default=60.0)
    args = parser.parse_args(argv)

    run_rtllm_audit(
        catalog_path=args.catalog,
        vendor_root=args.vendor,
        designs=args.designs,
        seed=args.seed,
        out_dir=args.out,
        timeout_s=args.timeout_s,
        retry_timeout_s=args.retry_timeout_s,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
