"""Provider adapter skeletons for GateTruth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GenParams:
    model: str
    temperature: float = 0.0
    max_tokens: int | None = None
    seed: int | None = None


class ProviderAdapter(Protocol):
    def generate(self, spec: str, interface: str, params: GenParams) -> str:
        """Generate an RTL candidate for the given task inputs."""
