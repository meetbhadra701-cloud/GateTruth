from __future__ import annotations

import sys
from pathlib import Path

AUDIT_ROOT = Path(__file__).resolve().parents[1]
if str(AUDIT_ROOT) not in sys.path:
    sys.path.insert(0, str(AUDIT_ROOT))

from fetch_vendor import tree_hash  # noqa: E402
from sweep_cvdp import _row_report  # noqa: E402
from sweep_rtllm import (  # noqa: E402
    _module_names,
    _reference_top_module,
    _support_files,
)


def test_tree_hash_is_content_sensitive_and_ignores_git(tmp_path):
    (tmp_path / "B.txt").write_text("second\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("first\n", encoding="utf-8")
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ignored\n", encoding="utf-8")

    baseline = tree_hash(tmp_path)
    (git_dir / "HEAD").write_text("still ignored\n", encoding="utf-8")
    assert tree_hash(tmp_path) == baseline

    (tmp_path / "a.txt").write_text("changed\n", encoding="utf-8")
    assert tree_hash(tmp_path) != baseline


def test_cvdp_row_requires_actual_output_not_only_an_oss_origin():
    row = {
        "id": "cvdp_copilot_example_0001",
        "categories": ["cid003", "medium"],
        "output": {"response": "", "context": {"rtl/design.sv": ""}},
    }
    report = _row_report(
        row,
        oss_ids={"cvdp_copilot_example"},
        example_solutions={},
    )

    assert report["oss_origin_declared"] is True
    assert report["has_golden"] is False
    assert report["golden_source"] is None


def test_cvdp_row_accepts_nonempty_rtl_output():
    row = {
        "id": "row",
        "categories": ["cid002"],
        "output": {
            "response": "",
            "context": {"rtl/design.sv": "module design; endmodule\n"},
        },
    }
    report = _row_report(row, oss_ids=set(), example_solutions={})

    assert report["has_golden"] is True
    assert report["golden_source"] == "output-field"


def test_rtllm_module_and_support_file_discovery(tmp_path):
    source = tmp_path / "verified_example.v"
    source.write_text(
        "module helper; endmodule\nmodule verified_example; endmodule\n",
        encoding="utf-8",
    )
    testbench = tmp_path / "testbench.v"
    testbench.write_text(
        'module testbench; initial $readmemh("vectors.dat", mem); endmodule\n',
        encoding="utf-8",
    )
    (tmp_path / "vectors.dat").write_text("00\n", encoding="utf-8")

    modules = _module_names(source)
    assert modules == ["helper", "verified_example"]
    assert _reference_top_module(modules, "example") == "verified_example"
    assert _support_files(testbench) == ["vectors.dat"]
