from __future__ import annotations

from http.client import IncompleteRead
from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from harness.providers import GenParams
from harness.providers import _http as http_module
from harness.providers import anthropic as anthropic_module
from harness.providers import openai as openai_module
from harness.providers import openrouter as openrouter_module
from harness.providers._http import PROVIDER_READ_TIMEOUT_S
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
            "stop_reason": "end_turn",
        }

    monkeypatch.setattr(anthropic_module, "post_json", fake_post)
    spend = tmp_path / "spend.json"
    provider = AnthropicProvider(PARAMS_ANTHROPIC.model, spend_path=spend)

    assert provider.generate("prompt", "system", PARAMS_ANTHROPIC) == '{"tool":"done"}'
    assert captured["url"] == anthropic_module.API_URL
    assert captured["payload"]["max_tokens"] == 100
    assert captured["payload"]["temperature"] == 0.0
    assert captured["timeout_s"] == PROVIDER_READ_TIMEOUT_S
    assert provider.usage == {"tokens_in": 100, "tokens_out": 20, "cost_usd": 0.0002}
    assert provider.last_finish_reason == "end_turn"
    recorded = load_spend(spend)
    assert recorded["total_usd"] == pytest.approx(0.0002)
    assert "reservation" not in recorded["runs"][0]


def test_anthropic_max_tokens_stop_reason_is_recorded(tmp_path, monkeypatch):
    """The paper's token-budget claims (Section 5, Table budget) currently infer truncation
    from an absent or malformed extraction alone; stop_reason="max_tokens" is the provider's
    own direct confirmation that the cap, not something else, ended generation. Regression
    test: this must actually reach provider.last_finish_reason, not just be present in the
    raw HTTP response and then discarded."""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-key")

    def fake_post(url, *, headers, payload, timeout_s=60.0):
        return {
            "content": [{"type": "text", "text": "```systemverilog\nmodule x; // truncated"}],
            "usage": {"input_tokens": 500, "output_tokens": 4096},
            "stop_reason": "max_tokens",
        }

    monkeypatch.setattr(anthropic_module, "post_json", fake_post)
    provider = AnthropicProvider(PARAMS_ANTHROPIC.model, spend_path=tmp_path / "spend.json")

    provider.generate("prompt", "system", PARAMS_ANTHROPIC)

    assert provider.last_finish_reason == "max_tokens"


def test_anthropic_empty_billed_response_settles_real_cost_not_zero(tmp_path, monkeypatch):
    """A provider can bill an attempt that comes back with no usable text; the
    usage block in that same response is the only record of that cost, so it
    must be settled for real rather than the reservation released at zero.
    A subsequent successful retry's usage must add to, not replace, that
    already-settled cost."""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-key")
    responses = [
        {
            "content": [{"type": "text", "text": "   "}],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        },
        {
            "content": [{"type": "text", "text": '{"tool":"done"}'}],
            "usage": {"input_tokens": 100, "output_tokens": 15},
        },
    ]

    def fake_post(url, *, headers, payload, timeout_s=60.0):
        return responses.pop(0)

    monkeypatch.setattr(anthropic_module, "post_json", fake_post)
    spend = tmp_path / "spend.json"
    provider = AnthropicProvider(PARAMS_ANTHROPIC.model, spend_path=spend)

    with pytest.raises(anthropic_module.ProviderRetryableError, match="no text"):
        provider.generate("prompt", "system", PARAMS_ANTHROPIC)
    first_cost = provider.usage["cost_usd"]
    assert first_cost > 0, "an empty-text attempt with real usage must not settle at zero"
    assert provider.usage == {"tokens_in": 100, "tokens_out": 20, "cost_usd": pytest.approx(0.0002)}

    assert provider.generate("prompt", "system", PARAMS_ANTHROPIC) == '{"tool":"done"}'
    assert provider.usage["tokens_in"] == 200
    assert provider.usage["tokens_out"] == 35
    assert provider.usage["cost_usd"] == pytest.approx(first_cost + 0.000175)
    recorded = load_spend(spend)
    assert recorded["total_usd"] == pytest.approx(provider.usage["cost_usd"])


def test_openai_empty_billed_response_settles_real_cost_not_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")
    responses = [
        {
            "choices": [{"message": {"content": ""}}],
            "usage": {"prompt_tokens": 80, "completion_tokens": 10},
        },
        {
            "choices": [{"message": {"content": '{"tool":"sb_lint"}'}}],
            "usage": {"prompt_tokens": 80, "completion_tokens": 8},
        },
    ]

    def fake_post(url, *, headers, payload, timeout_s=60.0):
        return responses.pop(0)

    monkeypatch.setattr(openai_module, "post_json", fake_post)
    spend = tmp_path / "spend.json"
    provider = OpenAIProvider(PARAMS_OPENAI.model, spend_path=spend)

    with pytest.raises(openai_module.ProviderRetryableError, match="no text"):
        provider.generate("prompt", "system", PARAMS_OPENAI)
    assert provider.usage == {"tokens_in": 80, "tokens_out": 10, "cost_usd": pytest.approx(0.00004)}

    assert provider.generate("prompt", "system", PARAMS_OPENAI) == '{"tool":"sb_lint"}'
    assert provider.usage["tokens_in"] == 160
    assert provider.usage["tokens_out"] == 18
    recorded = load_spend(spend)
    assert recorded["total_usd"] == pytest.approx(provider.usage["cost_usd"])


