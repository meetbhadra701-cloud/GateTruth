"""Independent functional oracles for the ArchXBench pilot designs.

Each oracle is written directly from the published ArchXBench ``design-specs.txt``
(pinned commit 0db0d0de25aad5238393d51bd97ce952e579fa1a) and shares no code with the
evaluator-authored reference RTL. All input combinations are enumerated; the specs
define no illegal input encodings, so every 2-state combination is treated as legal.
"""
from __future__ import annotations

import random

SPECS: dict[str, dict] = {
    # spec: "selects in0 when sel=0, in1 when sel=1"
    "mux_2to1": {
        "inputs": [("in0", 1), ("in1", 1), ("sel", 1)],
        "outputs": [("out", 1)],
        "oracle": lambda i: {"out": i["in1"] if i["sel"] == 1 else i["in0"]},
    },
    # spec: unsigned compare of a and b; gt / eq / lt; mutually exclusive
    "comparator_4bit": {
        "inputs": [("a", 4), ("b", 4)],
        "outputs": [("gt", 1), ("eq", 1), ("lt", 1)],
        "oracle": lambda i: {"gt": int(i["a"] > i["b"]), "eq": int(i["a"] == i["b"]),
                             "lt": int(i["a"] < i["b"])},
    },
    # spec: enable=1 -> one-hot of `in`; enable=0 -> all zero
    "decoder_2to4": {
        "inputs": [("in", 2), ("enable", 1)],
        "outputs": [("out", 4)],
        "oracle": lambda i: {"out": (1 << i["in"]) if i["enable"] == 1 else 0},
    },
    # ---- v2 additions (each written from the pinned design-specs.txt) ----
    # spec: "Assumes exactly one input is high" -> only one-hot inputs are legal
    "binary_encoder_8to3": {
        "inputs": [("in", 8)], "outputs": [("out", 3)],
        "legal": lambda i: bin(i["in"]).count("1") == 1,
        "oracle": lambda i: {"out": i["in"].bit_length() - 1},
    },
    # spec: unsigned 8-bit compare; gt / eq / lt
    "comparator_8bit": {
        "inputs": [("a", 8), ("b", 8)], "outputs": [("gt", 1), ("eq", 1), ("lt", 1)],
        "oracle": lambda i: {"gt": int(i["a"] > i["b"]), "eq": int(i["a"] == i["b"]),
                             "lt": int(i["a"] < i["b"])},
    },
    # spec: in[2]=0 -> lower four outputs, in[2]=1 -> upper four; enable=0 -> all zero
    "decoder3to8": {
        "inputs": [("in", 3), ("enable", 1)], "outputs": [("out", 8)],
        "oracle": lambda i: {"out": (1 << i["in"]) if i["enable"] == 1 else 0},
    },
    # spec: out0 = in AND NOT(sel); out1 = in AND sel
    "demux_1to2": {
        "inputs": [("in", 1), ("sel", 1)], "outputs": [("out0", 1), ("out1", 1)],
        "oracle": lambda i: {"out0": i["in"] & (1 - i["sel"]), "out1": i["in"] & i["sel"]},
    },
    # spec: outN active (= in) when sel == N
    "demux_1to4": {
        "inputs": [("in", 1), ("sel", 2)],
        "outputs": [("out0", 1), ("out1", 1), ("out2", 1), ("out3", 1)],
        "oracle": lambda i: {f"out{n}": i["in"] if i["sel"] == n else 0 for n in range(4)},
    },
    # spec: selects in[sel]
    "mux_4to1": {
        "inputs": [("in", 4), ("sel", 2)], "outputs": [("out", 1)],
        "oracle": lambda i: {"out": (i["in"] >> i["sel"]) & 1},
    },
}


class _Seq:
    """Cycle model: ``step`` applies one rising edge and returns the outputs just after it."""

    def __init__(self, reset_state, advance, view):
        self.reset_state, self.advance, self.view, self.state = reset_state, advance, view, None

    def step(self, inputs: dict[str, int]) -> dict[str, int]:
        if inputs["rst"] == 1:
            self.state = self.reset_state
        else:
            assert self.state is not None, "stimulus must start with reset"
            self.state = self.advance(self.state)
        return self.view(self.state)


SEQ_SPECS: dict[str, dict] = {
    # spec: q resets to 0000; shift left, feed back inverted MSB
    "johnson_counter4": {"inputs": [("rst", 1)], "outputs": [("q", 4)], "model": lambda: _Seq(
        0, lambda s: ((s << 1) & 15) | (1 - ((s >> 3) & 1)), lambda s: {"q": s})},
    # spec: q resets to 0001; shift left, MSB wraps to LSB
    "ring_counter4": {"inputs": [("rst", 1)], "outputs": [("q", 4)], "model": lambda: _Seq(
        1, lambda s: ((s << 1) & 15) | (s >> 3), lambda s: {"q": s})},
    # spec: internal binary counter, gray = binary ^ (binary >> 1), reset to zero
    "gray_counter8": {"inputs": [("rst", 1)], "outputs": [("count", 8)], "model": lambda: _Seq(
        0, lambda s: (s + 1) & 255, lambda s: {"count": s ^ (s >> 1)})},
    # spec: synchronous incrementer, reset to zero
    "up_counter8": {"inputs": [("rst", 1)], "outputs": [("count", 8)], "model": lambda: _Seq(
        0, lambda s: (s + 1) & 255, lambda s: {"count": s})},
    # spec: clk_out toggles every rising edge, reset clears it to 0
    "clock_div2": {"inputs": [("rst", 1)], "outputs": [("clk_out", 1)], "model": lambda: _Seq(
        0, lambda s: 1 - s, lambda s: {"clk_out": s})},
}


