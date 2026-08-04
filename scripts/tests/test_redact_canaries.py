"""Regression tests for GTFS-045: the canary redactor must never rewrite a signed
JSON artifact, since any byte change invalidates its signature field."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.redact_canaries import SignedEvidenceCanaryError, redact

# Built from two fragments, neither of which matches CANARY_RE on its own, so this
# synthetic test value never appears as a contiguous canary-shaped string in this
# file's own source text -- scripts/contamination_check.py's repo-wide sweep would
# otherwise flag it as an undeclared/escaped canary leaking out of this test file.
_CANARY_PREFIX = "SILICONBENCH-CANARY-"
_CANARY_SUFFIX = "CAFEBABE-CAFE-BABE-CAFE-BABECAFEBABE"
CANARY = _CANARY_PREFIX + _CANARY_SUFFIX


def _make_repo(tmp_path: Path) -> Path:
    task_root = tmp_path / "tasks" / "demo"
    task_root.mkdir(parents=True)
    (task_root / "task.yaml").write_text(
        f'id: demo\ncanary: "{CANARY}"\n', encoding="utf-8"
    )
    return tmp_path


def test_escaped_canary_in_signed_json_is_never_rewritten(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    signed = repo / "results" / "eval" / "leak.json"
    signed.parent.mkdir(parents=True)
    payload = {
        "signature": "deadbeef",
        "task_id": "other_task",
        "generated_source": f"// echoed spec text\n// {CANARY}\nmodule top; endmodule\n",
    }
    original_bytes = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    signed.write_bytes(original_bytes)

    with pytest.raises(SignedEvidenceCanaryError) as excinfo:
        redact(repo, apply=False)
    assert "leak.json" in str(excinfo.value)
    assert signed.read_bytes() == original_bytes

    with pytest.raises(SignedEvidenceCanaryError):
        redact(repo, apply=True)
    assert signed.read_bytes() == original_bytes


def test_escaped_canary_in_unsigned_artifact_is_still_redacted(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    generated = repo / "results" / "eval" / "sample.sv"
    generated.parent.mkdir(parents=True)
    generated.write_text(f"// {CANARY}\nmodule top; endmodule\n", encoding="utf-8")

    touched = redact(repo, apply=False)
    assert generated in touched

    touched = redact(repo, apply=True)
    assert generated in touched
    assert CANARY not in generated.read_text(encoding="utf-8")
    assert "REDACTED-CANARY" in generated.read_text(encoding="utf-8")


def test_canary_inside_its_own_owning_package_is_left_alone(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    spec = repo / "tasks" / "demo" / "spec.md"
    spec.write_text(f"Canary for this task: {CANARY}\n", encoding="utf-8")

    touched = redact(repo, apply=True)
    assert spec not in touched
    assert CANARY in spec.read_text(encoding="utf-8")
