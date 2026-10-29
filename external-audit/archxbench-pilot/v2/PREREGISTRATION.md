# Pilot v2 — pre-registration (frozen before any v2 mutation outcome was seen)

Date: 2026-10-29 · Supersedes nothing: v1 (verdict `INCONCLUSIVE`) stays as reported.
Freeze commit: the commit that introduces this file. Nothing in `v2/results/` existed at freeze.

## Why v2, and a disclosure of bias

v1 showed 6 mutants, all trivially detected, and zero mutants for the structural decoder. v2 tries to
fix those two stated limitations (operator coverage, sample size). **Disclosure:** I had already seen v1
outcomes and had inspected the weak testbenches (comparator-4bit: 5/256 vectors; decoder-2to4: 6/8)
before choosing the v2 operators. To limit hindsight bias the operators are standard textbook classes
(relational/logical/arithmetic operator replacement, unary-operator deletion, constant perturbation,
stuck-at, gate-type replacement) fixed here, in advance, and **no operator may be added, removed or
re-tuned after v2 outcomes are seen**. If an operator turns out useless, that is reported, not removed.

## Task selection rule (applied to specs and testbenches only)

Include a level-0 task iff (a) the published spec determines the observable behavior at the pins the
testbench checks, with no choice that only the testbench resolves, and (b) the verdict for a correct
design does not appear to depend on same-timestamp event ordering. 20 level-0 tasks → **14 included, 6
excluded** with reasons in `tasks.json` (`excluded`): priority-encoder, bitmanip-unit, down-counter,
piso-regs, siso-regs, sipo-regs. The sipo/piso/siso exclusions are conservative judgements from reading,
**not verified by simulation**. Level-1 tasks are out of scope for v2 (cost of authoring and reviewing
more references), so this experiment still covers level 0 only: 9 combinational + 5 sequential designs.
Plus one supplementary (non-spec-compliant decoder style), excluded from primary totals as in v1.

## References and oracles

Evaluator-authored from the spec (`v2/references/`, plus the 3 v1 references), validated before freeze
(`validate_references.py`): all unmodified upstream testbenches PASS, all behaviors equal the independent
oracle (`archxbench_oracles.py`). Assumptions are in each file header. Legal-input assumption: the binary
encoder is compared on its 8 one-hot inputs only (spec: "assumes exactly one input is high"). Sequential
designs: oracle = Python cycle model replayed on a fixed 1,202-cycle reset stimulus. Human sign-off of
references is still pending.

## Operators

`archxbench_ops_v2.py`, documented in its module docstring: all v1 mutants unchanged, then
relational_op_replacement, bitwise_op_replacement, negation_deletion, if_condition_negation,
arith_op_replacement, constant_bit_flip, bit_select_off_by_one, gate_type_replacement, stuck_at_assign.
`harness/mutators/rtl.py` is not modified.

## Categories, equivalence and scoring (unchanged from v1 unless stated)

Same category procedure as `archxbench_analysis.py`. Equivalence evidence: combinational — exhaustive
simulation over legal inputs and a Yosys SAT miter (agreement required); sequential — **unbounded** proof
from reset with SymbiYosys/ABC-PDR (a finite trace can only show a difference, so a trace-identical
mutant without a proof is `INDETERMINATE`). Score = BEHAVIORAL_KILL / (BEHAVIORAL_KILL + SURVIVED),
denominator always printed. Reported per design, per operator, and in aggregate; no design is dropped
after the fact. Every task is run twice for determinism.

## Pre-registered evidence thresholds and verdict rules

- **Sufficient evidence** requires: ≥ 8 designs with ≥ 5 valid non-equivalent mutants each AND ≥ 100
  valid non-equivalent mutants in total. Otherwise the verdict stays `INCONCLUSIVE`.
- If sufficient: INDETERMINATE + TIMEOUT + SETUP_ERROR ≤ 10 % of generated mutants, run1 == run2 for every
  design, and baselines PASS, else `INCONCLUSIVE`; if all hold → `CONDITIONAL_GO` (never `GO`: references
  remain evaluator-authored and no outsider has replicated).
- A high kill score is **not** a success criterion. Discriminative spread (surviving non-equivalent
  mutants exposing testbench gaps) is reported as a finding about the testbenches, not as GateTruth's score.

## Yosys MCY head-to-head (exploratory, descriptive only)

Same references, same unmodified testbenches. MCY mutates the elaborated netlist (`prep`), runs the
iverilog testbench per mutation, and classifies unkilled mutations as formally equivalent or not using the
same miter/SBY procedure. Metrics: mutations enumerated, valid non-equivalent, killed, surviving
non-equivalent, per design. No winner is declared on counts alone: the two tools mutate different
objects (text vs. netlist), so counts are not like-for-like. Anything MCY cannot do in the pinned image is
reported as such.

## Not claimed regardless of outcome

No third-party adoption, no maintainer validation of references, no replication outside this host, no
claim that GateTruth is better than any other tool.
