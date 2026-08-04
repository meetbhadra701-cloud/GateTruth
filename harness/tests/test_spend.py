from __future__ import annotations

import json
import subprocess
import sys

import pytest

from harness.providers import GenParams
from harness.providers import anthropic as anthropic_module
from harness.providers._http import ProviderRetryableError
from harness.providers.anthropic import AnthropicProvider
from harness.spend import (
    SpendCapExceeded,
    load_spend,
    reconcile_spend_reservations,
    reserve_spend,
    settle_spend_reservation,
    spend_cap_from_env,
)


def test_spend_cap_prefers_gatetruth_and_supports_legacy(monkeypatch):
    monkeypatch.setenv("SILICONBENCH_SPEND_CAP_USD", "41")
    monkeypatch.delenv("GATETRUTH_SPEND_CAP_USD", raising=False)
    assert spend_cap_from_env() == 41.0

    monkeypatch.setenv("GATETRUTH_SPEND_CAP_USD", "17")
    assert spend_cap_from_env() == 17.0


def test_total_is_settled_only_but_cap_includes_reservations(tmp_path):
    path = tmp_path / "spend.json"
    reserve_spend(1.0, provider="test", model="m", path=path, cap_usd=3.0)
    reserved = reserve_spend(
        1.5,
        provider="test",
        model="m",
        path=path,
        cap_usd=3.0,
        reservation=True,
    )

    assert reserved["total_usd"] == 1.0
    with pytest.raises(SpendCapExceeded):
        reserve_spend(
            0.6,
            provider="test",
            model="second",
            path=path,
            cap_usd=3.0,
            reservation=True,
        )

    settled = settle_spend_reservation(
        1.5,
        0.25,
        provider="test",
        model="m",
        path=path,
        cap_usd=3.0,
    )
    assert settled["total_usd"] == 1.25
    assert all("reservation" not in run for run in settled["runs"])


def test_parse_error_releases_reservation_before_retry(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-key")
    responses = [
        {"content": [], "usage": {"input_tokens": 0, "output_tokens": 0}},
        {
            "content": [{"type": "text", "text": '{"tool":"done"}'}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
    ]

    def fake_post(*args, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(anthropic_module, "post_json", fake_post)
    path = tmp_path / "spend.json"
    provider = AnthropicProvider(
        "claude-haiku-4-5-20251001",
        spend_path=path,
    )
    params = GenParams(
        model=provider.model,
        temperature=0.0,
        max_tokens=8,
        seed=0,
    )

    with pytest.raises(ProviderRetryableError, match="contained no text"):
        provider.generate("prompt", "system", params)
    after_error = load_spend(path)
    assert after_error["total_usd"] == 0.0
    assert all("reservation" not in run for run in after_error["runs"])

    assert provider.generate("prompt", "system", params) == '{"tool":"done"}'
    after_retry = load_spend(path)
    assert after_retry["total_usd"] == provider.price.cost(10, 5)
    assert all("reservation" not in run for run in after_retry["runs"])


def test_over_cap_actual_is_settled_before_refusal(tmp_path):
    path = tmp_path / "spend.json"
    reserve_spend(
        0.5,
        provider="test",
        model="m",
        path=path,
        cap_usd=1.0,
        reservation=True,
    )

    with pytest.raises(SpendCapExceeded, match="actual spend exceeded cap"):
        settle_spend_reservation(
            0.5,
            2.0,
            provider="test",
            model="m",
            path=path,
            cap_usd=1.0,
        )

    ledger = load_spend(path)
    assert ledger["total_usd"] == 2.0
    assert all("reservation" not in run for run in ledger["runs"])


def test_reconciliation_cli_drops_only_orphaned_reservations(tmp_path):
    path = tmp_path / "spend.json"
    settled = [
        {"provider": "a", "model": "m1", "cost_usd": 1.25},
        {"provider": "b", "model": "m2", "cost_usd": 2.25, "note": "keep"},
    ]
    reservations = [
        {"provider": "a", "model": "m1", "cost_usd": 10.0, "reservation": True},
        {"provider": "b", "model": "m2", "cost_usd": 20.0, "reservation": True},
    ]
    historical = {"total_usd": 33.5, "runs": settled + reservations}
    path.write_text(json.dumps(historical, indent=2) + "\n", encoding="utf-8")

    audit = reconcile_spend_reservations(path)
    assert audit == {
        "reservations_removed": 2,
        "reserved_usd_removed": 30.0,
        "settled_entries": 2,
        "total_usd": 3.5,
    }
    assert json.loads(path.read_text(encoding="utf-8")) == historical
    assert load_spend(path)["total_usd"] == 3.5

    result = subprocess.run(
        [
            sys.executable,
            "scripts/reconcile_spend.py",
            "--path",
            str(path),
            "--write",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"mode": "write", **audit}
    reconciled = json.loads(path.read_text(encoding="utf-8"))
    assert reconciled == {"total_usd": 3.5, "runs": settled}


def test_reserve_spend_rejects_nan_and_infinite_cost(tmp_path):
    path = tmp_path / "spend.json"
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finite and non-negative"):
            reserve_spend(bad, provider="test", model="m", path=path, cap_usd=10.0)
    assert not path.exists()


def test_settle_spend_reservation_rejects_nan_and_infinite_values(tmp_path):
    path = tmp_path / "spend.json"
    reserve_spend(1.0, provider="test", model="m", path=path, cap_usd=10.0, reservation=True)
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="finite and non-negative"):
            settle_spend_reservation(
                bad, 0.5, provider="test", model="m", path=path, cap_usd=10.0
            )
        with pytest.raises(ValueError, match="finite and non-negative"):
            settle_spend_reservation(
                1.0, bad, provider="test", model="m", path=path, cap_usd=10.0
            )


def test_spend_cap_from_env_rejects_non_finite_value(monkeypatch):
    monkeypatch.setenv("GATETRUTH_SPEND_CAP_USD", "nan")
    with pytest.raises(ValueError, match="finite and non-negative"):
        spend_cap_from_env()

    monkeypatch.setenv("GATETRUTH_SPEND_CAP_USD", "inf")
    with pytest.raises(ValueError, match="finite and non-negative"):
        spend_cap_from_env()


def test_a_nan_cost_already_in_the_ledger_is_rejected_on_load_not_silently_trusted(
    tmp_path,
):
    """A NaN cost_usd surviving into the ledger (e.g. hand-edited, or written by a
    version of the harness that predates this check) must not be silently summed --
    `nan < 0` is false, so a naive non-negativity check alone would let it through and
    poison every downstream total, and worse, make the cap's own `> cap` comparison
    silently false (fail-open) for every run after it."""

    path = tmp_path / "spend.json"
    path.write_text(
        json.dumps(
            {
                "total_usd": 0.0,
                "runs": [{"provider": "test", "model": "m", "cost_usd": float("nan")}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="finite and non-negative"):
        load_spend(path)
