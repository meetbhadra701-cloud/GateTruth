"""Verify that every hash-bound Track B manifest under a results directory
actually reproduces through scripts/reproduce_trackb.py.

harness/trackb.py's run_track_b() has recorded submission_sha256 unconditionally
since P0-3 (2026-08-03); every manifest generated from that point on commits to
its design bytes being independently verifiable. Manifests generated before that
commit never made that promise -- their design source lived only in a
tempfile.TemporaryDirectory() that was torn down before the process returned, so
the bytes are permanently unrecoverable. Those are reported as legacy-unbound,
not failures. A hash-bound manifest (submission_sha256 is not None) that fails to
reproduce -- missing sidecar, tampered sidecar, or a genuine scoring mismatch --
is always a real failure: GTFS-052.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.reproduce_trackb import reproduce_manifest  # noqa: E402

DEFAULT_ROOT = REPO_ROOT / "results" / "evalB" / "official"


@dataclass
class ReproducibilityReport:
    reproduced: list[str] = field(default_factory=list)
    legacy_unbound: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def _iter_official_manifests(root: Path):
    for path in sorted(root.glob("**/*.json")):
        if path.name == "summary.json" or path.name.endswith(".transcript.json"):
            continue
        yield path


def verify_directory(root: Path) -> ReproducibilityReport:
    report = ReproducibilityReport()
    for path in _iter_official_manifests(root):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("submission_sha256") is None:
            report.legacy_unbound.append(str(path))
            continue
        try:
            matched, message = reproduce_manifest(path)
        except (OSError, ValueError) as exc:
            report.failed.append((str(path), str(exc)))
            continue
        if matched:
            report.reproduced.append(str(path))
        else:
            report.failed.append((str(path), message))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify every hash-bound official Track B manifest under a results "
            "directory actually reproduces through scripts/reproduce_trackb.py. "
            "Manifests predating submission_sha256 (2026-08-03) are reported as "
            "legacy-unbound, not failures -- their design bytes were never retained."
        )
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=str(DEFAULT_ROOT),
        help="directory to scan (default: results/evalB/official)",
    )
    args = parser.parse_args(argv)
    report = verify_directory(Path(args.root))

    print(f"reproduced: {len(report.reproduced)}")
    print(
        "legacy-unbound (design bytes never retained, not a failure): "
        f"{len(report.legacy_unbound)}"
    )
    print(f"FAILED: {len(report.failed)}")
    for path, reason in report.failed:
        print(f"  {path}: {reason}", file=sys.stderr)

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
