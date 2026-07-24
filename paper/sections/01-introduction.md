# 1 Introduction

Large language models can write register-transfer-level (RTL) hardware in
Verilog and SystemVerilog, and a growing body of benchmarks measures how often
that RTL is *functionally correct*. Correctness, however, is only the entry fee
in real hardware design. A working divider that is twice the area, misses timing,
or burns excess power than it needs to is, in practice, a bad design — and the
gap between "compiles and simulates" and "is a design an engineer would ship" is
precisely the part that functional benchmarks do not measure. As models begin to
be proposed as design assistants, the field needs an evaluation that asks the
question a hardware engineer actually asks: not just *is it correct*, but *is it
good*.

We introduce **SiliconBench**, a benchmark that scores model-generated RTL on
power, performance, and area (PPA) by carrying every submission through a real,
pinned open-source ASIC implementation flow — logic synthesis and static timing
and power analysis on the open sky130 technology — and comparing the result to a
human-reviewed reference design. PPA is meaningless without correctness, so
SiliconBench treats correctness as a *severability gate*: lint, simulation against
held-out vectors, and formal property checks each independently zero a submission
that fails them, and only surviving designs are scored on PPA. This composition —
correctness as a gate, PPA as the score — is the benchmark's central design
choice, and it is what lets a single number distinguish a model that produces
correct-but-mediocre RTL from one that produces correct-and-efficient RTL.

SiliconBench evaluates two capabilities that we argue are distinct. **Track A**
measures single-shot generation: given a specification and a locked interface,
emit synthesizable RTL in one attempt. **Track B** measures agentic optimization:
starting from a correct but deliberately suboptimal baseline, iterate against the
synthesis and timing tools under a fixed token, tool-call, and wall-clock budget
to meet a concrete PPA objective — close timing, reduce area, reduce power, or
remove inferred latches — without regressing correctness, verified by sequential
equivalence against the baseline. Track B is, to our knowledge, the first RTL
benchmark to place a model *inside* the physical-design feedback loop and score
the outcome.

Our contributions are: (1) a PPA-aware RTL benchmark with correctness as a
severability gate and a reference-relative PPA score, spanning 60 single-shot
tasks across three difficulty tiers and 8 agentic optimization tasks; (2) a fully
pinned, reproducible open-source evaluation harness that emits signed, byte-stable
result manifests, with test adequacy enforced by mutation testing and
contamination controlled by per-task canaries and a sign-off-gated hidden-vector
repository; and (3) an evaluation of seven contemporary models across three
providers, showing a large gap to the human reference on single-shot generation,
a decoupling of cost from quality, and a sharply discriminating agentic track on
which most models make no progress at all.
