from __future__ import annotations

from io import BytesIO
from typing import Any
from urllib.error import HTTPError

import pytest

from harness.providers import GenParams
from harness.providers import _http as http_module
from harness.providers import anthropic as anthropic_module
from harness.providers import openai as openai_module
from harness.providers import openrouter as openrouter_module
from harness.providers.anthropic import AnthropicProvider
from harness.providers.openai import OpenAIProvider
from harness.providers.openrouter import OpenRouterProvider
from harness.providers.pricing import (
    OFFICIAL_LEADERBOARD_MODELS,
    PRICING_DATE,
    PROVIDER_DEFAULT_TEMPERATURE,
    UnknownModelPricing,
    price_for,
)
from harness.spend import SpendCapExceeded, load_spend

PARAMS_ANTHROPIC = GenParams(model="claude-haiku-4-5-20251001", temperature=0.0, max_tokens=100, seed=7)
PARAMS_OPENAI = GenParams(model="gpt-5-mini-2025-08-07", temperature=0.0, max_tokens=100, seed=7)
PARAMS_OPENROUTER = GenParams(model="anthropic/claude-haiku-4.5", temperature=0.0, max_tokens=100, seed=7)


def test_anthropic_adapter_records_usage_and_settles_reservation(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-key")
    captured: dict[str, Any] = {}

    def fake_post(url, *, headers, payload, timeout_s=60.0):
        captured.update(url=url, payload=payload, timeout_s=timeout_s)
        assert headers["x-api-key"]
        return {
            "content": [{"type": "text", "text": '{"tool":"done"}'}],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }

    monkeypatch.setattr(anthropic_module, "post_json", fake_post)
    spend = tmp_path / "spend.json"
    provider = AnthropicProvider(PARAMS_ANTHROPIC.model, spend_path=spend)

    assert provider.generate("prompt", "system", PARAMS_ANTHROPIC) == '{"tool":"done"}'
    assert captured["url"] == anthropic_module.API_URL
    assert captured["payload"]["max_tokens"] == 100
    assert captured["payload"]["temperature"] == 0.0
    assert provider.usage == {"tokens_in": 100, "tokens_out": 20, "cost_usd": 0.0002}
    recorded = load_spend(spend)
    assert recorded["total_usd"] == pytest.approx(0.0002)
    assert "reservation" not in recorded["runs"][0]


def test_openai_adapter_parses_recorded_chat_response(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")

    def fake_post(url, *, headers, payload, timeout_s=60.0):
        assert url == openai_module.API_URL
        assert headers["authorization"].startswith("Bearer ")
        assert payload["max_completion_tokens"] == 100
        assert payload["seed"] == 7
        assert "temperature" not in payload
        return {
            "choices": [{"message": {"content": '{"tool":"sb_lint"}'}}],
            "usage": {"prompt_tokens": 80, "completion_tokens": 10},
        }

    monkeypatch.setattr(openai_module, "post_json", fake_post)
    provider = OpenAIProvider(PARAMS_OPENAI.model, spend_path=tmp_path / "spend.json")

    assert provider.generate("prompt", "system", PARAMS_OPENAI) == '{"tool":"sb_lint"}'
    assert provider.usage["tokens_in"] == 80
    assert provider.usage["tokens_out"] == 10
    assert provider.usage["cost_usd"] == pytest.approx(0.00004)


def test_openrouter_adapter_parses_recorded_chat_response(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "unit-test-key")

    def fake_post(url, *, headers, payload, timeout_s=60.0):
        assert url == openrouter_module.API_URL
        assert headers["authorization"].startswith("Bearer ")
        assert payload["max_tokens"] == 100
        assert payload["temperature"] == 0.0
        return {
            "choices": [{"message": {"content": '{"tool":"read_file","path":"spec.md"}'}}],
            "usage": {"prompt_tokens": 90, "completion_tokens": 12},
        }

    monkeypatch.setattr(openrouter_module, "post_json", fake_post)
    provider = OpenRouterProvider(PARAMS_OPENROUTER.model, spend_path=tmp_path / "spend.json")

    text = provider.generate("prompt", "system", PARAMS_OPENROUTER)
    assert text == '{"tool":"read_file","path":"spec.md"}'
    assert provider.usage["tokens_in"] == 90
    assert provider.usage["tokens_out"] == 12
    assert provider.usage["cost_usd"] == pytest.approx(0.00015)


def test_unknown_pricing_refuses_before_network():
    with pytest.raises(UnknownModelPricing, match=PRICING_DATE):
        AnthropicProvider("claude-unpriced-future-model")


def test_missing_key_names_env_var_without_secret(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = AnthropicProvider(PARAMS_ANTHROPIC.model, spend_path=tmp_path / "spend.json")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        provider.generate("prompt", "system", PARAMS_ANTHROPIC)


def test_worst_case_reservation_blocks_before_http(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-key")
    monkeypatch.setenv("SILICONBENCH_SPEND_CAP_USD", "0.0001")
    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("HTTP must not run after reservation refusal")

    monkeypatch.setattr(anthropic_module, "post_json", fake_post)
    provider = AnthropicProvider(PARAMS_ANTHROPIC.model, spend_path=tmp_path / "spend.json")

    with pytest.raises(SpendCapExceeded):
        provider.generate("prompt", "system", PARAMS_ANTHROPIC)
    assert called is False
    assert not (tmp_path / "spend.json").exists()


def test_pricing_table_has_expected_pinned_models():
    assert price_for("anthropic", PARAMS_ANTHROPIC.model).input_per_mtok == 1.0
    assert price_for("openai", PARAMS_OPENAI.model).output_per_mtok == 2.0
    assert price_for("openrouter", PARAMS_OPENROUTER.model).output_per_mtok == 5.0


def test_every_official_leaderboard_model_has_pinned_positive_pricing():
    assert len(OFFICIAL_LEADERBOARD_MODELS) == 7
    for provider, model in OFFICIAL_LEADERBOARD_MODELS:
        price = price_for(provider, model)
        assert price.input_per_mtok > 0
        assert price.output_per_mtok > 0


@pytest.mark.parametrize(
    ("model", "expected_temperature"),
    [
        ("claude-opus-4-8", None),
        ("claude-haiku-4-5-20251001", 0.0),
        ("claude-sonnet-4-6", 0.0),
    ],
)
def test_anthropic_temperature_capability_controls_payload(
    model,
    expected_temperature,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-key")
    captured: dict[str, Any] = {}

    def fake_post(url, *, headers, payload, timeout_s=60.0):
        captured.update(payload)
        return {
            "content": [{"type": "text", "text": "module x; endmodule"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    monkeypatch.setattr(anthropic_module, "post_json", fake_post)
    provider = AnthropicProvider(model, spend_path=tmp_path / "spend.json")
    params = GenParams(model=model, temperature=0.0, max_tokens=8, seed=0)

    assert provider.generate("prompt", "system", params) == "module x; endmodule"
    if expected_temperature is None:
        assert "temperature" not in captured
        assert provider.manifest_temperature == PROVIDER_DEFAULT_TEMPERATURE
    else:
        assert captured["temperature"] == expected_temperature
        assert provider.manifest_temperature == expected_temperature


@pytest.mark.parametrize("model", ["gpt-5", "gpt-5-mini"])
def test_openai_reasoning_models_omit_temperature(
    model,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")
    captured: dict[str, Any] = {}

    def fake_post(url, *, headers, payload, timeout_s=60.0):
        captured.update(payload)
        return {
            "choices": [{"message": {"content": "module x; endmodule"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr(openai_module, "post_json", fake_post)
    provider = OpenAIProvider(model, spend_path=tmp_path / "spend.json")
    params = GenParams(model=model, temperature=0.0, max_tokens=8, seed=0)

    assert provider.generate("prompt", "system", params) == "module x; endmodule"
    assert "temperature" not in captured
    assert provider.manifest_temperature == PROVIDER_DEFAULT_TEMPERATURE


def test_http_error_does_not_echo_response_body(monkeypatch):
    secret = "unit-test-key-must-not-leak"

    def fake_urlopen(*args, **kwargs):
        raise HTTPError(
            "https://provider.invalid",
            401,
            "unauthorized",
            {},
            BytesIO(f"reflected credential: {secret}".encode()),
        )

    monkeypatch.setattr(http_module, "urlopen", fake_urlopen)
    with pytest.raises(http_module.ProviderHTTPError) as caught:
        http_module.post_json(
            "https://provider.invalid",
            headers={"authorization": f"Bearer {secret}"},
            payload={"prompt": "hello"},
        )
    assert str(caught.value) == "provider HTTP 401"
    assert secret not in str(caught.value)
