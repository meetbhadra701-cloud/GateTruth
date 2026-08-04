"""Pydantic implementation of the frozen result manifest contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections.abc import Mapping
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from harness.schemas.canonical_json import compute_manifest_signature

Platform = Literal["linux/amd64"]
StageStatus = Literal["pass", "fail", "skip"]
TemperatureSetting = Annotated[float, Field(ge=0)] | Literal["provider_default"]

SHA256_HEX_RE = r"^[0-9a-f]{64}$"
DOCKER_DIGEST_RE = r"^sha256:[0-9a-f]{64}$"

METRIC_FIELDS = frozenset(
    {
        "warnings",
        "tests_run",
        "tests_passed",
        "area_um2",
        "cell_count",
        "wns_ns",
        "tns_ns",
        "fmax_mhz",
        "power_mw",
    }
)

CANONICAL_STAGE_NAMES: dict[int, str] = {
    0: "lint",
    1: "sim",
    2: "formal",
    3: "synth",
    4: "sta",
    5: "power",
    6: "route",
}


class StageResult(BaseModel):
    """One manifest stage entry with stage-specific metrics."""

    model_config = ConfigDict(extra="forbid")

    STAGE_METRICS: ClassVar[dict[int, frozenset[str]]] = {
        0: frozenset({"warnings"}),
        1: frozenset({"tests_run", "tests_passed"}),
        2: frozenset(),
        3: frozenset({"area_um2", "cell_count"}),
        4: frozenset({"wns_ns", "tns_ns", "fmax_mhz"}),
        5: frozenset({"power_mw"}),
        6: frozenset(),
    }

    stage: int = Field(ge=0, le=6)
    name: str = Field(min_length=1)
    status: StageStatus
    warnings: int | None = Field(default=None, ge=0)
    tests_run: int | None = Field(default=None, ge=0)
    tests_passed: int | None = Field(default=None, ge=0)
    area_um2: float | None = Field(default=None, gt=0)
    cell_count: int | None = Field(default=None, ge=0)
    wns_ns: float | None = None
    tns_ns: float | None = None
    fmax_mhz: float | None = Field(default=None, gt=0)
    power_mw: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_stage_metrics(self) -> "StageResult":
        allowed = self.STAGE_METRICS[self.stage]
        present = {
            name
            for name in METRIC_FIELDS
            if getattr(self, name) is not None
        }

        if self.status in {"fail", "skip"} and present:
            raise ValueError("metrics must be null on stage fail or skip")

        unexpected = present - allowed
        if unexpected:
            names = ", ".join(sorted(unexpected))
            raise ValueError(f"stage {self.stage} has non-contract metrics: {names}")

        if self.status == "pass":
            missing = allowed - present
            if missing:
                names = ", ".join(sorted(missing))
                raise ValueError(f"stage {self.stage} missing metrics: {names}")

        if self.stage == 1 and self.status == "pass":
            if self.tests_passed is not None and self.tests_run is not None:
                if self.tests_passed > self.tests_run:
                    raise ValueError("tests_passed cannot exceed tests_run")

        return self


class ResultManifest(BaseModel):
    """Top-level manifest schema."""

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
    docker_digest: str = Field(pattern=DOCKER_DIGEST_RE)
    platform: Platform
    stages: list[StageResult] = Field(min_length=1)
    sec: float = Field(ge=0)
    ppa: float = Field(ge=0)
    task_score: float = Field(ge=0)
    wall_clock_s: float = Field(ge=0)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    temperature: TemperatureSetting
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    prompt_version: str | None = Field(default=None, min_length=1)
    generation_error: str | None = Field(default=None, min_length=1)
    official_skip_reason: str | None = Field(default=None, min_length=1)
    harness_git: str | None = Field(default=None, min_length=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    provider_finish_reason: str | None = Field(default=None, min_length=1)
    submission_sha256: str | None = Field(default=None, pattern=SHA256_HEX_RE)
    task_package_sha256: str | None = Field(default=None, pattern=SHA256_HEX_RE)
    reference_metrics_sha256: str | None = Field(default=None, pattern=SHA256_HEX_RE)
    timestamp: str = Field(min_length=1)
    signature: str = Field(pattern=SHA256_HEX_RE)

    @model_validator(mode="after")
    def validate_manifest_rules(self) -> "ResultManifest":
        stage_ids = [stage.stage for stage in self.stages]
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("stages must not repeat a stage number")

        expected_ids = sorted(CANONICAL_STAGE_NAMES)
        if stage_ids != expected_ids:
            raise ValueError(
                f"stages must be exactly {expected_ids} in order, got {stage_ids}"
            )
        for stage in self.stages:
            expected_name = CANONICAL_STAGE_NAMES[stage.stage]
            if stage.name != expected_name:
                raise ValueError(
                    f"stage {stage.stage} must be named {expected_name!r}, "
                    f"got {stage.name!r}"
                )

        correctness_failed = any(
            stage.stage in {0, 1, 2} and stage.status == "fail"
            for stage in self.stages
        )
        if correctness_failed and self.task_score != 0:
            raise ValueError("task_score must be 0 when a correctness gate fails")

        ppa_stages_passed = all(
            stage.status == "pass"
            for stage in self.stages
            if stage.stage in {3, 4, 5}
        )
        if not ppa_stages_passed and (self.ppa != 0 or self.task_score != 0):
            raise ValueError(
                "ppa and task_score must both be 0 unless synth, sta, and power "
                "(stages 3, 4, 5) all pass -- a manifest cannot report a physical "
                "quality score without a complete, passing PPA flow behind it"
            )

        return self


def load_manifest(path: str | Path) -> ResultManifest:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return ResultManifest.model_validate(data)


def validate_manifest(path: str | Path) -> None:
    load_manifest(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a GateTruth manifest")
    parser.add_argument("--validate", metavar="PATH", help="manifest JSON to validate")
    args = parser.parse_args(argv)

    if not args.validate:
        parser.error("--validate is required")

    try:
        validate_manifest(args.validate)
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        print(f"invalid manifest: {args.validate}", file=sys.stderr)
        print(exc, file=sys.stderr)
        return 1

    print(f"valid manifest: {args.validate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
