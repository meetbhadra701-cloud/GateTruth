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
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.atomic_write import atomic_write_text  # noqa: E402
from scripts.contamination_check import (  # noqa: E402
    CANARY_RE,
    _canary_owners,
    _package_roots,
    _text_files,
)

REDACTION_PLACEHOLDER = "REDACTED-CANARY"


class SignedEvidenceCanaryError(RuntimeError):
    """An escaped canary was found inside a signed JSON artifact.

    Rewriting any byte of a signed object invalidates its `signature` field, so this
    tool must never do that silently -- it has no way to re-sign the object, and a
    corrupted-but-unflagged signature is worse than an untouched leak. This must
    surface as a loud failure so a human decides how to handle the contamination.
    """

    def __init__(self, paths: list[Path]) -> None:
        self.paths = paths
        joined = ", ".join(p.as_posix() for p in paths)
        super().__init__(
            f"escaped canary found inside signed JSON artifact(s), cannot redact "
            f"automatically without invalidating their signature: {joined}"
        )


def _is_signed_json(path: Path, text: str) -> bool:
    if path.suffix.lower() != ".json":
        return False
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and "signature" in parsed


def _escaped_matches(text: str, path: Path, owners: dict[str, Path]) -> list[str]:
    escaped = []
    for match in CANARY_RE.finditer(text):
        canary = match.group(0).upper()
        owner = owners.get(canary)
        if owner is not None and path.resolve().is_relative_to(owner):
            continue
        escaped.append(match.group(0))
    return escaped


def redact(root: Path, *, apply: bool) -> list[Path]:
    """Return files that contain (or contained, if apply=True) an escaped canary.

    Raises SignedEvidenceCanaryError, touching nothing, if an escaped canary is found
    inside any signed JSON artifact -- see that class's docstring for why this can
    never be an automatic rewrite.
    """

    repo = root.resolve()
    owners = _canary_owners(_package_roots(repo))
    touched: list[Path] = []
    protected: list[Path] = []

    for path in _text_files(repo):
        text = path.read_text(encoding="utf-8")

        if _is_signed_json(path, text):
            if _escaped_matches(text, path, owners):
                protected.append(path)
            continue

        def _replace(match, path=path) -> str:
            canary = match.group(0).upper()
            owner = owners.get(canary)
            if owner is not None and path.resolve().is_relative_to(owner):
                return match.group(0)
            return REDACTION_PLACEHOLDER

        new_text = CANARY_RE.sub(_replace, text)
        if new_text != text:
            touched.append(path)
            if apply:
                atomic_write_text(path, new_text)

    if protected:
        raise SignedEvidenceCanaryError(protected)

    return touched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write redactions in place (default: dry run, list files only)",
    )
    args = parser.parse_args(argv)

    try:
        touched = redact(REPO_ROOT, apply=args.apply)
    except SignedEvidenceCanaryError as exc:
        print(f"redact_canaries: FAIL - {exc}", file=sys.stderr)
        return 1

    verb = "redacted" if args.apply else "would redact"
    for path in touched:
        print(f"{verb}: {path.relative_to(REPO_ROOT).as_posix()}")
    print(f"{len(touched)} file(s) {verb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
