"""Regression tests for the paper_facts generator.

Locks in the specific numbers this pass hand-verified against the real committed g2012 audit
data (external-audit/results/rtllm/final-g2012/*.json) after finding and fixing five places where
main.tex's prose had drifted from them (44 vs 46 audited, 73% vs 72% below-floor, an operator-count
table that summed to 769 instead of 775, and others). If the raw evidence changes, these exact
values should change too -- that is the point of generating them instead of hand-typing them again.
"""

from __future__ import annotations

from paper.data.generate_paper_facts import collect


def test_facts_match_the_verified_g2012_totals() -> None:
    facts = collect()

    assert facts["audited"] == 46
    assert facts["unsupported"] == 4
    assert facts["total_mutants"] == 775
    assert facts["total_killed"] == 440
    assert facts["total_survived"] == 320
    assert facts["total_indeterminate"] == 15
    assert facts["at_100"] == 13
    assert facts["below_95"] == 33
    assert round(facts["below_95_pct"]) == 72


def test_operator_counts_match_the_verified_totals() -> None:
    facts = collect()
    op = facts["op_total"]

    assert op["assignment_hold"] == 367
    assert op["blocking_output_inversion"] == 154
    assert op["comparator_boundary_flip"] == 92
    assert op["output_inversion"] == 60
    assert op["bitwise_inversion"] == 49
    assert op["logic_inversion"] == 29
    assert op["shift_inversion"] == 14
    assert op["operator_inversion"] == 6
    assert op["reset_polarity_flip"] == 4
    assert sum(op.values()) == 775


def test_tercile_medians_match_the_verified_split() -> None:
    facts = collect()
    t1, t2, t3 = facts["tercile_medians"]

    assert t1 == 100.0
    assert t2 == 75.0
    assert round(t3, 1) == 61.4