def test_openrouter_empty_billed_response_settles_real_cost_not_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "unit-test-key")
    responses = [
        {
            "choices": [{"message": {"content": None}}],
            "usage": {"prompt_tokens": 90, "completion_tokens": 12},
        },
        {
            "choices": [{"message": {"content": '{"tool":"read_file","path":"spec.md"}'}}],
            "usage": {"prompt_tokens": 90, "completion_tokens": 9},
        },
    ]

    def fake_post(url, *, headers, payload, timeout_s=60.0):
        return responses.pop(0)

    monkeypatch.setattr(openrouter_module, "post_json", fake_post)
    spend = tmp_path / "spend.json"
    provider = OpenRouterProvider(PARAMS_OPENROUTER.model, spend_path=spend)

    with pytest.raises(openrouter_module.ProviderRetryableError, match="no text"):
        provider.generate("prompt", "system", PARAMS_OPENROUTER)
    assert provider.usage == {"tokens_in": 90, "tokens_out": 12, "cost_usd": pytest.approx(0.00015)}

    assert (
        provider.generate("prompt", "system", PARAMS_OPENROUTER)
        == '{"tool":"read_file","path":"spec.md"}'
    )
    assert provider.usage["tokens_in"] == 180
    assert provider.usage["tokens_out"] == 21
    recorded = load_spend(spend)
    assert recorded["total_usd"] == pytest.approx(provider.usage["cost_usd"])


