"""Cumulative spend guard for model runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_SPEND_PATH = Path("results/spend.json")
DEFAULT_SPEND_CAP_USD = 300.0


class SpendCapExceeded(RuntimeError):
    """Raised when a model run would exceed the configured spend cap."""


def spend_cap_from_env() -> float:
    return float(os.environ.get("SILICONBENCH_SPEND_CAP_USD", DEFAULT_SPEND_CAP_USD))


def load_spend(path: str | Path = DEFAULT_SPEND_PATH) -> dict[str, Any]:
    spend_path = Path(path)
    if not spend_path.exists():
        return {"total_usd": 0.0, "runs": []}
    return json.loads(spend_path.read_text(encoding="utf-8"))


def save_spend(data: dict[str, Any], path: str | Path = DEFAULT_SPEND_PATH) -> None:
    spend_path = Path(path)
    spend_path.parent.mkdir(parents=True, exist_ok=True)
    spend_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    data = load_spend(path)
    total = float(data.get("total_usd", 0.0))
    if total + cost_usd > cap:
        raise SpendCapExceeded(f"spend cap exceeded: {total + cost_usd:.4f} > {cap:.4f}")
    run = {"provider": provider, "model": model, "cost_usd": cost_usd}
    if reservation:
        run["reservation"] = True
    data.setdefault("runs", []).append(run)
    data["total_usd"] = total + cost_usd
    save_spend(data, path)
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
    data = load_spend(path)
    runs = data.get("runs", [])
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

    total = float(data.get("total_usd", 0.0)) - reserved_usd + actual_usd
    match["cost_usd"] = actual_usd
    match.pop("reservation", None)
    data["total_usd"] = total
    save_spend(data, path)

    cap = spend_cap_from_env() if cap_usd is None else cap_usd
    if total > cap:
        raise SpendCapExceeded(
            f"actual spend exceeded cap after reservation: {total:.4f} > {cap:.4f}"
        )
    return data