def is_sequential(module: str) -> bool:
    return module in SEQ_SPECS


def legal_filter(module: str, rows: list[str]) -> list[str]:
    """Keep only rows whose input combination is legal under the documented assumption."""
    spec = SPECS[module]
    legal = spec.get("legal")
    if legal is None:
        return rows
    ok = {index for index, values in input_combinations(spec) if legal(values)}
    return [row for row in rows if int(row.split(" ", 1)[0]) in ok]


def stimulus(seed: int = 20260729, length: int = 600) -> list[dict[str, int]]:
    """Deterministic reset stimulus: reset-free run (covers 8-bit wrap), then random resets."""
    rng = random.Random(seed)
    resets = [1] + [0] * length + [1] + [1 if rng.random() < 0.05 else 0 for _ in range(length)]
    return [{"rst": r} for r in resets]


def sequential_oracle_rows(module: str) -> list[str]:
    spec, model = SEQ_SPECS[module], SEQ_SPECS[module]["model"]()
    rows = []
    for cycle, inputs in enumerate(stimulus()):
        out = model.step(inputs)
        rows.append(" ".join([str(cycle)] + [format(out[n], f"0{w}b") for n, w in spec["outputs"]]))
    return rows


def trace_testbench(module: str) -> str:
    """Self-contained TB: replays ``stimulus()`` and prints outputs 1 ns after each rising edge."""
    spec, stim = SEQ_SPECS[module], stimulus()
    decls = [f"    reg [{w - 1}:0] {n};" for n, w in spec["inputs"]]
    decls += [f"    wire [{w - 1}:0] {n};" for n, w in spec["outputs"]]
    ports = ", ".join([".clk(clk)"] + [f".{n}({n})" for n, _ in spec["inputs"] + spec["outputs"]])
    body = [f"        stim_{n}[{i}] = {w}'d{values[n]};" for i, values in enumerate(stim) for n, w in spec["inputs"]]
    arrays = [f"    reg [{w - 1}:0] stim_{n} [0:{len(stim) - 1}];" for n, w in spec["inputs"]]
    drive = [f"            {n} = stim_{n}[i];" for n, _ in spec["inputs"]]
    fmt = " ".join(["%0d"] + ["%b"] * len(spec["outputs"]))
    args = ", ".join(["i"] + [n for n, _ in spec["outputs"]])
    return "\n".join([
        "module gt_trace_tb;", "    reg clk;", *decls, *arrays, "    integer i;",
        f"    {module} dut ({ports});", "    initial begin", *body,
        f"        for (i = 0; i < {len(stim)}; i = i + 1) begin", "            clk = 0;", *drive,
        "            #5 clk = 1;", "            #1;", f'            $display("{fmt}", {args});',
        "            #4;", "        end", "        $finish;", "    end", "endmodule", ""])


def input_combinations(spec: dict):
    """Yield (index, {name: value}) for every input combination, first input = MSBs."""
    widths = [w for _, w in spec["inputs"]]
    total = sum(widths)
    for index in range(2 ** total):
        values, shift = {}, total
        for name, width in spec["inputs"]:
            shift -= width
            values[name] = (index >> shift) & ((1 << width) - 1)
        yield index, values


def format_row(spec: dict, index: int, outputs: dict[str, int]) -> str:
    cells = [format(outputs[name], f"0{width}b") for name, width in spec["outputs"]]
    return " ".join([str(index), *cells])


def oracle_rows(module: str) -> list[str]:
    """Expected rows for all LEGAL input combinations (all of them unless a predicate is set)."""
    spec = SPECS[module]
    legal = spec.get("legal", lambda _values: True)
    return [format_row(spec, i, spec["oracle"](v)) for i, v in input_combinations(spec) if legal(v)]


def exhaustive_testbench(module: str) -> str:
    """Self-contained Verilog TB that prints one `index out...` row per input combination."""
    spec = SPECS[module]
    decls = [f"    reg [{w - 1}:0] {n};" for n, w in spec["inputs"]]
    decls += [f"    wire [{w - 1}:0] {n};" for n, w in spec["outputs"]]
    ports = ", ".join(f".{n}({n})" for n, _ in spec["inputs"] + spec["outputs"])
    total = sum(w for _, w in spec["inputs"])
    concat = ", ".join(n for n, _ in spec["inputs"])
    fmt = " ".join(["%0d"] + ["%b"] * len(spec["outputs"]))
    args = ", ".join(["i"] + [n for n, _ in spec["outputs"]])
    return "\n".join([
        "module gt_exhaustive_tb;", *decls, "    integer i;",
        f"    {module} dut ({ports});",
        "    initial begin",
        f"        for (i = 0; i < {2 ** total}; i = i + 1) begin",
        f"            {{{concat}}} = i[{total - 1}:0];",
        "            #1;", f'            $display("{fmt}", {args});',
        "        end", "        $finish;", "    end", "endmodule", ""])
