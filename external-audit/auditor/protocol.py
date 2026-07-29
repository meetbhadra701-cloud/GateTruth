"""Protocol shared by external benchmark testbench adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    TIMEOUT = "timeout"
    NOT_RUNNABLE = "not-runnable"


@dataclass(frozen=True)
class TbResult:
    verdict: Verdict
    killed_by: str | None


class TestbenchRunner(Protocol):
    suite: str

    def run(
        self,
        design_id: str,
        rtl_source: str,
        work_dir: Path,
        *,
        timeout_s: float,
    ) -> TbResult: ...
