"""Redact task canaries that leaked into committed result artifacts.

A task canary exists to detect whether a task's spec text has been scraped
into a future model's training data. Publishing raw model completions (RTL
samples, agent transcripts) that happen to echo a spec's canary defeats that
purpose: anyone reading the public repo could read the canary straight out of
a results/ file instead of only from the owning task package, undermining the
signal contamination_check.py exists to protect.

This script does NOT touch the owning tasks/*/task.yaml declarations (those
are the canary's one legitimate location) and does NOT touch any file whose
content is covered by a manifest `signature` field -- it only redacts
"escaped" occurrences as scripts/contamination_check.py itself defines them,
inside result artifacts (generated .sv sources, .transcript.json logs).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.contamination_check import (  # noqa: E402
    CANARY_RE,
    _canary_owners,
    _package_roots,
    _text_files,
)

REDACTION_PLACEHOLDER = "REDACTED-CANARY"


def redact(root: Path, *, apply: bool) -> list[Path]:
    """Return files that contain (or contained, if apply=True) an escaped canary."""

    repo = root.resolve()
    owners = _canary_owners(_package_roots(repo))
    touched: list[Path] = []

    for path in _text_files(repo):
        text = path.read_text(encoding="utf-8")

        def _replace(match) -> str:
            canary = match.group(0).upper()
            owner = owners.get(canary)
            if owner is not None and path.resolve().is_relative_to(owner):
                return match.group(0)
            return REDACTION_PLACEHOLDER

        new_text = CANARY_RE.sub(_replace, text)
        if new_text != text:
            touched.append(path)
            if apply:
                path.write_text(new_text, encoding="utf-8")

    return touched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write redactions in place (default: dry run, list files only)",
    )
    args = parser.parse_args(argv)

    touched = redact(REPO_ROOT, apply=args.apply)
    verb = "redacted" if args.apply else "would redact"
    for path in touched:
        print(f"{verb}: {path.relative_to(REPO_ROOT).as_posix()}")
    print(f"{len(touched)} file(s) {verb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
