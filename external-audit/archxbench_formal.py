"""Behavior capture and equivalence engines for the ArchXBench pilot (sequential + multi-module).

* ``trace_rows``  : replay the fixed reset stimulus on a sequential design (one row per cycle).
* ``behavior_rows``: exhaustive rows (combinational) or trace rows (sequential), legal inputs only.
* ``sby_equivalence``: UNBOUNDED equivalence from reset via SymbiYosys/ABC-PDR.
* ``prefix_modules``: rename every module in a file so a reference and a mutant can coexist.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from archxbench_oracles import (
    SEQ_SPECS,
    exhaustive_testbench,
    is_sequential,
    legal_filter,
    oracle_rows,
    sequential_oracle_rows,
    trace_testbench,
)
from archxbench_pilot import sim_env

ROW = re.compile(r"^\d+ ")


def _simulate(iverilog: str, vvp: str, source: str, tb_source: str, top: str, work: Path) -> list[str] | None:
    work.mkdir(parents=True, exist_ok=True)
    (work / "dut.v").write_text(source, encoding="utf-8", newline="")
    (work / "tb.v").write_text(tb_source, encoding="utf-8", newline="")
    try:
        built = subprocess.run([iverilog, "-g2012", "-s", top, "-o", str(work / "sim.out"),
                                str(work / "dut.v"), str(work / "tb.v")],
                               capture_output=True, text=True, timeout=60, env=sim_env())
        if built.returncode != 0:
            return None
        ran = subprocess.run([vvp, str(work / "sim.out")], capture_output=True, text=True,
                             timeout=120, env=sim_env())
    except (subprocess.TimeoutExpired, OSError):
        return None
    if ran.returncode != 0:
        return None
    return [line for line in ran.stdout.splitlines() if ROW.match(line)]


def exhaustive_rows(iverilog: str, vvp: str, source: str, module: str, work: Path) -> list[str] | None:
    """Simulate every input combination; rows outside the documented legal-input set are dropped."""
    rows = _simulate(iverilog, vvp, source, exhaustive_testbench(module), "gt_exhaustive_tb", work)
    return None if rows is None else legal_filter(module, rows)


def trace_rows(iverilog: str, vvp: str, source: str, module: str, work: Path) -> list[str] | None:
    return _simulate(iverilog, vvp, source, trace_testbench(module), "gt_trace_tb", work)


def behavior_rows(iverilog: str, vvp: str, source: str, module: str, work: Path) -> list[str] | None:
    fn = trace_rows if is_sequential(module) else exhaustive_rows
    return fn(iverilog, vvp, source, module, work)


def expected_rows(module: str) -> list[str]:
    return sequential_oracle_rows(module) if is_sequential(module) else oracle_rows(module)


def prefix_modules(source: str, prefix: str) -> str:
    """Rename every module defined in ``source`` (declarations and instantiations)."""
    for name in dict.fromkeys(re.findall(r"\bmodule\s+([A-Za-z_]\w*)", source)):
        source = re.sub(rf"\b{re.escape(name)}\b", prefix + name, source)
    return source


def sby_equivalence(sby: str, reference: str, mutant: str, module: str, work: Path,
                    timeout_s: int = 300) -> str:
    """'equivalent' | 'different' | 'unavailable' | 'error' (unbounded, from reset).

    Both machines start in arbitrary state; cycle 0 is constrained to rst=1 and outputs are
    compared from cycle 1 on, for every possible input sequence thereafter.
    """
    spec = SEQ_SPECS[module]
    work.mkdir(parents=True, exist_ok=True)
    (work / "gold.v").write_text(prefix_modules(reference, "gtgold_"), encoding="utf-8", newline="")
    (work / "gate.v").write_text(prefix_modules(mutant, "gtgate_"), encoding="utf-8", newline="")
    ports = ["input clk"] + [f"input [{w - 1}:0] {n}" for n, w in spec["inputs"]]
    wires = [f"  wire [{w - 1}:0] {side}_{n};" for n, w in spec["outputs"] for side in ("g", "t")]

    def connect(side: str) -> str:
        pairs = [".clk(clk)"] + [f".{n}({n})" for n, _ in spec["inputs"]]
        return ", ".join(pairs + [f".{n}({side}_{n})" for n, _ in spec["outputs"]])

    lines = [f"module gt_miter({', '.join(ports)});", *wires,
             f"  gtgold_{module} g ({connect('g')});", f"  gtgate_{module} t ({connect('t')});",
             "  reg init = 1'b1;", "  always @(posedge clk) init <= 1'b0;", "  always @* begin",
             "    if (init) assume (rst == 1'b1);"]
    lines += [f"    if (!init) assert (g_{n} == t_{n});" for n, _ in spec["outputs"]]
    lines += ["  end", "endmodule", ""]
    (work / "miter.sv").write_text("\n".join(lines), encoding="utf-8", newline="")
    (work / "gt.sby").write_text("\n".join([
        "[options]", "mode prove", "", "[engines]", "abc pdr", "", "[script]",
        "read -formal gold.v", "read -formal gate.v", "read -formal -sv miter.sv",
        "prep -top gt_miter", "", "[files]", "gold.v", "gate.v", "miter.sv", ""]),
        encoding="utf-8", newline="")
    try:
        subprocess.run([sby, "-f", "gt.sby"], cwd=work, capture_output=True, text=True,
                       timeout=timeout_s, env=sim_env())
    except FileNotFoundError:
        return "unavailable"
    except subprocess.TimeoutExpired:
        return "error"
    if (work / "gt" / "PASS").exists():
        return "equivalent"
    if (work / "gt" / "FAIL").exists():
        return "different"
    return "error"
