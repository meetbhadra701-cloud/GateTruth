"""Regression tests for the deterministic hidden-vector extractor."""

from pathlib import Path

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
