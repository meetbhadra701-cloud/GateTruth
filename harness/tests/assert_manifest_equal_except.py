"""Compare two manifests after removing explicitly nondeterministic fields."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from harness.schemas.canonical_json import canonical_dumps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("left")
    parser.add_argument("right")
    parser.add_argument("exclude", nargs="*")
    args = parser.parse_args(argv)

    left = _drop_fields(json.loads(Path(args.left).read_text(encoding="utf-8")), set(args.exclude))
    right = _drop_fields(json.loads(Path(args.right).read_text(encoding="utf-8")), set(args.exclude))
    left_text = canonical_dumps(left)
    right_text = canonical_dumps(right)
    if left_text == right_text:
        print("manifests match")
        return 0
    print("manifests differ after exclusions", file=sys.stderr)
    print(f"left:  {left_text}", file=sys.stderr)
    print(f"right: {right_text}", file=sys.stderr)
    return 1


def _drop_fields(value: Any, excluded: set[str]) -> Any:
    if isinstance(value, dict):
        return {key: _drop_fields(item, excluded) for key, item in value.items() if key not in excluded}
    if isinstance(value, list):
        return [_drop_fields(item, excluded) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
