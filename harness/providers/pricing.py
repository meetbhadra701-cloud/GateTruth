"""Pinned model pricing used for pre-call reservations and actual-cost accounting."""

from __future__ import annotations

from dataclasses import dataclass

PRICING_DATE = "2026-07-13"


class UnknownModelPricing(ValueError):
    """Raised rather than guessing the price of an unpinned model."""


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        if tokens_in < 0 or tokens_out < 0:
            raise ValueError("token counts must be nonnegative")
        return (
            tokens_in * self.input_per_mtok
            + tokens_out * self.output_per_mtok
        ) / 1_000_000.0


PRICES: dict[tuple[str, str], ModelPrice] = {
    ("anthropic", "claude-haiku-4-5-20251001"): ModelPrice(1.0, 5.0),
    ("openai", "gpt-5-mini"): ModelPrice(0.25, 2.0),
    ("openai", "gpt-5-mini-2025-08-07"): ModelPrice(0.25, 2.0),
    ("openrouter", "anthropic/claude-haiku-4.5"): ModelPrice(1.0, 5.0),
    ("openrouter", "openai/gpt-5-mini"): ModelPrice(0.25, 2.0),
}


def price_for(provider: str, model: str) -> ModelPrice:
    try:
        return PRICES[(provider, model)]
    except KeyError as exc:
        raise UnknownModelPricing(
            f"no pinned price for {provider}/{model} as of {PRICING_DATE}"
        ) from exc


def estimate_prompt_tokens(prompt: str, system: str) -> int:
    # One token per UTF-8 byte plus protocol overhead is intentionally conservative.
    return max(1, len(prompt.encode("utf-8")) + len(system.encode("utf-8")) + 64)


def worst_case_cost(
    provider: str,
    model: str,
    *,
    prompt: str,
    system: str,
    max_tokens: int,
) -> float:
    if max_tokens < 1:
        raise ValueError("max_tokens must be at least 1")
    return price_for(provider, model).cost(
        estimate_prompt_tokens(prompt, system),
        max_tokens,
    )
