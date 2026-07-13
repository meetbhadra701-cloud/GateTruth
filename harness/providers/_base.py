"""Shared pricing, key loading, usage, and spend reservation for real adapters."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from harness.providers import GenParams
from harness.providers.pricing import ModelPrice, price_for, worst_case_cost
from harness.spend import DEFAULT_SPEND_PATH, reserve_spend, settle_spend_reservation


class PricedProvider:
    name: str
    env_var: str

    def __init__(
        self,
        model: str,
        *,
        temperature: float = 0.0,
        spend_path: str | Path = DEFAULT_SPEND_PATH,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.spend_path = Path(spend_path)
        self.price: ModelPrice = price_for(self.name, model)
        self._tokens_in = 0
        self._tokens_out = 0
        self._cost_usd = 0.0

    @property
    def usage(self) -> dict[str, int | float]:
        return {
            "tokens_in": self._tokens_in,
            "tokens_out": self._tokens_out,
            "cost_usd": self._cost_usd,
        }

    def begin_call(
        self,
        prompt: str,
        system: str,
        params: GenParams,
    ) -> tuple[str, int, float]:
        if params.model != self.model:
            raise ValueError(
                f"GenParams model {params.model!r} does not match adapter model {self.model!r}"
            )
        if params.max_tokens is None or params.max_tokens < 1:
            raise ValueError("max_tokens must be at least 1")
        key = os.environ.get(self.env_var)
        if not key:
            raise RuntimeError(f"missing required environment variable {self.env_var}")
        reserved = worst_case_cost(
            self.name,
            self.model,
            prompt=prompt,
            system=system,
            max_tokens=params.max_tokens,
        )
        reserve_spend(
            reserved,
            provider=self.name,
            model=self.model,
            path=self.spend_path,
            reservation=True,
        )
        return key, params.max_tokens, reserved

    def finish_call(
        self,
        *,
        reserved_usd: float,
        tokens_in: int,
        tokens_out: int,
    ) -> float:
        if tokens_in < 0 or tokens_out < 0:
            raise ValueError("provider token usage must be nonnegative")
        actual = self.price.cost(tokens_in, tokens_out)
        self._tokens_in += tokens_in
        self._tokens_out += tokens_out
        self._cost_usd += actual
        settle_spend_reservation(
            reserved_usd,
            actual,
            provider=self.name,
            model=self.model,
            path=self.spend_path,
        )
        return actual


def require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"provider response {name} must be an object")
    return value


def require_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"provider response {name} must be a nonnegative integer")
    return value
