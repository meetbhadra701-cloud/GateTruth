import pytest

from harness.spend import (
    SpendCapExceeded,
    load_spend,
    reserve_spend,
    settle_spend_reservation,
)


def test_spend_guard_records_runs(tmp_path):
    path = tmp_path / "spend.json"
    data = reserve_spend(1.25, provider="test", model="m", path=path, cap_usd=2.0)

    assert data["total_usd"] == 1.25
    assert load_spend(path)["runs"][0]["provider"] == "test"


def test_spend_guard_blocks_over_cap(tmp_path):
    path = tmp_path / "spend.json"
    reserve_spend(1.5, provider="test", model="m", path=path, cap_usd=2.0)

    with pytest.raises(SpendCapExceeded):
        reserve_spend(0.6, provider="test", model="m", path=path, cap_usd=2.0)

def test_spend_reservation_settles_to_actual(tmp_path):
    path = tmp_path / "spend.json"
    reserve_spend(
        1.0,
        provider="test",
        model="m",
        path=path,
        cap_usd=2.0,
        reservation=True,
    )
    data = settle_spend_reservation(
        1.0,
        0.25,
        provider="test",
        model="m",
        path=path,
        cap_usd=2.0,
    )

    assert data["total_usd"] == 0.25
    assert data["runs"][0]["cost_usd"] == 0.25
    assert "reservation" not in data["runs"][0]
