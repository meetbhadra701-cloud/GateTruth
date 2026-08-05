"""Crash-safe text writes shared by every result-manifest writer.

A plain path.write_text(...) killed mid-write (OOM, SIGKILL, a container hitting its
--memory cap) leaves a truncated file at the final path -- for manifests that are later
json.load()'d for official scoring, that is a corrupted result, not just a missing one.
Write to a sibling temp file in the same directory, fsync it, then atomically rename it
into place, so the final path always holds either the previous complete content or the
new complete content, never a partial write. Extracted from harness/spend.py's
_save_spend_unlocked, which already used this pattern for the spend ledger.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        # mkstemp creates the temp file at mode 0600 (Python's own, deliberately
        # restrictive default for temp files), and os.replace() preserves that mode
        # across the rename -- so without this, every file this module ever writes
        # is owner-only-readable. Harmless when the writer and later reader are the
        # same process/user, but a real, silent failure the moment they are not: a
        # GitHub Actions runner (a different uid than the container that wrote a
        # result file) hit exactly this uploading nightly.yml's results/nightly/*.json
        # as a workflow artifact -- confirmed directly against the real failed run
        # (EACCES: permission denied) before writing this fix. Restore the ordinary
        # world-readable mode a plain path.write_text() would have produced.
        os.chmod(temp_path, 0o644)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Byte-exact counterpart to atomic_write_text.

    Text mode's universal-newline handling silently rewrites CRLF to LF on read,
    which breaks any later byte-for-byte hash comparison against the original file
    (e.g. a submission's recorded sha256). Callers persisting a copy of a file whose
    bytes must match a content hash need this, not atomic_write_text.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.chmod(temp_path, 0o644)  # see atomic_write_text's comment on this line
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
