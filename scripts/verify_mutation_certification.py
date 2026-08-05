"""Check whether a signed mutation-certification summary still matches the tree it audited.

GTFS-030: does NOT re-run mutation testing -- the full sequential campaign is expensive
(the paper's own "exclusively sequential" discipline is what makes certification
trustworthy, and also what makes it slow). Instead this recomputes the same cheap local
hashes scripts/certify_mutation.py already binds into every task row --
task_package_sha256, reference_rtl_sha256, public_testbench_sha256 -- and reports which
tasks (if any) have drifted since the certification was produced, so a later revision to
a task's RTL or testbench is caught rather than silently assumed still covered by stale
evidence. A summary that predates schema_version 4 (GTFS-030) carries none of these
hashes at all and is reported as unauditable rather than silently passed or crashed on.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pydantic import ValidationError  # noqa: E402

from harness.runner import resolve_task  # noqa: E402
from harness.schemas.mutation_certification import (  # noqa: E402
    load_mutation_certification_summary,
)
from harness.tree_hash import tree_hash  # noqa: E402

DEFAULT_SUMMARY = REPO_ROOT / "results" / "mutation" / "certification" / "summary.json"


class CertificationCheckError(ValueError):
    """Raised when a committed certification summary cannot be checked at all."""


@dataclass
class StalenessReport:
    fresh: list[str] = field(default_factory=list)
    stale: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.stale


def check_summary(path: Path) -> StalenessReport:
    try:
        summary = load_mutation_certification_summary(path)
    except OSError as exc:
        raise CertificationCheckError(f"cannot read {path}: {exc}") from exc
    except ValidationError as exc:
        raise CertificationCheckError(
            f"{path} is not a validly signed schema_version=4 certification summary "
            f"(legacy summaries predating GTFS-030 carry no provenance hashes and "
            f"cannot be staleness-checked): {exc.error_count()} schema violation(s), "
            f"first: {exc.errors()[0]['loc']} -- {exc.errors()[0]['msg']}"
        ) from exc

    report = StalenessReport()
    for task_id, entry in sorted(summary.tasks.items()):
        try:
            task = resolve_task(task_id)
            current_task_package = tree_hash(task.root)
            current_reference = hashlib.sha256(
                (task.root / "ref" / "ref.sv").read_bytes()
            ).hexdigest()
            current_public_tb = tree_hash(task.root / "tb")
        except OSError as exc:
            report.stale.append((task_id, f"task package unreadable: {exc}"))
            continue
        drift = []
        if current_task_package != entry.task_package_sha256:
            drift.append("task package")
        if current_reference != entry.reference_rtl_sha256:
            drift.append("reference RTL")
        if current_public_tb != entry.public_testbench_sha256:
            drift.append("public testbench")
        if drift:
            report.stale.append((task_id, f"{', '.join(drift)} changed since certification"))
        else:
            report.fresh.append(task_id)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", nargs="?", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args(argv)

    try:
        report = check_summary(args.summary)
    except CertificationCheckError as exc:
        print(f"certification check refused: {exc}", file=sys.stderr)
        return 2

    print(f"fresh: {len(report.fresh)}")
    print(f"STALE: {len(report.stale)}")
    for task_id, reason in report.stale:
        print(f"  {task_id}: {reason}", file=sys.stderr)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
