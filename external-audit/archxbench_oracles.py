"""Independent functional oracles for the ArchXBench pilot designs.

Each oracle is written directly from the published ArchXBench ``design-specs.txt``
(pinned commit 0db0d0de25aad5238393d51bd97ce952e579fa1a) and shares no code with the
evaluator-authored reference RTL. All input combinations are enumerated; the specs
define no illegal input encodings, so every 2-state combination is treated as legal.
"""
from __future__ import annotations

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
}


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
    spec = SPECS[module]
    return [format_row(spec, i, spec["oracle"](v)) for i, v in input_combinations(spec)]


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
