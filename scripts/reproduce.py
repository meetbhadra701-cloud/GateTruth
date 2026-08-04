"""Independently reproduce a signed Track A manifest through the pinned pipeline."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pydantic import ValidationError  # noqa: E402

from harness.runner import resolve_task, run_task  # noqa: E402
from harness.schemas.canonical_json import (  # noqa: E402
    compute_manifest_signature,
    manifest_signature_payload,
)
from harness.schemas.manifest import ResultManifest  # noqa: E402

GENERATION_FIELDS = (
    # Facts about how the submission was *generated*, not how it was *scored*. run_task()
    # (what this script reruns) only scores an already-given submission file -- it has no way
    # to independently re-derive what a model call originally requested or which provider
    # answered, so these are trusted from the recorded manifest rather than compared.
    "provider",
    "model",
    "temperature",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "prompt_version",
    "max_output_tokens",
    "provider_finish_reason",
    # Which harness commit produced the *original* run. A legitimate reproduction on a later
    # harness commit (unrelated fixes elsewhere, e.g. doc or comment changes) should still be
    # able to confirm a MATCH on the scoring math -- this field records provenance of the code
    # that ran, not a property of the score itself, so it is not part of what must match.
    "harness_git",
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


def _validate_stored_manifest(raw: dict[str, Any]) -> ResultManifest:
    recorded = raw.get("signature")
    recomputed = compute_manifest_signature(raw)
    if recorded != recomputed:
        raise ReproductionError(
            "stored signature mismatch\n"
            f"  recorded:   {recorded}\n"
            f"  recomputed: {recomputed}"
        )
    try:
        return ResultManifest.model_validate(raw)
    except ValidationError as exc:
        raise ReproductionError(f"invalid Track A manifest: {exc}") from exc


def _resolve_submission(
    manifest_path: Path,
    manifest: ResultManifest,
    explicit: Path | None,
) -> Path:
    if explicit is not None:
        submission = explicit
    else:
        sibling = manifest_path.with_suffix(".sv")
        if sibling.is_file():
            submission = sibling
        elif manifest.provider == "local" and manifest.model == "submission":
            submission = resolve_task(manifest.task_id).root / "ref" / "ref.sv"
        else:
            raise ReproductionError(
                "submission not found: provide --submission or place a same-stem .sv "
                "next to the manifest"
            )
    submission = submission.resolve()
    if not submission.is_file():
        raise ReproductionError(f"submission is not a file: {submission}")
    return submission


def _candidate_payload(
    original: Mapping[str, Any],
    reproduced: ResultManifest,
) -> dict[str, Any]:
    candidate = reproduced.model_dump(mode="json", exclude_none=True)
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
    """Re-run one signed manifest and return whether its canonical payload matches.

    official=None (the default) infers the original scoring mode from the manifest itself:
    hidden_module_sha256 is only ever recorded when a real hidden-vector mount was resolved
    and merged during an official run (harness/runner.py's _prepare_sim_tests()), so its
    presence is direct evidence official scoring happened, not an assumption. Pass an explicit
    True/False to override this inference. Reproducing under official=True additionally
    requires GATETRUTH_HIDDEN_ROOT to be mounted; without it, reproduction fails closed rather
    than silently falling back to public tests.
    """

    path = Path(manifest_path).resolve()
    raw = _load_raw_manifest(path)
    original = _validate_stored_manifest(raw)
    if original.generation_error or original.official_skip_reason:
        raise ReproductionError("only successfully scored Track A manifests are reproducible")
    source = _resolve_submission(
        path,
        original,
        Path(submission) if submission is not None else None,
    )
    resolved_official = (
        official if official is not None else original.hidden_module_sha256 is not None
    )

    with tempfile.TemporaryDirectory(prefix="gatetruth-reproduce-") as temp:
        rerun = run_task(
            original.task_id, source, Path(temp) / "manifest.json", official=resolved_official
        )

    recorded_payload = manifest_signature_payload(raw)
    rerun_payload = _candidate_payload(raw, rerun)
    rerun_signature = compute_manifest_signature(rerun_payload)
    if rerun_signature == original.signature:
        return True, (
            f"MATCH task={original.task_id} submission={source} "
            f"official={resolved_official} signature={original.signature}"
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
        description="Re-run a signed Track A manifest and verify its canonical signature"
    )
    parser.add_argument("manifest", help="signed Track A manifest JSON")
    parser.add_argument(
        "--submission",
        help="exact RTL source; defaults to sibling .sv or the task reference",
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
            "Older manifests predating that field fall back to non-official, matching "
            "the previous default -- pass --official explicitly to reproduce those "
            "under official mode."
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
