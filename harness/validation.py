"""Fail-closed validation for untrusted SystemVerilog sources."""

from __future__ import annotations

import re
from pathlib import Path

MAX_SOURCE_BYTES = 256 * 1024
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


class SubmissionValidationError(ValueError):
    """Raised before any tool sees a malformed or oversized source."""


def validate_source_file(
    path: str | Path,
    *,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> Path:
    source = Path(path)
    if not source.is_file():
        raise SubmissionValidationError(f"submission is not a file: {source}")
    size = source.stat().st_size
    if size > max_bytes:
        raise SubmissionValidationError(
            f"source exceeds {max_bytes} byte limit: {size} bytes"
        )
    return source


def validate_source_text(
    source: str,
    *,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> None:
    size = len(source.encode("utf-8"))
    if size > max_bytes:
        raise SubmissionValidationError(
            f"source exceeds {max_bytes} byte limit: {size} bytes"
        )


def validate_sv_filename(path: str | Path) -> None:
    source = Path(path)
    if source.suffix != ".sv" or IDENTIFIER_RE.fullmatch(source.stem) is None:
        raise SubmissionValidationError(
            f"invalid SystemVerilog filename: {source.name!r}"
        )


def validate_identifier(value: str, *, label: str) -> None:
    if IDENTIFIER_RE.fullmatch(value) is None:
        raise SubmissionValidationError(f"invalid {label}: {value!r}")


def validate_module_declarations(source: Path, *, expected_top: str) -> None:
    validate_identifier(expected_top, label="top module")
    text = source.read_text(encoding="utf-8")
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    raw_names = re.findall(r"\bmodule\s+([^\s#(;]+)", text)
    if not raw_names:
        raise SubmissionValidationError("source declares no module")
    invalid = [name for name in raw_names if IDENTIFIER_RE.fullmatch(name) is None]
    if invalid:
        raise SubmissionValidationError(
            "invalid module name(s): " + ", ".join(repr(name) for name in invalid)
        )
    if expected_top not in raw_names:
        raise SubmissionValidationError(
            f"source does not declare expected top module {expected_top!r}"
        )
