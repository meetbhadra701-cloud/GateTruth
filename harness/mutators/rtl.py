"""Deterministic text-level RTL mutation operators.

The operators are intentionally conservative: each mutant changes one common RTL
mistake pattern and is accepted only if it changes the source exactly once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Mutant:
    id: str
    operator: str
    description: str
    source: str


def generate_mutants(
    task_id: str,
    source: str,
    *,
    include_task_specs: bool = True,
) -> list[Mutant]:
    generic_specs = _generic_specs()
    specs = generic_specs + (_task_specs(task_id) if include_task_specs else [])
    generic_count = len(generic_specs)
    mutants: list[Mutant] = []
    seen: set[str] = set()
    for spec_index, (operator, description, old, new) in enumerate(specs):
        candidates = _replace_all(source, old, new) if spec_index < generic_count else [_replace_once(source, old, new)]
        for mutated in candidates:
            if mutated is None or mutated in seen:
                continue
            seen.add(mutated)
            index = len(mutants)
            mutants.append(
                Mutant(
                    id=f"{task_id}-m{index:03d}",
                    operator=operator,
                    description=description,
                    source=mutated,
                )
            )
    for operator, description, pattern, replacement in _generic_regex_specs():
        for mutated in _replace_regex_all(source, pattern, replacement):
            if mutated in seen:
                continue
            seen.add(mutated)
            mutants.append(
                Mutant(
                    id=f"{task_id}-m{len(mutants):03d}",
                    operator=operator,
                    description=description,
                    source=mutated,
                )
            )
    for operator, description, mutated in _flip_constant_nonblocking_assignments(source):
        if mutated in seen:
            continue
        seen.add(mutated)
        mutants.append(
            Mutant(
                id=f"{task_id}-m{len(mutants):03d}",
                operator=operator,
                description=description,
                source=mutated,
            )
        )
    for mutated in _invert_continuous_assignments(source):
        if mutated in seen:
            continue
        seen.add(mutated)
        mutants.append(
            Mutant(
                id=f"{task_id}-m{len(mutants):03d}",
                operator="output_inversion",
                description="continuous output is inverted",
                source=mutated,
            )
            )
    for mutated in _hold_nonblocking_assignments(source):
        if mutated in seen:
            continue
        seen.add(mutated)
        mutants.append(
            Mutant(
                id=f"{task_id}-m{len(mutants):03d}",
                operator="assignment_hold",
                description="registered assignment holds its previous value",
                source=mutated,
            )
            )
    for mutated in _invert_blocking_assignments(source):
        if mutated in seen:
            continue
        seen.add(mutated)
        mutants.append(
            Mutant(
                id=f"{task_id}-m{len(mutants):03d}",
                operator="blocking_output_inversion",
                description="combinational assignment is inverted",
                source=mutated,
            )
        )
    return [mutant for mutant in mutants if not _known_equivalent(task_id, mutant)]


def _known_equivalent(task_id: str, mutant: Mutant) -> bool:
    if task_id == "t2_spi_slave":
        # rx_shreg is seven bits wide and rx_data is emitted only after eight
        # incoming shifts, so its value at chip-select is fully overwritten.
        return "rx_shreg <= '1;" in mutant.source or "rx_shreg <= rx_shreg;" in mutant.source
    if task_id == "t2_priority_interrupt_controller":
        # idx is overwritten for every valid interrupt and is unobservable when
        # irq_valid is false, so its comb initializer cannot affect a port.
        return "idx = ~('0);" in mutant.source
    if task_id == "t2_round_robin_arbiter":
        # gidx is consumed only when a grant exists; in that case the grant
        # scan always overwrites this initializer before ptr uses it.
        return "gidx = ~('0);" in mutant.source
    if task_id == "t2_axi_lite_regfile":
        # AXI OKAY responses are constant zero in every reachable state.
        return "bresp <= bresp;" in mutant.source or "rresp <= rresp;" in mutant.source
    if task_id == "t2_pulse_stretcher":
        # These assignments merely restate the state invariant: out is already
        # low while idle and already high while an active stretch remains.
        return "out <= out;" in mutant.source
    if task_id == "t2_stream_downsizer":
        # count is zero whenever idle; the terminal clear is overwritten by the
        # next accepted input before count can affect an output.
        return "count <= count;" in mutant.source or "count <= '1;" in mutant.source
    if task_id in {"t2_uart_rx", "t2_uart_tx"}:
        # IDLE clears clk_cnt before accepting a frame, making the preceding
        # state-boundary clear and its held value externally unobservable.
        return "clk_cnt <= clk_cnt;" in mutant.source or "clk_cnt <= '1;" in mutant.source
    if task_id == "t3_sequential_divider":
        # The divide-by-zero branch is entered only from !busy, so retaining
        # busy there is equivalent to assigning zero.
        return "busy <= busy;" in mutant.source
    if task_id == "t2_i2c_slave":
        # shreg is seven bits and is fully overwritten by the eight incoming
        # bits before either address matching or byte_data observes it.
        # bit_cnt is redundantly cleared at every protocol boundary (the
        # byte-completing branch, then again in both *_ACK_FALL states, and on
        # every START) and is consumed only after one of those clears runs, so
        # each individual clear is masked by the next before any use.
        # matched is overwritten by is_match on the eighth address bit before
        # its only use in ADDR_ACK_FALL.
        return (
            "shreg <= '1;" in mutant.source
            or "shreg <= shreg;" in mutant.source
            or "bit_cnt <= '1;" in mutant.source
            or "bit_cnt <= bit_cnt;" in mutant.source
            or "matched <= matched;" in mutant.source
        )
    if task_id == "t3_lru_tracker":
        # age[] is a permutation of 0..NWAYS-1 in every reachable state (reset
        # seeds one and the shift-up update preserves it - the bound formal
        # properties check exactly this), so precisely one way matches
        # NWAYS-1 and the readout loop always overwrites this initializer.
        return "lru_way = ~('0);" in mutant.source
    if task_id == "t2_spi_master":
        # IDLE is only entered from reset or from the completion branch, both of
        # which leave cs_n=1, sclk=0, busy=0 and half_cnt=0; the IDLE-state
        # restatements and the start-branch half_cnt clear are therefore
        # redundant in every reachable visit. The matches are anchored to their
        # preceding source line so the behavior-changing ACTIVE-branch holds of
        # the same signals stay in the mutant pool.
        return (
            "IDLE: begin\n                    cs_n <= cs_n;" in mutant.source
            or "cs_n <= 1'b1;\n                    sclk <= sclk;" in mutant.source
            or "sclk <= 1'b0;\n                    busy <= busy;" in mutant.source
            or "busy     <= 1'b1;\n                        half_cnt <= half_cnt;" in mutant.source
        )
    return False


def _replace_once(source: str, old: str, new: str) -> str | None:
    mask = _code_mask(source)
    index = mask.find(old)
    if index < 0:
        return None
    return source[:index] + new + source[index + len(old) :]


def _replace_all(source: str, old: str, new: str) -> list[str]:
    mask = _code_mask(source)
    results: list[str] = []
    start = 0
    while True:
        index = mask.find(old, start)
        if index < 0:
            return results
        results.append(source[:index] + new + source[index + len(old) :])
        start = index + len(old)


def _replace_regex_all(source: str, pattern: str, replacement: str) -> list[str]:
    mask = _code_mask(source)
    results: list[str] = []
    for match in re.finditer(pattern, mask):
        results.append(source[: match.start()] + replacement + source[match.end() :])
    return results


def _invert_continuous_assignments(source: str) -> list[str]:
    mask = _code_mask(source)
    results: list[str] = []
    pattern = re.compile(r"\bassign\s+([A-Za-z_]\w*)\s*=\s*([^;]+);")
    for match in pattern.finditer(mask):
        lhs, rhs = match.group(1), source[match.start(2) : match.end(2)].strip()
        replacement = f"assign {lhs} = ~({rhs});"
        results.append(source[: match.start()] + replacement + source[match.end() :])
    return results


def _hold_nonblocking_assignments(source: str) -> list[str]:
    mask = _code_mask(source)
    output_names = _output_names(mask)
    reset_spans = _reset_spans(mask)
    results: list[str] = []
    pattern = re.compile(r"\b([A-Za-z_]\w*(?:\s*\[[^\]]+\])?)\s*<=\s*([^;]+);")
    for match in pattern.finditer(mask):
        line_start = mask.rfind("\n", 0, match.start()) + 1
        if "default:" in mask[line_start : match.start()]:
            continue
        lhs = source[match.start(1) : match.end(1)].strip()
        base_lhs = lhs.split("[", 1)[0].strip()
        rhs = source[match.start(2) : match.end(2)].strip()
        if re.sub(r"\s+", "", rhs) == re.sub(r"\s+", "", lhs):
            continue
        if _inside_any_span(match.start(), reset_spans) and base_lhs not in output_names:
            continue
        replacement = f"{lhs} <= {lhs};"
        results.append(source[: match.start()] + replacement + source[match.end() :])
    return results


def _flip_constant_nonblocking_assignments(source: str) -> list[tuple[str, str, str]]:
    mask = _code_mask(source)
    output_names = _output_names(mask)
    reset_spans = _reset_spans(mask)
    results: list[tuple[str, str, str]] = []
    pattern = re.compile(r"\b([A-Za-z_]\w*(?:\s*\[[^\]]+\])?)\s*<=\s*'(0|1);")
    for match in pattern.finditer(mask):
        lhs = source[match.start(1) : match.end(1)].strip()
        base_lhs = lhs.split("[", 1)[0].strip()
        if _inside_any_span(match.start(), reset_spans) and base_lhs not in output_names:
            continue
        old_bit = match.group(2)
        new_bit = "1" if old_bit == "0" else "0"
        replacement = f"{lhs} <= '{new_bit};"
        description = "zero assignment becomes all ones" if old_bit == "0" else "all-ones assignment becomes zero"
        results.append(
            (
                "assignment_deletion",
                description,
                source[: match.start()] + replacement + source[match.end() :],
            )
        )
    return results


def _output_names(mask: str) -> set[str]:
    pattern = re.compile(
        r"\boutput\s+(?:(?:logic|wire|reg)\s+)?(?:signed\s+)?(?:\[[^\]]+\]\s*)?([A-Za-z_]\w*)"
    )
    return {match.group(1) for match in pattern.finditer(mask)}


def _reset_spans(mask: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pattern = re.compile(r"\bif\s*\(\s*!?rst\s*\)\s*(begin)?")
    for match in pattern.finditer(mask):
        if match.group(1) is None:
            end = mask.find(";", match.end())
            spans.append((match.start(), len(mask) if end < 0 else end + 1))
            continue
        depth = 1
        end = match.end()
        for token in re.finditer(r"\b(begin|end)\b", mask[match.end() :]):
            depth += 1 if token.group(1) == "begin" else -1
            if depth == 0:
                end = match.end() + token.end()
                break
        spans.append((match.start(), end))
    return spans


def _inside_any_span(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


def _invert_blocking_assignments(source: str) -> list[str]:
    mask = _code_mask(source)
    results: list[str] = []
    pattern = re.compile(r"\b([A-Za-z_]\w*(?:\s*\[[^\]]+\])?)\s*=\s*([^=;]+);")
    for match in pattern.finditer(mask):
        line_start = mask.rfind("\n", 0, match.start()) + 1
        if "for (" in mask[line_start : match.start()] or "for(" in mask[line_start : match.start()]:
            continue
        lhs = source[match.start(1) : match.end(1)].strip()
        rhs = source[match.start(2) : match.end(2)].strip()
        replacement = f"{lhs} = ~({rhs});"
        results.append(source[: match.start()] + replacement + source[match.end() :])
    return results


def _code_mask(source: str) -> str:
    """Blank comments and string literals while preserving source offsets."""
    chars = list(source)
    index = 0
    mode = "code"
    while index < len(chars):
        if mode == "code" and chars[index : index + 2] == ["/", "/"]:
            mode = "line"
            chars[index] = chars[index + 1] = " "
            index += 2
            continue
        if mode == "code" and chars[index : index + 2] == ["/", "*"]:
            mode = "block"
            chars[index] = chars[index + 1] = " "
            index += 2
            continue
        if mode == "code" and chars[index] == '"':
            mode = "string"
            chars[index] = " "
            index += 1
            continue
        if mode == "code":
            index += 1
            continue
        if mode == "line":
            if chars[index] == "\n":
                mode = "code"
            else:
                chars[index] = " "
            index += 1
            continue
        if mode == "block":
            if chars[index : index + 2] == ["*", "/"]:
                chars[index] = chars[index + 1] = " "
                index += 2
                mode = "code"
            else:
                if chars[index] != "\n":
                    chars[index] = " "
                index += 1
            continue
        if mode == "string":
            if chars[index] == "\\":
                chars[index] = " "
                if index + 1 < len(chars):
                    chars[index + 1] = " "
                index += 2
            elif chars[index] == '"':
                chars[index] = " "
                index += 1
                mode = "code"
            else:
                chars[index] = " "
                index += 1
    return "".join(chars)


def _generic_specs() -> list[tuple[str, str, str, str]]:
    return [
        ("comparator_boundary_flip", "equality becomes inequality", " == ", " != "),
        ("comparator_boundary_flip", "inequality becomes equality", " != ", " == "),
        ("operator_inversion", "increment becomes decrement", " + 1'b1", " - 1'b1"),
        ("operator_inversion", "decrement becomes increment", " - 1'b1", " + 1'b1"),
        ("logic_inversion", "and becomes or", " && ", " || "),
        ("logic_inversion", "or becomes and", " || ", " && "),
        ("bitwise_inversion", "xor becomes or", " ^ ", " | "),
        ("bitwise_inversion", "or becomes xor", " | ", " ^ "),
        ("shift_inversion", "left shift becomes right shift", " << ", " >> "),
        ("shift_inversion", "right shift becomes left shift", " >> ", " << "),
    ]


def _generic_regex_specs() -> list[tuple[str, str, str, str]]:
    return [
        ("reset_polarity_flip", "reset condition inverted", r"\bif\s*\(\s*rst\s*\)", "if (!rst)"),
        ("reset_polarity_flip", "active-low reset condition inverted", r"\bif\s*\(\s*!rst\s*\)", "if (rst)"),
        ("dropped_enable", "enable condition inverted", r"\bif\s*\(\s*en\s*\)", "if (!en)"),
        ("dropped_enable", "active-low enable condition inverted", r"\bif\s*\(\s*!en\s*\)", "if (en)"),
    ]


def _task_specs(task_id: str) -> list[tuple[str, str, str, str]]:
    if task_id == "t1_gray_counter":
        return [
            ("reset_polarity_flip", "reset condition inverted", "if (rst)", "if (!rst)"),
            ("dropped_enable", "enable inverted", "else if (en)", "else if (!en)"),
            ("dropped_enable", "enable ignored", "else if (en)", "else if (1'b1)"),
            ("operator_inversion", "counter decrements instead of increments", "bin <= bin + 1'b1;", "bin <= bin - 1'b1;"),
            ("assignment_deletion", "counter does not advance", "bin <= bin + 1'b1;", "bin <= bin;"),
            ("operator_inversion", "gray xor becomes or", "assign gray = bin ^ (bin >> 1);", "assign gray = bin | (bin >> 1);"),
            ("operator_inversion", "gray xor becomes and", "assign gray = bin ^ (bin >> 1);", "assign gray = bin & (bin >> 1);"),
            ("assignment_deletion", "gray exposes binary count", "assign gray = bin ^ (bin >> 1);", "assign gray = bin;"),
        ]
    if task_id == "t2_sync_fifo":
        return [
            ("reset_polarity_flip", "reset condition inverted", "if (rst) begin", "if (!rst) begin"),
            ("fifo_flag_inversion", "full flag inverted", "assign full  = (count == CAP);", "assign full  = (count != CAP);"),
            ("fifo_flag_inversion", "empty flag inverted", "assign empty = (count == '0);", "assign empty = (count != '0);"),
            ("dropped_enable", "write ignores full back-pressure", "wire do_wr = wr_en & ~full;", "wire do_wr = wr_en;"),
            ("dropped_enable", "read ignores empty back-pressure", "wire do_rd = rd_en & ~empty;", "wire do_rd = rd_en;"),
            ("assignment_deletion", "write data corrupted to zero", "mem[wptr] <= din;", "mem[wptr] <= '0;"),
            ("assignment_deletion", "write pointer does not advance", "wptr      <= wptr + 1'b1;", "wptr      <= wptr;"),
            ("assignment_deletion", "read pointer does not advance", "rptr <= rptr + 1'b1;", "rptr <= rptr;"),
            ("operator_inversion", "occupancy increments on read", "2'b01:   count <= count - 1'b1;", "2'b01:   count <= count + 1'b1;"),
            ("operator_inversion", "occupancy decrements on write", "2'b10:   count <= count + 1'b1;", "2'b10:   count <= count - 1'b1;"),
            ("assignment_deletion", "simultaneous operation clears occupancy", "default: count <= count;", "default: count <= '0;"),
            ("assignment_deletion", "FWFT output uses write pointer", "assign dout = mem[rptr];", "assign dout = mem[wptr];"),
        ]
    if task_id == "t2_uart_tx":
        return [
            ("reset_polarity_flip", "reset condition inverted", "if (rst) begin", "if (!rst) begin"),
            ("comparator_boundary_flip", "baud tick equality inverted", "wire tick = (clk_cnt == LAST_TICK);", "wire tick = (clk_cnt != LAST_TICK);"),
            ("off_by_one_counter_limit", "baud period one cycle short", "CLKS_PER_BIT - 1", "CLKS_PER_BIT - 2"),
            ("off_by_one_counter_limit", "last data bit skipped", "DATA_BITS - 1", "DATA_BITS - 2"),
            ("assignment_deletion", "payload latch corrupted", "shift <= data;", "shift <= '0;"),
            ("state_transition_deletion", "idle start ignored", "state <= START_BIT;", "state <= IDLE;"),
            ("state_transition_deletion", "start bit repeats", "state   <= DATA_BITS_ST;", "state   <= START_BIT;"),
            ("state_transition_deletion", "data never reaches stop", "state <= STOP_BIT;", "state <= DATA_BITS_ST;"),
            ("state_transition_deletion", "stop never returns idle", "state   <= IDLE;", "state   <= STOP_BIT;"),
            ("assignment_deletion", "done pulse deleted", "done    <= 1'b1;", "done    <= 1'b0;"),
            ("operator_inversion", "start bit high", "START_BIT:    tx = 1'b0;", "START_BIT:    tx = 1'b1;"),
            ("assignment_deletion", "data bits forced high", "DATA_BITS_ST: tx = shift[bit_idx];", "DATA_BITS_ST: tx = 1'b1;"),
            ("assignment_deletion", "busy inverted", "assign busy = (state != IDLE);", "assign busy = (state == IDLE);"),
        ]
    return []
