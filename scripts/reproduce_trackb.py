"""Independently reproduce a signed Track B manifest's scoring through the pinned evaluator."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import shutil
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pydantic import ValidationError  # noqa: E402

from harness.schemas.canonical_json import (  # noqa: E402
    compute_manifest_signature,
    manifest_signature_payload,
)
from harness.schemas.manifest_b import AgentTrackBManifest, TrackBManifest  # noqa: E402
from harness.trackb import resolve_track_b_task, run_track_b, single_sv_file  # noqa: E402

GENERATION_FIELDS = (
    # Facts about how the design was *generated* (or, for a bare evaluator run, who
    # invoked it), not how it was *scored*. run_track_b() (what this script reruns)
    # only re-scores an already-given design against the pinned evaluator -- it has no
    # way to independently re-derive who produced that design or what it cost, so
    # these are trusted from the recorded manifest rather than compared. Mirrors
    # scripts/reproduce.py's own generation-vs-scoring split for Track A.
    "provider",
    "model",
    "temperature",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "tool_calls",
    "budget_exceeded",
    # A fresh tempfile.TemporaryDirectory() every run, torn down before run_track_b()
    # returns -- never the same path twice, even for a byte-identical reproduction.
    # submission_sha256 is the real content binding checked below; this field is only
    # ever informational.
    "submission_dir",
)


class ReproductionError(ValueError):
    """Raised when a manifest cannot be reproduced safely."""


def _load_raw_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReproductionError(f"cannot read manifest: {exc}") from exc
    if not isinstance(raw, dict):
        raise ReproductionError("manifest root must be a JSON object")
    return raw


def _validate_stored_manifest(raw: dict[str, Any]) -> TrackBManifest:
    recorded = raw.get("signature")
    recomputed = compute_manifest_signature(raw)
    if recorded != recomputed:
        raise ReproductionError(
            "stored signature mismatch\n"
            f"  recorded:   {recorded}\n"
            f"  recomputed: {recomputed}"
        )
    model = AgentTrackBManifest if "budget_exceeded" in raw else TrackBManifest
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise ReproductionError(f"invalid Track B manifest: {exc}") from exc


def _resolve_design_source(
    manifest_path: Path,
    manifest: TrackBManifest,
    explicit: Path | None,
) -> bytes:
    """Return the design's exact bytes -- never round-tripped through text mode, whose
    universal-newline handling silently rewrites CRLF to LF on read and would make a
    file with Windows line endings fail the byte-exact submission_sha256 check below
    even when untampered. trackb.py hashes read_bytes() too; this must match it."""

    if explicit is not None:
        source_path = explicit
    else:
        source_path = manifest_path.with_suffix(".sv")
        if not source_path.is_file():
            raise ReproductionError(
                "design not found: provide --submission or place a same-stem .sv "
                "next to the manifest (agentb.py writes one automatically for runs "
                "recorded after submission_sha256 existed; older manifests predate it "
                "and cannot be reproduced without an externally supplied --submission)"
            )
    source = source_path.resolve().read_bytes()
    if manifest.submission_sha256 is not None:
        actual = hashlib.sha256(source).hexdigest()
        if actual != manifest.submission_sha256:
            raise ReproductionError(
                "design content does not match the recorded submission_sha256\n"
                f"  recorded: {manifest.submission_sha256}\n"
                f"  actual:   {actual}"
            )
    return source


def _build_submission_dir(task_id: str, design_source: bytes, work_root: Path) -> Path:
    package = resolve_track_b_task(task_id)
    submission = work_root / "submission"
    shutil.copytree(package.root, submission)
    design_file = single_sv_file(submission / "design")
    design_file.write_bytes(design_source)
    return submission


def _candidate_payload(
    original: Mapping[str, Any],
    reproduced: TrackBManifest,
) -> dict[str, Any]:
    candidate = reproduced.model_dump(mode="json")
    for field in GENERATION_FIELDS:
        if field in original:
            candidate[field] = original[field]
        else:
            candidate.pop(field, None)
    return manifest_signature_payload(candidate)


def _payload_diff(
    original: Mapping[str, Any],
    reproduced: Mapping[str, Any],
) -> str:
    left = json.dumps(original, sort_keys=True, indent=2, ensure_ascii=False).splitlines()
    right = json.dumps(reproduced, sort_keys=True, indent=2, ensure_ascii=False).splitlines()
    return "\n".join(
        difflib.unified_diff(
            left,
            right,
            fromfile="recorded-manifest",
            tofile="reproduced-manifest",
            lineterm="",
        )
    )


def reproduce_manifest(
    manifest_path: str | Path,
    *,
    submission: str | Path | None = None,
    official: bool | None = None,
) -> tuple[bool, str]:
    """Re-run one signed Track B manifest's scoring and return whether its canonical
    payload matches.

    This reruns run_track_b() only -- it never re-invokes an LLM agent, so
    provider/model/token/cost/tool_calls/budget_exceeded are trusted from the original
    record (GENERATION_FIELDS above), exactly as scripts/reproduce.py already does for
    Track A's own generation-vs-scoring split.

    official=None (the default) infers the original scoring mode from the manifest
    itself: hidden_module_sha256 is only ever recorded when a real hidden-vector mount
    was resolved during an official run (mirrors harness/runner.py's own official
    signal, which scripts/reproduce.py already relies on for Track A). Pass an
    explicit True/False to override. Reproducing under official=True additionally
    requires GATETRUTH_HIDDEN_ROOT to be mounted; without it, run_track_b() disqualifies
    the rerun rather than silently falling back to public tests, so this fails closed
    as a MISMATCH rather than a false MATCH.
    """

    path = Path(manifest_path).resolve()
    raw = _load_raw_manifest(path)
    original = _validate_stored_manifest(raw)
    design_source = _resolve_design_source(
        path,
        original,
        Path(submission) if submission is not None else None,
    )
    resolved_official = (
        official if official is not None else original.hidden_module_sha256 is not None
    )

    with tempfile.TemporaryDirectory(prefix="gatetruth-reproduce-trackb-") as temp:
        submission_dir = _build_submission_dir(original.task_id, design_source, Path(temp))
        rerun = run_track_b(
            original.task_id,
            submission_dir,
            Path(temp) / "manifest.json",
            official=resolved_official,
        )

    recorded_payload = manifest_signature_payload(raw)
    rerun_payload = _candidate_payload(raw, rerun)
    rerun_signature = compute_manifest_signature(rerun_payload)
    if rerun_signature == original.signature:
        return True, (
            f"MATCH task={original.task_id} official={resolved_official} "
            f"signature={original.signature}"
        )
    diff = _payload_diff(recorded_payload, rerun_payload)
    return False, (
        "MISMATCH: reproduced canonical manifest differs\n"
        f"  official mode used: {resolved_official}"
        f"{' (inferred from hidden_module_sha256)' if official is None else ' (explicit)'}\n"
        f"  recorded signature:   {original.signature}\n"
        f"  reproduced signature: {rerun_signature}\n"
        f"{diff}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-run a signed Track B manifest's scoring and verify its canonical signature"
    )
    parser.add_argument("manifest", help="signed Track B manifest JSON")
    parser.add_argument(
        "--submission",
        help="exact design .sv source; defaults to the sibling .sv agentb.py writes next to the manifest",
    )
    parser.add_argument(
        "--official",
        dest="official",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "force official/non-official reproduction mode. Default: infer from the "
            "manifest itself (hidden_module_sha256 present means the original run was "
            "official; requires GATETRUTH_HIDDEN_ROOT to be mounted to reproduce it). "
            "Manifests predating that field fall back to non-official."
        ),
    )
    args = parser.parse_args(argv)

    try:
        matched, message = reproduce_manifest(
            args.manifest,
            submission=args.submission,
            official=args.official,
        )
    except (OSError, ValueError) as exc:
        print(f"reproduction refused: {exc}", file=sys.stderr)
        return 2
    stream = sys.stdout if matched else sys.stderr
    print(message, file=stream)
    return 0 if matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
