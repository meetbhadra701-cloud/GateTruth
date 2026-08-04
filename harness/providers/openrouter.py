"""OpenRouter OpenAI-compatible chat-completions adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.providers import GenParams
from harness.providers._base import PricedProvider, require_int, require_mapping
from harness.providers._http import (
    PROVIDER_READ_TIMEOUT_S,
    ProviderHTTPError,
    ProviderRetryableError,
    post_json,
)
from harness.providers.pricing import supports_temperature
from harness.spend import DEFAULT_SPEND_PATH

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(PricedProvider):
    name = "openrouter"
    env_var = "OPENROUTER_API_KEY"

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
            choices = response.get("choices")
            if not isinstance(choices, list):
                raise ValueError("OpenRouter response choices must be a list")
            no_text_reason: str | None = None
            text = ""
            if not choices:
                no_text_reason = "OpenRouter response choices were empty"
                self.last_finish_reason = None
            else:
                choice = require_mapping(choices[0], "choices[0]")
                finish_reason = choice.get("finish_reason")
                self.last_finish_reason = finish_reason if isinstance(finish_reason, str) else None
                message = require_mapping(choice.get("message"), "choices[0].message")
                raw_text = message.get("content")
                if raw_text is None:
                    no_text_reason = "OpenRouter response contained no text"
                elif not isinstance(raw_text, str):
                    raise ValueError("OpenRouter response text must be a string")
                elif not raw_text.strip():
                    no_text_reason = "OpenRouter response contained no text"
                else:
                    text = raw_text
            # Usage is parsed even when there is no usable text: a provider can
            # bill an attempt that came back empty, and the usage block in this
            # same response is the only record of that cost. Settling it here
            # -- rather than releasing the reservation at zero -- means a retry
            # sequence's total recorded spend still matches what was billed.
            usage = require_mapping(response.get("usage"), "usage")
            tokens_in = require_int(
                usage.get("prompt_tokens"),
                "usage.prompt_tokens",
            )
            tokens_out = require_int(
                usage.get("completion_tokens"),
                "usage.completion_tokens",
            )
        except (ProviderHTTPError, ValueError):
            self.release_call(reserved_usd=reserved)
            raise
        self.finish_call(
            reserved_usd=reserved,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        if no_text_reason is not None:
            raise ProviderRetryableError(no_text_reason)
        return text
