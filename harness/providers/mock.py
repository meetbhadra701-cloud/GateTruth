"""Deterministic scripted provider for key-independent agent tests."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from harness.providers import GenParams


class MockProvider:
    """Replay JSON actions while reporting configurable synthetic usage."""

    name = "mock"
    model = "mock-scripted"
    temperature = 0.0

    def __init__(
        self,
        script: list[dict[str, Any]],
        *,
        tokens_in_per_call: int = 10,
        tokens_out_per_call: int = 5,
        cost_usd_per_call: float = 0.0,
    ) -> None:
        if not all(isinstance(action, dict) for action in script):
            raise ValueError("mock script must be a list of JSON objects")
        if tokens_in_per_call < 0 or tokens_out_per_call < 0 or cost_usd_per_call < 0:
            raise ValueError("mock usage charges must be nonnegative")
        self._script = deepcopy(script)
        self._index = 0
        self._tokens_in_per_call = tokens_in_per_call
        self._tokens_out_per_call = tokens_out_per_call
        self._cost_usd_per_call = cost_usd_per_call
        self._tokens_in = 0
        self._tokens_out = 0
        self._cost_usd = 0.0

    def generate(self, spec: str, interface: str, params: GenParams) -> str:
        """Return the next scripted action through the frozen adapter method."""

        del spec, interface, params
        if self._index >= len(self._script):
            raise RuntimeError("mock script exhausted before done")
        action = self._script[self._index]
        self._index += 1
        self._tokens_in += self._tokens_in_per_call
        self._tokens_out += self._tokens_out_per_call
        self._cost_usd += self._cost_usd_per_call
        return json.dumps(action)

    @property
    def usage(self) -> dict[str, int | float]:
        return {
            "tokens_in": self._tokens_in,
            "tokens_out": self._tokens_out,
            "cost_usd": self._cost_usd,
        }


class MockCompletionProvider:
    """Replay raw text completions for no-network generation tests."""

    name = "mock"

    def __init__(
        self,
        responses: list[str],
        *,
        model: str = "mock-completion",
        temperature: float = 0.0,
        tokens_in_per_call: int = 10,
        tokens_out_per_call: int = 5,
        cost_usd_per_call: float = 0.0,
    ) -> None:
        if not responses or not all(isinstance(response, str) for response in responses):
            raise ValueError("mock responses must be a nonempty list of strings")
        if temperature < 0:
            raise ValueError("temperature must be nonnegative")
        if tokens_in_per_call < 0 or tokens_out_per_call < 0 or cost_usd_per_call < 0:
            raise ValueError("mock usage charges must be nonnegative")
        self.model = model
        self.temperature = temperature
        self._responses = list(responses)
        self._index = 0
        self._tokens_in_per_call = tokens_in_per_call
        self._tokens_out_per_call = tokens_out_per_call
        self._cost_usd_per_call = cost_usd_per_call
        self._tokens_in = 0
        self._tokens_out = 0
        self._cost_usd = 0.0

    def generate(self, spec: str, interface: str, params: GenParams) -> str:
        del spec, interface, params
        if self._index >= len(self._responses):
            raise RuntimeError("mock completion responses exhausted")
        response = self._responses[self._index]
        self._index += 1
        self._tokens_in += self._tokens_in_per_call
        self._tokens_out += self._tokens_out_per_call
        self._cost_usd += self._cost_usd_per_call
        return response

    @property
    def usage(self) -> dict[str, int | float]:
        return {
            "tokens_in": self._tokens_in,
            "tokens_out": self._tokens_out,
            "cost_usd": self._cost_usd,
        }
