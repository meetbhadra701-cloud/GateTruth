"""Cumulative spend guard for model runs."""

from __future__ import annotations

import json
import math
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import fcntl

DEFAULT_SPEND_PATH = Path("results/spend.json")
DEFAULT_SPEND_CAP_USD = 300.0


class SpendCapExceeded(RuntimeError):
    """Raised when a model run would exceed the configured spend cap."""


def spend_cap_from_env() -> float:
    return float(os.environ.get("SILICONBENCH_SPEND_CAP_USD", DEFAULT_SPEND_CAP_USD))


def load_spend(path: str | Path = DEFAULT_SPEND_PATH) -> dict[str, Any]:
    spend_path = Path(path)
    with _spend_lock(spend_path):
        return _load_spend_unlocked(spend_path)


def save_spend(data: dict[str, Any], path: str | Path = DEFAULT_SPEND_PATH) -> None:
    spend_path = Path(path)
    with _spend_lock(spend_path):
        normalized = dict(data)
        _normalize_total(normalized)
        _save_spend_unlocked(normalized, spend_path)


@contextmanager
def _spend_lock(spend_path: Path) -> Iterator[None]:
    spend_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = spend_path.with_name(f"{spend_path.name}.lock")
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_spend_unlocked(spend_path: Path) -> dict[str, Any]:
    if not spend_path.exists():
        return {"total_usd": 0.0, "runs": []}
    data = json.loads(spend_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("spend ledger must be a JSON object")
    _normalize_total(data)
    return data


def _ledger_runs(data: dict[str, Any]) -> list[dict[str, Any]]:
    runs = data.setdefault("runs", [])
    if not isinstance(runs, list) or not all(isinstance(run, dict) for run in runs):
        raise ValueError("spend ledger runs must be a list of objects")
    return runs


def _run_cost(run: dict[str, Any]) -> float:
    cost = float(run.get("cost_usd", -1.0))
    if cost < 0:
        raise ValueError("spend ledger run costs must be non-negative")
    return cost


def _settled_total(runs: list[dict[str, Any]]) -> float:
    return math.fsum(
        _run_cost(run)
        for run in runs
        if run.get("reservation") is not True
    )


def _committed_total(runs: list[dict[str, Any]]) -> float:
    return math.fsum(_run_cost(run) for run in runs)


def _normalize_total(data: dict[str, Any]) -> None:
    data["total_usd"] = _settled_total(_ledger_runs(data))


def _save_spend_unlocked(data: dict[str, Any], spend_path: Path) -> None:
    spend_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{spend_path.name}.",
        suffix=".tmp",
        dir=spend_path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as temp_file:
            temp_file.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, spend_path)
    finally:
        temp_path.unlink(missing_ok=True)


def reserve_spend(
    cost_usd: float,
    *,
    provider: str,
    model: str,
    path: str | Path = DEFAULT_SPEND_PATH,
    cap_usd: float | None = None,
    reservation: bool = False,
) -> dict[str, Any]:
    if cost_usd < 0:
        raise ValueError("cost_usd must be non-negative")
    cap = spend_cap_from_env() if cap_usd is None else cap_usd
    spend_path = Path(path)
    with _spend_lock(spend_path):
        data = _load_spend_unlocked(spend_path)
        runs = _ledger_runs(data)
        committed = _committed_total(runs)
        if committed + cost_usd > cap:
            raise SpendCapExceeded(
                f"spend cap exceeded: {committed + cost_usd:.4f} > {cap:.4f}"
            )
        run = {"provider": provider, "model": model, "cost_usd": cost_usd}
        if reservation:
            run["reservation"] = True
        runs.append(run)
        data["total_usd"] = _settled_total(runs)
        _save_spend_unlocked(data, spend_path)
        return data


def settle_spend_reservation(
    reserved_usd: float,
    actual_usd: float,
    *,
    provider: str,
    model: str,
    path: str | Path = DEFAULT_SPEND_PATH,
    cap_usd: float | None = None,
) -> dict[str, Any]:
    """Replace the latest matching reservation with the API-reported actual cost."""

    if reserved_usd < 0 or actual_usd < 0:
        raise ValueError("spend values must be non-negative")
    spend_path = Path(path)
    with _spend_lock(spend_path):
        data = _load_spend_unlocked(spend_path)
        runs = _ledger_runs(data)
        match = None
        for run in reversed(runs):
            if (
                run.get("reservation") is True
                and run.get("provider") == provider
                and run.get("model") == model
                and abs(float(run.get("cost_usd", -1.0)) - reserved_usd) < 1e-12
            ):
                match = run
                break
        if match is None:
            raise ValueError("matching spend reservation not found")

        match["cost_usd"] = actual_usd
        match.pop("reservation", None)
        data["total_usd"] = _settled_total(runs)
        committed = _committed_total(runs)
        _save_spend_unlocked(data, spend_path)

    cap = spend_cap_from_env() if cap_usd is None else cap_usd
    if committed > cap:
        raise SpendCapExceeded(
            "actual spend exceeded cap after reservation: "
            f"{committed:.4f} > {cap:.4f}"
        )
    return data


def reconcile_spend_reservations(
    path: str | Path = DEFAULT_SPEND_PATH,
    *,
    write: bool = False,
) -> dict[str, int | float]:
    """Report or remove outstanding reservations while preserving settled runs."""

    spend_path = Path(path)
    with _spend_lock(spend_path):
        data = _load_spend_unlocked(spend_path)
        runs = _ledger_runs(data)
        reservations = [run for run in runs if run.get("reservation") is True]
        settled = [run for run in runs if run.get("reservation") is not True]
        total = _settled_total(settled)
        summary: dict[str, int | float] = {
            "reservations_removed": len(reservations),
            "reserved_usd_removed": _committed_total(reservations),
            "settled_entries": len(settled),
            "total_usd": total,
        }
        if write:
            data["runs"] = settled
            data["total_usd"] = total
            _save_spend_unlocked(data, spend_path)
        return summary
