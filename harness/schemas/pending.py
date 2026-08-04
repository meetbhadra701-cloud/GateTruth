"""Schema for a Track A generation result awaiting a separate scoring phase.

harness/evalmodel.py's combined eval_model() calls a provider's .generate() (needs
network) and then immediately runs the extracted submission through lint/sim/formal
subprocesses (iverilog, yosys, cocotb -- executing whatever text the model wrote) in
the same process. Neither this repo's pinned sandbox flags (--cap-drop=ALL) nor this
host's kernel allow an unprivileged process to self-isolate its own network access
(unshare --net and unshare --user --net both fail under those flags), so the only real
boundary is a process one: generate in a network-enabled container, write everything a
later scoring pass needs to disk, exit, and score in a *separate* --network none
container that never had network to begin with.

PendingGeneration is what the generate phase writes instead of a full ResultManifest --
a ResultManifest requires real scoring fields (stages, ppa, task_score) that don't exist
yet. It carries only what the score phase cannot re-derive itself: the provider/model
identity, usage, cost, and whether generation itself already failed (in which case the
score phase writes a zero-score ResultManifest directly, without ever touching the
extracted text).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness.schemas.canonical_json import compute_manifest_signature
from harness.schemas.manifest import SHA256_HEX_RE, TemperatureSetting


class PendingGeneration(BaseModel):
    """A signed record of one Track A generation attempt, before scoring."""

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
            raise ValueError("signature does not match canonical manifest payload")
        return data

    task_id: str = Field(min_length=1)
    suite_version: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    temperature: TemperatureSetting
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    max_output_tokens: int = Field(ge=1)
    provider_finish_reason: str | None = Field(default=None, min_length=1)
    wall_clock_s: float = Field(ge=0)
    submission_sha256: str | None = Field(default=None, pattern=SHA256_HEX_RE)
    generation_error: str | None = Field(default=None, min_length=1)
    official_skip_reason: str | None = Field(default=None, min_length=1)
    harness_git: str = Field(min_length=1)
    timestamp: str = Field(min_length=1)
    signature: str = Field(pattern=SHA256_HEX_RE)

    @model_validator(mode="after")
    def validate_rules(self) -> "PendingGeneration":
        failed = self.generation_error is not None
        skipped = self.official_skip_reason is not None
        has_submission = self.submission_sha256 is not None
        if failed and has_submission:
            raise ValueError("a failed generation cannot carry a submission_sha256")
        if skipped and (failed or has_submission):
            raise ValueError("a skipped task cannot also be a failed or scored generation")
        if not failed and not skipped and not has_submission:
            raise ValueError(
                "a generation that neither failed nor was skipped must carry a submission_sha256"
            )
        return self


def load_pending_generation(path: str | Path) -> PendingGeneration:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return PendingGeneration.model_validate(data)
