"""Private hidden-test loader used by split GateTruth testbenches."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import cocotb

from harness.env_compat import read_env

HIDDEN_ROOT_ENV = "GATETRUTH_HIDDEN_ROOT"
LEGACY_HIDDEN_ROOT_ENV = "SILICONBENCH_HIDDEN_ROOT"
HIDDEN_REPORT_ENV = "GATETRUTH_HIDDEN_REPORT"
LEGACY_HIDDEN_REPORT_ENV = "SILICONBENCH_HIDDEN_REPORT"
HIDDEN_LOADED_KEY = "__gatetruth_hidden_loaded__"
TASK_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")
HIDDEN_KINDS = ("tasks", "tasksB")
_RESERVED_MODULE_KEYS = {
    "__builtins__",
    "__cached__",
    "__file__",
    "__loader__",
    "__name__",
    "__package__",
    "__spec__",
}


class HiddenTestError(RuntimeError):
    """Raised when a configured private hidden-test module is unusable."""


def load_hidden(module_globals: dict[str, Any], task_id: str) -> int:
    """Load a task's private cocotb tests into its public testbench namespace."""

    module_globals[HIDDEN_LOADED_KEY] = 0
    root_value = read_env("HIDDEN_ROOT")
    if not root_value:
        return 0

    public_values = {
        name: value
        for name, value in module_globals.items()
        if name != HIDDEN_LOADED_KEY
    }
    hidden_path, kind = resolve_hidden_module(root_value, task_id)
    module = _load_module(hidden_path, task_id, module_globals)
    declared_tests = [
        (name, value)
        for name, value in module.__dict__.items()
        if isinstance(value, cocotb.test)
        and (
            name not in public_values
            or value is not public_values[name]
        )
    ]
    declared_tests.sort(key=lambda item: item[0])
    if not declared_tests:
        raise HiddenTestError(f"hidden module defines no cocotb tests: {hidden_path}")

    duplicates = [name for name, _ in declared_tests if name in public_values]
    if duplicates:
        raise HiddenTestError(
            f"hidden test names collide with public names for {task_id}: "
            + ", ".join(duplicates)
        )
    for name, test in declared_tests:
        module_globals[name] = test

    count = len(declared_tests)
    module_globals[HIDDEN_LOADED_KEY] = count
    _write_report(task_id=task_id, kind=kind, path=hidden_path, count=count)
    return count


def resolve_hidden_module(
    root: str | Path,
    task_id: str,
    *,
    kind: str | None = None,
) -> tuple[Path, str]:
    """Resolve one registered hidden module below a mounted hidden root."""

    if TASK_ID_RE.fullmatch(task_id) is None:
        raise HiddenTestError(f"invalid hidden task id: {task_id!r}")
    if kind is not None and kind not in HIDDEN_KINDS:
        raise HiddenTestError(f"invalid hidden task kind: {kind!r}")

    hidden_root = Path(root).expanduser().resolve()
    kinds = (kind,) if kind is not None else HIDDEN_KINDS
    matches = [
        (hidden_root / candidate / task_id / f"hidden_{task_id}.py", candidate)
        for candidate in kinds
    ]
    present = [(path, candidate) for path, candidate in matches if path.is_file()]
    if len(present) == 1:
        return present[0]
    if len(present) > 1:
        raise HiddenTestError(
            f"ambiguous hidden module for {task_id}: "
            + ", ".join(str(path) for path, _ in present)
        )
    expected = ", ".join(str(path) for path, _ in matches)
    raise HiddenTestError(f"hidden module missing for {task_id}; expected {expected}")


def _load_module(
    path: Path,
    task_id: str,
    public_globals: dict[str, Any],
) -> ModuleType:
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    module_name = f"_gatetruth_hidden_{task_id}_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise HiddenTestError(f"cannot create import spec for hidden module: {path}")
    module = importlib.util.module_from_spec(spec)
    for name, value in public_globals.items():
        if name not in _RESERVED_MODULE_KEYS:
            module.__dict__.setdefault(name, value)

    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise HiddenTestError(
            f"hidden module malformed for {task_id}: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        sys.modules.pop(module_name, None)
    return module


def _write_report(*, task_id: str, kind: str, path: Path, count: int) -> None:
    report_value = read_env("HIDDEN_REPORT")
    if not report_value:
        return
    report_path = Path(report_value)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "count": count,
        "kind": kind,
        "path": str(path),
        "task_id": task_id,
    }
    report_path.write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
