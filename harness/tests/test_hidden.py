"""Hidden-vector loader and official fail-closed regressions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import cocotb
import pytest

from harness.hidden import (
    HIDDEN_LOADED_KEY,
    HIDDEN_REPORT_ENV,
    HIDDEN_ROOT_ENV,
    HiddenTestError,
    load_hidden,
)
from harness.runner import HIDDEN_FAILURE_PREFIX, TaskPackage, run_sim


def _write_hidden(root: Path, task_id: str, source: str) -> Path:
    path = root / "tasks" / task_id / f"hidden_{task_id}.py"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    return path


def test_unset_root_is_smoke_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HIDDEN_ROOT_ENV, raising=False)
    namespace: dict[str, object] = {}

    assert load_hidden(namespace, "demo") == 0
    assert namespace[HIDDEN_LOADED_KEY] == 0


def test_present_root_loads_hidden_tests_in_name_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "hidden"
    _write_hidden(
        root,
        "demo",
        """
@cocotb.test()
async def hidden_zeta(dut):
    assert helper() == 7

@cocotb.test()
async def hidden_alpha(dut):
    assert helper() == 7
""",
    )
    report = tmp_path / "report.json"
    monkeypatch.setenv(HIDDEN_ROOT_ENV, str(root))
    monkeypatch.setenv(HIDDEN_REPORT_ENV, str(report))
    namespace = {"cocotb": cocotb, "helper": lambda: 7}

    assert load_hidden(namespace, "demo") == 2
    assert list(namespace)[-2:] == ["hidden_alpha", "hidden_zeta"]
    assert isinstance(namespace["hidden_alpha"], cocotb.test)
    assert namespace[HIDDEN_LOADED_KEY] == 2
    assert '"count":2' in report.read_text(encoding="utf-8")


def test_configured_missing_module_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(HIDDEN_ROOT_ENV, str(tmp_path))

    with pytest.raises(HiddenTestError, match="hidden module missing"):
        load_hidden({}, "demo")


def test_configured_malformed_module_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "hidden"
    _write_hidden(root, "demo", "not_a_test = 1\n")
    monkeypatch.setenv(HIDDEN_ROOT_ENV, str(root))

    with pytest.raises(HiddenTestError, match="defines no cocotb tests"):
        load_hidden({}, "demo")


def test_official_registered_task_fails_closed_without_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(HIDDEN_ROOT_ENV, raising=False)
    task_root = tmp_path / "tasks" / "demo"
    task = TaskPackage(
        task_id="demo",
        root=task_root,
        task_yaml=SimpleNamespace(formal=False),
        top_module="demo",
    )

    stage, log = run_sim(
        task,
        tmp_path / "ref.sv",
        tmp_path / "work",
        official=True,
    )

    assert stage["status"] == "fail"
    assert HIDDEN_FAILURE_PREFIX in log
    assert HIDDEN_ROOT_ENV in log
