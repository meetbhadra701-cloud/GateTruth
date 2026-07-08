"""Deterministic text-level RTL mutation operators.

The operators are intentionally conservative: each mutant changes one common RTL
mistake pattern and is accepted only if it changes the source exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mutant:
    id: str
    operator: str
    description: str
    source: str


def generate_mutants(task_id: str, source: str) -> list[Mutant]:
    specs = _generic_specs() + _task_specs(task_id)
    mutants: list[Mutant] = []
    seen: set[str] = set()
    for operator, description, old, new in specs:
        mutated = _replace_once(source, old, new)
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
    return mutants


def _replace_once(source: str, old: str, new: str) -> str | None:
    if old not in source:
        return None
    return source.replace(old, new, 1)


def _generic_specs() -> list[tuple[str, str, str, str]]:
    return [
        ("comparator_boundary_flip", "first equality becomes inequality", " == ", " != "),
        ("operator_inversion", "first increment becomes decrement", " + 1'b1", " - 1'b1"),
        ("operator_inversion", "first decrement becomes increment", " - 1'b1", " + 1'b1"),
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
