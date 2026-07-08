"""Manifest score assertion helper used by task tickets."""

from __future__ import annotations

import argparse
import math
import sys

from harness.schemas.manifest import load_manifest
from harness.scoring import task_score_from_ppa


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--reference", action="store_true")
    parser.add_argument("--ppa", type=float)
    parser.add_argument("--task-score", type=float)
    parser.add_argument("--tol", type=float, default=1e-6)
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    expected_ppa = 1.0 if args.reference else args.ppa
    if expected_ppa is None:
        parser.error("provide --reference or --ppa")
    expected_score = task_score_from_ppa(expected_ppa) if args.task_score is None else args.task_score

    errors: list[str] = []
    if args.reference:
        failed = [stage.stage for stage in manifest.stages if stage.stage in {0, 1, 2} and stage.status == "fail"]
        if failed:
            errors.append(f"correctness gate stages failed: {failed}")
    if not math.isclose(manifest.ppa, expected_ppa, abs_tol=args.tol):
        errors.append(f"ppa mismatch: got {manifest.ppa}, expected {expected_ppa}")
    if not math.isclose(manifest.task_score, expected_score, abs_tol=args.tol):
        errors.append(f"task_score mismatch: got {manifest.task_score}, expected {expected_score}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
