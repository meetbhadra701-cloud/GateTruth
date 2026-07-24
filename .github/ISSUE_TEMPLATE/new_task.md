---
name: New task proposal
about: Propose a new Track A or Track B task
title: "[task] "
labels: new-task
---

**Task name and tier**
Proposed id (e.g. `t2_my_block`) and tier (T1 / T2 / T3, or Track B).

**What it exercises**
The design and the capability it tests (protocol conformance, pipelining,
clock-domain crossing, timing closure, ...). Why it adds coverage the suite
does not already have.

**Interface sketch**
Rough module ports/parameters.

**Edge cases**
List at least eight behavioral edge cases the hidden tests would exercise.

**Formal**
Does the task admit natural formal properties? If so, which.

**Clock target**
Intended clock target and rough justification.

Note: reference designs and hidden vectors require human sign-off before a task is
admitted, and every test suite must kill ≥95% of generated mutants. See
[CONTRIBUTING.md](../../CONTRIBUTING.md).
