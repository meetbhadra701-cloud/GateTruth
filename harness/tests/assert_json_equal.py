"""Compare two JSON documents after canonical serialization."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness.schemas.canonical_json import canonical_dumps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("left")
    parser.add_argument("right")
    args = parser.parse_args(argv)
    left = canonical_dumps(json.loads(Path(args.left).read_text(encoding="utf-8")))
    right = canonical_dumps(json.loads(Path(args.right).read_text(encoding="utf-8")))
    if left == right:
        print("json matches")
        return 0
    print("json differs", file=sys.stderr)
    print(f"left:  {left}", file=sys.stderr)
    print(f"right: {right}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
