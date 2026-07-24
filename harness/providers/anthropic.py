"""Anthropic Messages API adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.providers import GenParams
from harness.providers._base import PricedProvider, require_int, require_mapping
from harness.providers._http import (
    PROVIDER_READ_TIMEOUT_S,
    ProviderHTTPError,
    post_json,
)
from harness.providers.pricing import supports_temperature
from harness.spend import DEFAULT_SPEND_PATH

API_URL = "https://api.anthropic.com/v1/messages"


class AnthropicProvider(PricedProvider):
    name = "anthropic"
    env_var = "ANTHROPIC_API_KEY"

    def __init__(
        self,
        model: str,
        *,
        temperature: float = 0.0,
        spend_path: str | Path = DEFAULT_SPEND_PATH,
    ) -> None:
        super().__init__(model, temperature=temperature, spend_path=spend_path)

    def generate(self, spec: str, interface: str, params: GenParams) -> str:
        key, max_tokens, reserved = self.begin_call(spec, interface, params)
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": interface,
            "messages": [{"role": "user", "content": spec}],
        }
        if supports_temperature(self.name, self.model):
            payload["temperature"] = params.temperature
        try:
            response = post_json(
                API_URL,
                headers={
                    "content-type": "application/json",
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                },
                payload=payload,
                timeout_s=PROVIDER_READ_TIMEOUT_S,
            )
            content = response.get("content")
            if not isinstance(content, list):
                raise ValueError("Anthropic response content must be a list")
            text = "".join(
                block["text"]
                for block in content
                if isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            )
            if not text:
                raise ValueError("Anthropic response contained no text")
            usage: dict[str, Any] = require_mapping(response.get("usage"), "usage")
            tokens_in = require_int(
                usage.get("input_tokens"),
                "usage.input_tokens",
            )
            tokens_out = require_int(
                usage.get("output_tokens"),
                "usage.output_tokens",
            )
        except (ProviderHTTPError, ValueError):
            self.release_call(reserved_usd=reserved)
            raise
        self.finish_call(
            reserved_usd=reserved,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        return text
