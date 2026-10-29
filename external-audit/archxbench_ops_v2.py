"""Pilot operator set v2: standard first-order mutation operators for small RTL.

This module lives in ``external-audit/`` ON PURPOSE: ``harness/mutators/rtl.py`` (the engine
behind GateTruth's task admission and paper numbers) is left untouched. v2 = every v1 mutant
(unchanged, same order) followed by the operators below, each applied once per site, in
source order, deduplicated by mutated source text.

Pre-registered operator list (frozen in PREREGISTRATION.md before any v2 outcome was seen;
chosen from textbook mutation classes -- ROR, LOR/AOR, UOD, CRP, stuck-at, gate-type
replacement -- not tuned on results):

  relational_op_replacement   <  <=  >  >=  ==  !=   -> each other relational operator
                              (`<=` counts as relational only inside parentheses, never as NBA)
  bitwise_op_replacement      binary & | ^             -> each of the other two
  negation_deletion           unary ~x / !x            -> x
  if_condition_negation       if (C)                   -> if (!(C))
  arith_op_replacement        binary + <-> -
  constant_bit_flip           sized literal W'b/o/d/h v -> v ^ 1 (same width and base)
  bit_select_off_by_one       name[k]                  -> name[k+1], name[k-1] (k > 0)
  gate_type_replacement       primitive and/or/nand/nor/xor/xnor/not/buf -> fixed partner set
  stuck_at_assign             assign x = E;  /  x <= E; -> '0 and '1
"""
from __future__ import annotations

import re

from harness.mutators import Mutant, generate_mutants
from harness.sv_mask import mask_code

V2_OPERATORS = [
    "relational_op_replacement", "bitwise_op_replacement", "negation_deletion",
    "if_condition_negation", "arith_op_replacement", "constant_bit_flip",
    "bit_select_off_by_one", "gate_type_replacement", "stuck_at_assign",
]
RELATIONAL = ["<", "<=", ">", ">=", "==", "!="]
GATE_PARTNERS = {"and": ["or", "nand"], "or": ["and", "nor"], "nand": ["nor", "and"],
                 "nor": ["nand", "or"], "xor": ["xnor", "or"], "xnor": ["xor"],
                 "not": ["buf"], "buf": ["not"]}
OPERAND_END = re.compile(r"[A-Za-z0-9_)\]']")
DECL_WORDS = {"input", "output", "reg", "wire", "logic", "integer", "inout", "parameter"}


def _prev_nonspace(mask: str, index: int) -> str:
    j = index - 1
    while j >= 0 and mask[j].isspace():
        j -= 1
    return mask[j] if j >= 0 else ""


def _depths(mask: str) -> list[int]:
    depth, out = 0, []
    for ch in mask:
        if ch == ")":
            depth -= 1
        out.append(depth)
        if ch == "(":
            depth += 1
    return out


def _splice(source: str, start: int, end: int, new: str) -> str:
    return source[:start] + new + source[end:]


def _relational(source: str, mask: str):
    depth = _depths(mask)
    for m in re.finditer(r"(?<![<>=!])(<=|>=|==|!=|<|>)(?![<>=])", mask):
        op = m.group(1)
        if op == "<=" and depth[m.start()] == 0:
            continue  # non-blocking assignment, not a comparison
        if op in ("<", ">") and mask[m.start() - 1:m.start()] in ("<", ">"):
            continue
        for other in RELATIONAL:
            if other != op:
                yield f"{op} becomes {other}", _splice(source, m.start(), m.end(), other)


def _binary_operand_before(mask: str, index: int) -> bool:
    prev = _prev_nonspace(mask, index)
    return bool(prev) and OPERAND_END.fullmatch(prev) is not None


def _bitwise(source: str, mask: str):
    for m in re.finditer(r"(?<![&|^~])([&|^])(?![&|^~=])", mask):
        op = m.group(1)
        if not _binary_operand_before(mask, m.start()):
            continue
        for other in "&|^":
            if other != op:
                yield f"bitwise {op} becomes {other}", _splice(source, m.start(), m.end(), other)


def _negation(source: str, mask: str):
    for m in re.finditer(r"(?<![~!])([~!])(?![&|^~=])", mask):
        if _binary_operand_before(mask, m.start()):
            continue
        yield f"unary {m.group(1)} deleted", _splice(source, m.start(), m.end(), "")


