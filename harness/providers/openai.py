"""OpenAI Chat Completions API adapter."""

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

API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(PricedProvider):
    name = "openai"
    env_var = "OPENAI_API_KEY"

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
            "max_completion_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": interface},
                {"role": "user", "content": spec},
            ],
        }
        if supports_temperature(self.name, self.model):
            payload["temperature"] = params.temperature
        if params.seed is not None:
            payload["seed"] = params.seed
        try:
            response = post_json(
                API_URL,
                headers={
                    "content-type": "application/json",
                    "authorization": f"Bearer {key}",
                },
                payload=payload,
                timeout_s=PROVIDER_READ_TIMEOUT_S,
            )
        except ProviderHTTPError:
            self.release_call(reserved_usd=reserved)
            raise
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("OpenAI response choices must be a nonempty list")
        choice = require_mapping(choices[0], "choices[0]")
        message = require_mapping(choice.get("message"), "choices[0].message")
        text = message.get("content")
        if not isinstance(text, str) or not text:
            raise ValueError("OpenAI response contained no text")
        usage = require_mapping(response.get("usage"), "usage")
        tokens_in = require_int(usage.get("prompt_tokens"), "usage.prompt_tokens")
        tokens_out = require_int(
            usage.get("completion_tokens"),
            "usage.completion_tokens",
        )
        self.finish_call(
            reserved_usd=reserved,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        return text
