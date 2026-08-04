"""Hidden-vector loader and official fail-closed regressions."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import cocotb
import pytest

from harness.hidden import (
    HIDDEN_LOADED_KEY,
    HIDDEN_REPORT_ENV,
    HIDDEN_ROOT_ENV,
    LEGACY_HIDDEN_REPORT_ENV,
    LEGACY_HIDDEN_ROOT_ENV,
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
    monkeypatch.delenv(LEGACY_HIDDEN_ROOT_ENV, raising=False)
    namespace: dict[str, object] = {}

    assert load_hidden(namespace, "demo") == 0
    assert namespace[HIDDEN_LOADED_KEY] == 0


def test_primary_hidden_root_wins_and_legacy_root_remains_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary_root = tmp_path / "primary"
    legacy_root = tmp_path / "legacy"
    _write_hidden(
        primary_root,
        "demo",
        """
import cocotb

@cocotb.test()
async def hidden_primary(dut):
    pass
""",
    )
    _write_hidden(
        legacy_root,
        "demo",
        """
import cocotb

@cocotb.test()
async def hidden_legacy(dut):
    pass
""",
    )
    monkeypatch.setenv(HIDDEN_ROOT_ENV, str(primary_root))
    monkeypatch.setenv(LEGACY_HIDDEN_ROOT_ENV, str(legacy_root))

    primary_namespace: dict[str, object] = {}
    assert load_hidden(primary_namespace, "demo") == 1
    assert "hidden_primary" in primary_namespace
    assert "hidden_legacy" not in primary_namespace

    monkeypatch.delenv(HIDDEN_ROOT_ENV)
    legacy_namespace: dict[str, object] = {}
    assert load_hidden(legacy_namespace, "demo") == 1
    assert "hidden_legacy" in legacy_namespace


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
    legacy_report = tmp_path / "legacy-report.json"
    monkeypatch.setenv(HIDDEN_ROOT_ENV, str(root))
    monkeypatch.setenv(HIDDEN_REPORT_ENV, str(report))
    monkeypatch.setenv(LEGACY_HIDDEN_REPORT_ENV, str(legacy_report))
    namespace = {"cocotb": cocotb, "helper": lambda: 7}

    assert load_hidden(namespace, "demo") == 2
    assert list(namespace)[-2:] == ["hidden_alpha", "hidden_zeta"]
    assert isinstance(namespace["hidden_alpha"], cocotb.test)
    assert namespace[HIDDEN_LOADED_KEY] == 2
    assert '"count":2' in report.read_text(encoding="utf-8")
    assert not legacy_report.exists()

    monkeypatch.delenv(HIDDEN_REPORT_ENV)
    assert load_hidden({"cocotb": cocotb, "helper": lambda: 7}, "demo") == 2
    assert '"count":2' in legacy_report.read_text(encoding="utf-8")


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


def test_hidden_test_name_collision_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "hidden"
    _write_hidden(
        root,
        "demo",
        """
@cocotb.test()
async def hidden_collision(dut):
    pass
""",
    )
    monkeypatch.setenv(HIDDEN_ROOT_ENV, str(root))

    async def public_collision(_dut):
        pass

    namespace = {
        "cocotb": cocotb,
        "hidden_collision": cocotb.test()(public_collision),
    }
    with pytest.raises(HiddenTestError, match="collide.*hidden_collision"):
        load_hidden(namespace, "demo")


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

    stage, log, _hidden_sha256, _hidden_test_count = run_sim(
        task,
        tmp_path / "ref.sv",
        tmp_path / "work",
        official=True,
    )

    assert stage["status"] == "fail"
    assert HIDDEN_FAILURE_PREFIX in log
    assert HIDDEN_ROOT_ENV in log


def test_official_hidden_tests_are_staged_without_exposing_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_root = tmp_path / "tasks" / "demo"
    tb_dir = task_root / "tb"
    tb_dir.mkdir(parents=True)
    (tb_dir / "test_demo.py").write_text(
        """
import json
import os

import cocotb

from harness.hidden import load_hidden


@cocotb.test()
async def smoke_environment(dut):
    print("SB_CHILD_ENV=" + json.dumps(dict(os.environ), sort_keys=True))


load_hidden(globals(), "demo")
""".lstrip(),
        encoding="utf-8",
    )
    source = tmp_path / "demo.sv"
    source.write_text("module demo; endmodule\n", encoding="utf-8")
    hidden_root = tmp_path / "hidden-secret-root"
    hidden_path = _write_hidden(
        hidden_root,
        "demo",
        """
@cocotb.test()
async def hidden_loaded(dut):
    assert "GATETRUTH_HIDDEN_ROOT" not in os.environ
    assert "SILICONBENCH_HIDDEN_ROOT" not in os.environ
""".lstrip(),
    )
    monkeypatch.setenv(HIDDEN_ROOT_ENV, str(hidden_root))
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret-value")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret-value")
    work_root = tmp_path / "work"
    work_root.mkdir()
    task = TaskPackage(
        task_id="demo",
        root=task_root,
        task_yaml=SimpleNamespace(formal=False),
        top_module="demo",
    )

    stage, log, hidden_sha256, hidden_test_count = run_sim(
        task,
        source,
        work_root,
        official=True,
    )

    assert stage["status"] == "pass"
    assert stage["tests_run"] == 2
    assert "OPENAI_API_KEY" not in log
    assert "ANTHROPIC_API_KEY" not in log
    assert HIDDEN_ROOT_ENV not in log
    assert LEGACY_HIDDEN_ROOT_ENV not in log
    assert "openai-secret-value" not in log
    assert "anthropic-secret-value" not in log
    # The hidden module defines exactly one test (hidden_loaded); the public smoke
    # test brings tests_run to 2. The hash binds this manifest to that exact hidden
    # module revision without the hash itself revealing anything about its content.
    assert hidden_test_count == 1
    assert hidden_sha256 == hashlib.sha256(
        hidden_path.read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()
    assert hidden_sha256 not in log


def test_official_staging_rejects_hidden_public_name_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_root = tmp_path / "tasks" / "demo"
    tb_dir = task_root / "tb"
    tb_dir.mkdir(parents=True)
    (tb_dir / "test_demo.py").write_text(
        """
import cocotb

from harness.hidden import load_hidden


@cocotb.test()
async def hidden_collision(dut):
    pass


load_hidden(globals(), "demo")
""".lstrip(),
        encoding="utf-8",
    )
    hidden_root = tmp_path / "hidden"
    _write_hidden(
        hidden_root,
        "demo",
        """
@cocotb.test()
async def hidden_collision(dut):
    pass
""".lstrip(),
    )
    monkeypatch.setenv(HIDDEN_ROOT_ENV, str(hidden_root))
    work_root = tmp_path / "work"
    work_root.mkdir()
    task = TaskPackage(
        task_id="demo",
        root=task_root,
        task_yaml=SimpleNamespace(formal=False),
        top_module="demo",
    )

    stage, log, _hidden_sha256, _hidden_test_count = run_sim(
        task,
        tmp_path / "unused.sv",
        work_root,
        official=True,
    )

    assert stage["status"] == "fail"
    assert HIDDEN_FAILURE_PREFIX in log
    assert "collide" in log
    assert "hidden_collision" in log
