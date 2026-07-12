"""Pydantic schema for Track B evaluator manifests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness.schemas.canonical_json import compute_manifest_signature
from harness.schemas.manifest import DOCKER_DIGEST_RE, SHA256_HEX_RE, Platform

ObjectiveType = Literal["timing_closure", "area_reduction", "power_reduction", "add_property"]


class TrackBStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: int = Field(ge=0)
    name: str = Field(min_length=1)
    status: Literal["pass", "fail", "skip"]
    warnings: int | None = Field(default=None, ge=0)
    tests_run: int | None = Field(default=None, ge=0)
    tests_passed: int | None = Field(default=None, ge=0)
    area_um2: float | None = Field(default=None, ge=0)
    cell_count: int | None = Field(default=None, ge=0)
    wns_ns: float | None = None
    tns_ns: float | None = None
    fmax_mhz: float | None = Field(default=None, ge=0)
    power_mw: float | None = Field(default=None, ge=0)


class SecResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pass", "fail", "skip", "timeout"]
    backend: str | None = None
    seconds: float | None = Field(default=None, ge=0)


class PpaMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area_um2: float | None = Field(default=None, ge=0)
    wns_ns: float | None = None
    tns_ns: float | None = None
    fmax_mhz: float | None = Field(default=None, ge=0)
    power_mw: float | None = Field(default=None, ge=0)


class PpaDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design: PpaMetric | None = None
    baseline: PpaMetric | None = None
    area_ratio: float | None = Field(default=None, ge=0)
    power_ratio: float | None = Field(default=None, ge=0)
    wns_delta_ns: float | None = None


class TrackBManifest(BaseModel):
    """Track B result manifest with Track A canonical signature rules."""

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
    track: Literal["B"]
    docker_digest: str = Field(pattern=DOCKER_DIGEST_RE)
    platform: Platform
    submission_dir: str = Field(min_length=1)
    disqualified: bool
    disqualification_reason: str | None = None
    objective_type: ObjectiveType
    objective_pass: bool
    stages: list[TrackBStage] = Field(min_length=1)
    sec: SecResult
    ppa_delta: PpaDelta
    task_score: float = Field(ge=0)
    wall_clock_s: float = Field(ge=0)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    temperature: float = Field(ge=0)
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    tool_calls: int = Field(ge=0)
    timestamp: str = Field(min_length=1)
    signature: str = Field(pattern=SHA256_HEX_RE)

    @model_validator(mode="after")
    def validate_rules(self) -> "TrackBManifest":
        if self.disqualified and self.task_score != 0:
            raise ValueError("disqualified manifests must score 0")
        if not self.objective_pass and self.task_score != 0:
            raise ValueError("objective-failing manifests must score 0")
        if self.disqualified and not self.disqualification_reason:
            raise ValueError("disqualified manifests need a reason")
        return self


def load_manifest_b(path: str | Path) -> TrackBManifest:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return TrackBManifest.model_validate(data)


def validate_manifest_b(path: str | Path) -> None:
    load_manifest_b(path)
