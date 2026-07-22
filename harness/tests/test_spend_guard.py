import json
import subprocess
import sys
import time

import pytest

from harness import spend
from harness.spend import (
    SpendCapExceeded,
    load_spend,
    reserve_spend,
    save_spend,
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


def test_concurrent_processes_preserve_every_spend_record(tmp_path):
    path = tmp_path / "spend.json"
    process_count = 16
    cost_usd = 0.25
    start_at = time.time() + 1.0
    program = (
        "import sys,time; "
        "from harness.spend import reserve_spend; "
        "time.sleep(max(0.0, float(sys.argv[2]) - time.time())); "
        "reserve_spend(0.25, provider='worker', model=sys.argv[3], "
        "path=sys.argv[1], cap_usd=1000.0)"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", program, str(path), str(start_at), str(index)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for index in range(process_count)
    ]

    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stdout + stderr

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw == load_spend(path)
    assert raw["total_usd"] == process_count * cost_usd
    assert len(raw["runs"]) == process_count
    assert {run["model"] for run in raw["runs"]} == {
        str(index) for index in range(process_count)
    }


def test_atomic_replace_failure_preserves_previous_ledger(tmp_path, monkeypatch):
    path = tmp_path / "spend.json"
    original = {"total_usd": 1.0, "runs": [{"cost_usd": 1.0}]}
    save_spend(original, path)

    def fail_replace(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(spend.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        save_spend({"total_usd": 2.0, "runs": []}, path)

    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert list(tmp_path.glob(".spend.json.*.tmp")) == []
