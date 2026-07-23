"""Audit or remove orphaned spend reservations from a quiet ledger."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.spend import (  # noqa: E402
    DEFAULT_SPEND_PATH,
    reconcile_spend_reservations,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit orphaned reservations, or remove them while no provider "
            "calls are active."
        )
    )
    parser.add_argument("--path", type=Path, default=DEFAULT_SPEND_PATH)
    parser.add_argument(
        "--write",
        action="store_true",
        help="atomically remove reservations; default is audit-only",
    )
    args = parser.parse_args(argv)
    summary = reconcile_spend_reservations(args.path, write=args.write)
    print(
        json.dumps(
            {"mode": "write" if args.write else "audit", **summary},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
