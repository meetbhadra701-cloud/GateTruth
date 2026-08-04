"""Regression tests for the deterministic hidden-vector extractor."""

from pathlib import Path

import pytest

import scripts.freeze_extract_hidden as freeze_extract_hidden_module
from scripts.freeze_extract_hidden import (
    apply_extraction,
    extraction_plan,
)


def test_extract_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    task_root = tmp_path / "tasks" / "demo"
    tb = task_root / "tb" / "test_demo.py"
    tb.parent.mkdir(parents=True)
    (task_root / "task.yaml").write_text("id: demo\n", encoding="utf-8")
    tb.write_text(
        """# HUMAN REVIEW: PENDING (tb_review in task.yaml - Meet only).

import cocotb

def helper():
    return 7

@cocotb.test()
async def smoke(dut):
    assert helper() == 7

# --- HIDDEN ---

@cocotb.test()
async def hidden_edge(dut):
    assert helper() == 7
""",
        encoding="utf-8",
    )

    plan = extraction_plan(tmp_path)
    assert len(plan) == 1
    assert plan[0].status == "would_extract"
    assert apply_extraction(plan[0]) is True

    public = tb.read_text(encoding="utf-8")
    hidden = plan[0].hidden_path.read_text(encoding="utf-8")
    assert "hidden_edge" not in public
    assert 'load_hidden(globals(), "demo")' in public
    assert "hidden_edge" in hidden
    assert "HUMAN REVIEW: PENDING" in hidden

    second = extraction_plan(tmp_path)
    assert second[0].status == "already_split"
    assert apply_extraction(second[0]) is False
    assert tb.read_text(encoding="utf-8") == public
    assert second[0].hidden_path.read_text(encoding="utf-8") == hidden


def test_crash_between_hidden_and_public_write_loses_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GTFS-031: a process kill mid-extraction must never strip the public source's
    hidden section without a durably-written hidden module to recover it from."""

    task_root = tmp_path / "tasks" / "demo"
    tb = task_root / "tb" / "test_demo.py"
    tb.parent.mkdir(parents=True)
    (task_root / "task.yaml").write_text("id: demo\n", encoding="utf-8")
    original_source = (
        "import cocotb\n\n"
        "def helper():\n"
        "    return 7\n\n"
        "@cocotb.test()\n"
        "async def smoke(dut):\n"
        "    assert helper() == 7\n\n"
        "# --- HIDDEN ---\n\n"
        "@cocotb.test()\n"
        "async def hidden_edge(dut):\n"
        "    assert helper() == 7\n"
    )
    tb.write_text(original_source, encoding="utf-8")

    plan = extraction_plan(tmp_path)
    item = plan[0]

    real_atomic_write_text = freeze_extract_hidden_module.atomic_write_text
    calls: list[Path] = []

    def flaky_atomic_write_text(path: Path, content: str) -> None:
        calls.append(path)
        if len(calls) == 2:
            raise OSError("simulated crash between the hidden and public writes")
        real_atomic_write_text(path, content)

    monkeypatch.setattr(
        freeze_extract_hidden_module, "atomic_write_text", flaky_atomic_write_text
    )

    with pytest.raises(OSError):
        apply_extraction(item)

    # The hidden module was durably written before the simulated crash...
    assert item.hidden_path.is_file()
    assert "hidden_edge" in item.hidden_path.read_text(encoding="utf-8")
    # ...and the public source was never touched, so nothing was lost: the marker
    # is still there for a re-run to safely redo the extraction from.
    assert tb.read_text(encoding="utf-8") == original_source

    monkeypatch.setattr(
        freeze_extract_hidden_module, "atomic_write_text", real_atomic_write_text
    )
    recovery_plan = extraction_plan(tmp_path)
    assert recovery_plan[0].status == "would_extract"
    assert apply_extraction(recovery_plan[0]) is True
    assert "hidden_edge" not in tb.read_text(encoding="utf-8")
    assert "hidden_edge" in recovery_plan[0].hidden_path.read_text(encoding="utf-8")
