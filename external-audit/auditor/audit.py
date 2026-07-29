"""Sequential, benchmark-neutral mutation-audit policy."""

from __future__ import annotations

import hashlib
import random
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from harness.mutators import generate_mutants

from .protocol import TbResult, TestbenchRunner, Verdict

SCHEMA_VERSION = "1.0"


def _source_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _base_report(
    design_id: str,
    runner: TestbenchRunner,
    seed: int,
    catalog_entry: dict[str, Any],
    golden_source: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "suite": runner.suite,
        "task_id": design_id,
        "seed": seed,
        "vendor_commit": catalog_entry["_vendor_commit"],
        "source_sha256": catalog_entry.get("reference_sha256")
        or _source_hash(golden_source),
        "testbench_sha256": catalog_entry.get("testbench_sha256"),
        "tool_versions": catalog_entry["_tool_versions"],
    }


def _unsupported_report(
    base: dict[str, Any],
    baseline: TbResult,
    catalog_entry: dict[str, Any],
) -> dict[str, Any]:
    return {
        **base,
        "status": "unsupported",
        "notes": catalog_entry.get("notes") or "unmodified golden did not pass",
        "baseline": {
            "verdict": baseline.verdict.value,
            "killed_by": baseline.killed_by,
        },
        "mutants_total": 0,
        "operator_counts": {},
        "killed": 0,
        "survived": 0,
        "indeterminate": 0,
        "kill_rate": 0.0,
        "per_mutant": [],
    }


def _mutant_verdict(
    result: TbResult,
    retry: TbResult | None,
) -> tuple[str, str | None]:
    effective = retry or result
    if effective.verdict == Verdict.PASS:
        return "survived", None
    if effective.verdict == Verdict.FAIL:
        return "killed", effective.killed_by or "tb"
    if effective.verdict == Verdict.TIMEOUT:
        return "indeterminate", "tb-timeout"
    return "indeterminate", None


def audit_design(
    design_id: str,
    runner: TestbenchRunner,
    seed: int,
    catalog_entry: dict[str, Any],
    *,
    timeout_s: float = 20.0,
    retry_timeout_s: float = 60.0,
) -> dict[str, Any]:
    """Audit one design, baseline first, with deterministic sequential execution."""
    golden_source = catalog_entry.get("_golden_source")
    if not isinstance(golden_source, str):
        raise ValueError(f"{design_id}: catalog entry has no loaded golden source")
    base = _base_report(design_id, runner, seed, catalog_entry, golden_source)

    with tempfile.TemporaryDirectory(
        prefix=f"gatetruth-audit-{runner.suite}-{design_id}-"
    ) as temp:
        audit_root = Path(temp)
        baseline = runner.run(
            design_id,
            golden_source,
            audit_root / "baseline",
            timeout_s=timeout_s,
        )
        if baseline.verdict != Verdict.PASS:
            return _unsupported_report(base, baseline, catalog_entry)

        mutants = generate_mutants(
            f"{runner.suite}_{design_id}",
            golden_source,
            include_task_specs=False,
        )
        rng = random.Random(seed)
        rng.shuffle(mutants)

        per_mutant: list[dict[str, Any]] = []
        for mutant in mutants:
            result = runner.run(
                design_id,
                mutant.source,
                audit_root / mutant.id,
                timeout_s=timeout_s,
            )
            retry = None
            if result.verdict == Verdict.TIMEOUT:
                retry = runner.run(
                    design_id,
                    mutant.source,
                    audit_root / f"{mutant.id}-retry",
                    timeout_s=retry_timeout_s,
                )
            verdict, killed_by = _mutant_verdict(result, retry)
            per_mutant.append(
                {
                    "id": mutant.id,
                    "operator": mutant.operator,
                    "description": mutant.description,
                    "verdict": verdict,
                    "killed_by": killed_by,
                }
            )

    verdict_counts = Counter(item["verdict"] for item in per_mutant)
    operator_counts = Counter(item["operator"] for item in per_mutant)
    total = len(per_mutant)
    killed = verdict_counts["killed"]
    kill_rate = 0.0 if total == 0 else 100.0 * killed / total
    return {
        **base,
        "status": "audited",
        "notes": catalog_entry.get("notes") or "",
        "baseline": {
            "verdict": baseline.verdict.value,
            "killed_by": baseline.killed_by,
        },
        "mutants_total": total,
        "operator_counts": dict(sorted(operator_counts.items())),
        "killed": killed,
        "survived": verdict_counts["survived"],
        "indeterminate": verdict_counts["indeterminate"],
        "kill_rate": round(kill_rate, 4),
        "per_mutant": per_mutant,
    }
