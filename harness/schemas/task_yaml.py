"""Pydantic implementation of the frozen task.yaml contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Tier = Literal["T1", "T2", "T3"]

CANARY_RE = r"^SILICONBENCH-CANARY-[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$"
SIGNED_RE = r"^SIGNED-OFF-BY-MEET-\d{4}-\d{2}-\d{2}$"


class TaskWeights(BaseModel):
    """PPA weights, fixed to 1 for every metric in v1.0."""

    model_config = ConfigDict(extra="forbid")

    area: int = Field(default=1)
    delay: int = Field(default=1)
    power: int = Field(default=1)

    @model_validator(mode="after")
    def validate_v1_weights(self) -> "TaskWeights":
        if (self.area, self.delay, self.power) != (1, 1, 1):
            raise ValueError("v1.0 task weights must all be 1")
        return self


class TaskYaml(BaseModel):
    """Frozen task.yaml schema."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    tier: Tier
    tags: list[str] = Field(min_length=1)
    clock_target_ns: float = Field(gt=0)
    formal: bool
    route_t3: bool
    weights: TaskWeights
    canary: str = Field(pattern=CANARY_RE)
    ref_review: str = Field(pattern=rf"^(PENDING|{SIGNED_RE[1:-1]})$")
    hidden_review: str = Field(pattern=rf"^(PENDING|{SIGNED_RE[1:-1]})$")

    def require_official_reviews(self) -> None:
        if not self.ref_review.startswith("SIGNED-OFF-BY-MEET-"):
            raise ValueError("ref_review must be signed off for official runs")
        if not self.hidden_review.startswith("SIGNED-OFF-BY-MEET-"):
            raise ValueError("hidden_review must be signed off for official runs")


class TaskYamlParseError(ValueError):
    """Raised when the frozen task.yaml subset cannot be parsed."""


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[:index].rstrip()
    return line.rstrip()


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"true", "false"}:
        return value == "true"
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _parse_value(value: str) -> Any:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item) for item in inner.split(",")]
    if value.startswith("{") and value.endswith("}"):
        inner = value[1:-1].strip()
        result: dict[str, Any] = {}
        if not inner:
            return result
        for item in inner.split(","):
            key, sep, raw = item.partition(":")
            if not sep:
                raise TaskYamlParseError(f"invalid inline map item: {item}")
            result[key.strip()] = _parse_scalar(raw)
        return result
    return _parse_scalar(value)


def parse_task_yaml_text(text: str) -> dict[str, Any]:
    """Parse the flat YAML subset used by frozen GateTruth task files."""

    result: dict[str, Any] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw_line).strip()
        if not line:
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise TaskYamlParseError(f"line {line_number}: expected key: value")
        key = key.strip()
        if not key:
            raise TaskYamlParseError(f"line {line_number}: empty key")
        result[key] = _parse_value(value)
    return result


def load_task_yaml(path: str | Path) -> TaskYaml:
    text = Path(path).read_text(encoding="utf-8")
    return TaskYaml.model_validate(parse_task_yaml_text(text))