def test_openai_empty_choices_list_still_settles_usage(tmp_path, monkeypatch):
    """The empty-choices and null-content cases share the same accounting
    fix as the empty-string case above; this covers the other branch."""

    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")

    def fake_post(url, *, headers, payload, timeout_s=60.0):
        return {"choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 0}}

    monkeypatch.setattr(openai_module, "post_json", fake_post)
    spend = tmp_path / "spend.json"
    provider = OpenAIProvider(PARAMS_OPENAI.model, spend_path=spend)

    with pytest.raises(openai_module.ProviderRetryableError, match="empty"):
        provider.generate("prompt", "system", PARAMS_OPENAI)
    assert provider.usage == {"tokens_in": 50, "tokens_out": 0, "cost_usd": pytest.approx(0.0000125)}
    assert provider.last_finish_reason is None


def test_openai_adapter_parses_recorded_chat_response(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")

    def fake_post(url, *, headers, payload, timeout_s=60.0):
        assert url == openai_module.API_URL
        assert headers["authorization"].startswith("Bearer ")
        assert payload["max_completion_tokens"] == 100
        assert payload["seed"] == 7
        assert "temperature" not in payload
        assert timeout_s == PROVIDER_READ_TIMEOUT_S
        return {
            "choices": [{"message": {"content": '{"tool":"sb_lint"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 80, "completion_tokens": 10},
        }

    monkeypatch.setattr(openai_module, "post_json", fake_post)
    provider = OpenAIProvider(PARAMS_OPENAI.model, spend_path=tmp_path / "spend.json")

    assert provider.generate("prompt", "system", PARAMS_OPENAI) == '{"tool":"sb_lint"}'
    assert provider.usage["tokens_in"] == 80
    assert provider.usage["tokens_out"] == 10
    assert provider.usage["cost_usd"] == pytest.approx(0.00004)
    assert provider.last_finish_reason == "stop"


def test_openai_length_finish_reason_is_recorded(tmp_path, monkeypatch):
    """Same regression concern as the Anthropic max_tokens test: GPT-5's 22-of-60 no-extraction
    count (Section 5) is currently inferred, not directly confirmed by the provider's own
    finish_reason="length"."""

    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")

    def fake_post(url, *, headers, payload, timeout_s=60.0):
        return {
            "choices": [
                {"message": {"content": "```systemverilog\nmodule x;"}, "finish_reason": "length"}
            ],
            "usage": {"prompt_tokens": 500, "completion_tokens": 4096},
        }

    monkeypatch.setattr(openai_module, "post_json", fake_post)
    provider = OpenAIProvider(PARAMS_OPENAI.model, spend_path=tmp_path / "spend.json")

    provider.generate("prompt", "system", PARAMS_OPENAI)

    assert provider.last_finish_reason == "length"


def test_openrouter_adapter_parses_recorded_chat_response(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "unit-test-key")

    def fake_post(url, *, headers, payload, timeout_s=60.0):
        assert url == openrouter_module.API_URL
        assert headers["authorization"].startswith("Bearer ")
        assert payload["max_tokens"] == 100
        assert payload["temperature"] == 0.0
        assert timeout_s == PROVIDER_READ_TIMEOUT_S
        return {
            "choices": [
                {
                    "message": {"content": '{"tool":"read_file","path":"spec.md"}'},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 90, "completion_tokens": 12},
        }

    monkeypatch.setattr(openrouter_module, "post_json", fake_post)
    provider = OpenRouterProvider(PARAMS_OPENROUTER.model, spend_path=tmp_path / "spend.json")

    text = provider.generate("prompt", "system", PARAMS_OPENROUTER)
    assert text == '{"tool":"read_file","path":"spec.md"}'
    assert provider.usage["tokens_in"] == 90
    assert provider.usage["tokens_out"] == 12
    assert provider.usage["cost_usd"] == pytest.approx(0.00015)
    assert provider.last_finish_reason == "stop"


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


def test_openrouter_reasoning_model_omits_temperature_like_native_openai(
    tmp_path,
    monkeypatch,
):
    """An OpenRouter-routed reasoning model must send the identical request shape
    as OpenAIProvider would for the same underlying model -- specifically, no
    explicit temperature field."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "unit-test-key")
    captured: dict[str, Any] = {}

    def fake_post(url, *, headers, payload, timeout_s=60.0):
        captured.update(payload)
        return {
            "choices": [{"message": {"content": "module x; endmodule"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr(openrouter_module, "post_json", fake_post)
    provider = OpenRouterProvider("openai/gpt-5-mini", spend_path=tmp_path / "spend.json")
    params = GenParams(model="openai/gpt-5-mini", temperature=0.0, max_tokens=8, seed=0)

    assert provider.generate("prompt", "system", params) == "module x; endmodule"
    assert "temperature" not in captured
    assert provider.manifest_temperature == PROVIDER_DEFAULT_TEMPERATURE


def test_openrouter_non_reasoning_model_still_sends_temperature(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("OPENROUTER_API_KEY", "unit-test-key")
    captured: dict[str, Any] = {}

    def fake_post(url, *, headers, payload, timeout_s=60.0):
        captured.update(payload)
        return {
            "choices": [{"message": {"content": "module x; endmodule"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    monkeypatch.setattr(openrouter_module, "post_json", fake_post)
    provider = OpenRouterProvider(
        "google/gemini-2.5-pro", temperature=0.0, spend_path=tmp_path / "spend.json"
    )
    params = GenParams(model="google/gemini-2.5-pro", temperature=0.0, max_tokens=8, seed=0)

    assert provider.generate("prompt", "system", params) == "module x; endmodule"
    assert captured["temperature"] == 0.0
    assert provider.manifest_temperature == 0.0


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


@pytest.mark.parametrize(
    "status",
    sorted(http_module.RETRYABLE_HTTP_STATUS_CODES),
)
def test_transient_http_statuses_are_classified_retryable(monkeypatch, status):
    def fake_urlopen(*args, **kwargs):
        raise HTTPError(
            "https://provider.invalid",
            status,
            "transient",
            {},
            BytesIO(b"temporary failure"),
        )

    monkeypatch.setattr(http_module, "urlopen", fake_urlopen)
    with pytest.raises(http_module.ProviderRetryableError, match=f"HTTP {status}"):
        http_module.post_json(
            "https://provider.invalid",
            headers={},
            payload={"prompt": "hello"},
        )


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_deterministic_http_statuses_remain_terminal(monkeypatch, status):
    def fake_urlopen(*args, **kwargs):
        raise HTTPError(
            "https://provider.invalid",
            status,
            "terminal",
            {},
            BytesIO(b"bad request"),
        )

    monkeypatch.setattr(http_module, "urlopen", fake_urlopen)
    with pytest.raises(http_module.ProviderHTTPError, match=f"HTTP {status}") as caught:
        http_module.post_json(
            "https://provider.invalid",
            headers={},
            payload={"prompt": "hello"},
        )
    assert not isinstance(caught.value, http_module.ProviderRetryableError)


def test_incomplete_response_body_is_classified_retryable(monkeypatch):
    def fake_urlopen(*args, **kwargs):
        raise IncompleteRead(b'{"partial":', 20)

    monkeypatch.setattr(http_module, "urlopen", fake_urlopen)
    with pytest.raises(
        http_module.ProviderRetryableError,
        match="incomplete",
    ):
        http_module.post_json(
            "https://provider.invalid",
            headers={},
            payload={"prompt": "hello"},
        )


def test_invalid_json_response_is_classified_retryable(monkeypatch):
    monkeypatch.setattr(
        http_module,
        "urlopen",
        lambda *args, **kwargs: BytesIO(b"{not-json"),
    )
    with pytest.raises(
        http_module.ProviderRetryableError,
        match="invalid JSON",
    ):
        http_module.post_json(
            "https://provider.invalid",
            headers={},
            payload={"prompt": "hello"},
        )


@pytest.mark.parametrize("failure", [URLError("offline"), TimeoutError()])
def test_transport_failures_are_classified_retryable(monkeypatch, failure):
    def fake_urlopen(*args, **kwargs):
        raise failure

    monkeypatch.setattr(http_module, "urlopen", fake_urlopen)
    with pytest.raises(http_module.ProviderTransportError):
        http_module.post_json(
            "https://provider.invalid",
            headers={},
            payload={"prompt": "hello"},
        )
