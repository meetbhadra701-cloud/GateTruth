"""Pydantic schema for signed mutation-certification summaries (GTFS-030).

The committed results/mutation/certification/summary.json is the paper's central
46/60 certification artifact. Prior to this schema it carried no signature and no
provenance hashes -- nothing bound it to the exact task tree, reference RTL, public
testbench, or hidden-module revision it claimed to have audited, so a reader had no
way to tell whether the numbers still matched what is actually in the repository
today. This module defines the target schema; scripts/certify_mutation.py emits it
and scripts/verify_mutation_certification.py checks a committed summary against the
current tree without re-running mutation testing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness.schemas.canonical_json import compute_manifest_signature
from harness.schemas.manifest import DOCKER_DIGEST_RE, SHA256_HEX_RE


class MutationTaskCertification(BaseModel):
    """One task's row inside a signed mutation-certification summary."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "setup_error", "unsupported"]
    total_generated: int = Field(ge=0)
    indeterminate: int = Field(ge=0)
    kill_rate: float = Field(ge=0, le=100)
    killed: int = Field(ge=0)
    survived: int = Field(ge=0)
    stillborn: int = Field(ge=0)
    setup_errors: int = Field(ge=0)
    formal_only_kills: int = Field(ge=0)
    total: int = Field(ge=0)
    task_package_sha256: str = Field(pattern=SHA256_HEX_RE)
    reference_rtl_sha256: str = Field(pattern=SHA256_HEX_RE)
    public_testbench_sha256: str = Field(pattern=SHA256_HEX_RE)
    hidden_module_sha256: str | None = Field(default=None, pattern=SHA256_HEX_RE)
    hidden_test_count: int | None = Field(default=None, ge=1)


class MutationCertificationSummary(BaseModel):
    """Top-level signed mutation-certification summary contract."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def validate_raw_signature(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data
        signature = data.get("signature")
        if not isinstance(signature, str):
            return data
        expected = compute_manifest_signature(data)
        if signature != expected:
            raise ValueError("signature does not match canonical certification payload")
        return data

    schema_version: Literal[4]
    all_above_floor: bool
    any_unsupported: bool
    docker_digest: str = Field(pattern=DOCKER_DIGEST_RE)
    docker_digest_source: Literal["env", "file", "default"] | None = None
    harness_git: str = Field(min_length=1)
    jobs: int = Field(ge=1)
    metric: Literal["simulation_testbench_kill_rate"]
    min_kill: float = Field(ge=0, le=100)
    official: bool
    seed: int
    tasks: dict[str, MutationTaskCertification]
    timestamp: str = Field(min_length=1)
    signature: str = Field(pattern=SHA256_HEX_RE)


def load_mutation_certification_summary(path: str | Path) -> MutationCertificationSummary:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return MutationCertificationSummary.model_validate(data)