def _if_negation(source: str, mask: str):
    for m in re.finditer(r"\bif\s*\(", mask):
        depth, j = 1, m.end()
        while j < len(mask) and depth:
            depth += {"(": 1, ")": -1}.get(mask[j], 0)
            j += 1
        cond = source[m.end():j - 1]
        yield "if condition negated", source[:m.end()] + f"!({cond})" + source[j - 1:]


def _arith(source: str, mask: str):
    for m in re.finditer(r"(?<![+\-])([+\-])(?![+\-=])", mask):
        if not _binary_operand_before(mask, m.start()):
            continue
        yield f"arithmetic {m.group(1)} flipped", _splice(source, m.start(), m.end(), "-" if m.group(1) == "+" else "+")


def _constants(source: str, mask: str):
    for m in re.finditer(r"(?<![\w'])(\d+)'([bBoOdDhH])([0-9a-fA-F_]+)(?![\w'])", mask):
        width, base, digits = int(m.group(1)), m.group(2).lower(), m.group(3).replace("_", "")
        radix = {"b": 2, "o": 8, "d": 10, "h": 16}[base]
        try:
            value = int(digits, radix)
        except ValueError:
            continue
        flipped = (value ^ 1) & ((1 << width) - 1)
        text = {"b": format(flipped, f"0{len(digits)}b"), "o": format(flipped, f"0{len(digits)}o"),
                "d": str(flipped), "h": format(flipped, f"0{len(digits)}x")}[base]
        yield f"constant {m.group(0)} LSB flipped", _splice(source, m.start(3), m.end(3), text)


def _bit_selects(source: str, mask: str):
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]", mask):
        if m.group(1) in DECL_WORDS:
            continue
        k = int(m.group(2))
        for new in (k + 1, k - 1):
            if new >= 0:
                yield f"bit select index {k} becomes {new}", _splice(source, m.start(2), m.end(2), str(new))


def _gates(source: str, mask: str):
    pattern = r"(?m)^\s*(and|or|nand|nor|xor|xnor|not|buf)\s+(?:[A-Za-z_]\w*\s*)?\("
    for m in re.finditer(pattern, mask):
        for partner in GATE_PARTNERS[m.group(1)]:
            yield f"gate {m.group(1)} becomes {partner}", _splice(source, m.start(1), m.end(1), partner)


def _stuck(source: str, mask: str):
    for m in re.finditer(r"\bassign\s+([A-Za-z_]\w*(?:\s*\[[^\]]+\])?)\s*=\s*([^;]+);", mask):
        for const in ("'0", "'1"):
            rhs = source[m.start(2):m.end(2)].strip()
            if rhs != const:
                yield f"assign output stuck at {const}", _splice(source, m.start(2), m.end(2), const)
    depth = _depths(mask)
    for m in re.finditer(r"\b([A-Za-z_]\w*(?:\s*\[[^\]]+\])?)\s*<=\s*([^;]+);", mask):
        if depth[m.start()] != 0:
            continue
        for const in ("'0", "'1"):
            if source[m.start(2):m.end(2)].strip() != const:
                yield f"register input stuck at {const}", _splice(source, m.start(2), m.end(2), const)


_GENERATORS = [
    ("relational_op_replacement", _relational), ("bitwise_op_replacement", _bitwise),
    ("negation_deletion", _negation), ("if_condition_negation", _if_negation),
    ("arith_op_replacement", _arith), ("constant_bit_flip", _constants),
    ("bit_select_off_by_one", _bit_selects), ("gate_type_replacement", _gates),
    ("stuck_at_assign", _stuck),
]


def generate_mutants_v2(task_id: str, source: str, *, include_task_specs: bool = False) -> list[Mutant]:
    """v1 mutants unchanged and first, then the v2 operators; ids are renumbered sequentially."""
    mutants = [(m.operator, m.description, m.source) for m in
               generate_mutants(task_id, source, include_task_specs=include_task_specs)]
    seen = {source, *[m[2] for m in mutants]}
    mask = mask_code(source)
    for operator, generator in _GENERATORS:
        for description, mutated in generator(source, mask):
            if mutated not in seen:
                seen.add(mutated)
                mutants.append((operator, description, mutated))
    return [Mutant(id=f"{task_id}-m{i:03d}", operator=op, description=desc, source=src)
            for i, (op, desc, src) in enumerate(mutants)]
