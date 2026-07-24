# 4 Evaluation Methodology

## 4.1 Pinned flow

Every submission is evaluated inside a single pinned container image
(`siliconbench:v1`, linux/amd64, referenced by digest) so that scores are a
function of the design alone, not of tool versions. The image fixes Verilator 5.x,
Icarus Verilog 12.x, an oss-cad-suite release providing Yosys with the yosys-slang
SystemVerilog front end, SymbiYosys, boolector, and eqy, plus OpenSTA, cocotb, and
Python 3.11, and the sky130hd liberty and LEF cell library subset. The same image
and the same reference flow produce both the model's metrics and the reference's,
so the two are always measured identically.

## 4.2 Pipeline and correctness gates

A submission passes through six stages. Stages 0-2 are **correctness gates**, each
of which independently zeroes the task score on failure (severability):

- **Stage 0 — lint:** `verilator --lint-only`.
- **Stage 1 — simulation:** Icarus Verilog with cocotb, running the held-out
  hidden vectors; any failing test zeroes the task.
- **Stage 2 — formal:** SymbiYosys on the task's properties, for tasks marked
  `formal: true`.

Stages 3-5 produce the PPA metrics on surviving designs: **synthesis** (Yosys with
yosys-slang, mapped to sky130hd), **static timing** (OpenSTA worst-path delay at
the task's clock target), and **power** (OpenSTA). A planned Stage 6 of
post-route metrics via OpenROAD was disabled for v1.0 after a native-amd64
go/no-go failure (an illegal-instruction fault in clock-tree synthesis); stages
0-5 carry the benchmark, and manifests record Stage 6 as skipped. This decision
and its consequences are documented in the released architecture-decision record.

Track B adds a **sequential-equivalence gate**: the optimized design must be
proven equivalent to the baseline with eqy, and any modification to the test
bench, formal properties, constraints, or task configuration disqualifies the
task outright. This prevents a model from "optimizing" by weakening the tests.

## 4.3 Score

For a design that clears all applicable gates, let `ref_*` denote the reference's
area, worst-path delay, and power, and `area`, `delay`, `power` the submission's.
The PPA figure of merit and per-task score are:

```
ppa        = geomean(ref_area / area, ref_delay / delay, ref_power / power)
task_score = 100 * min(ppa, 1.5) / 1.5
```

A design that matches the reference on all three axes scores `ppa = 1.0` and
`task_score = 66.67`; the human reference therefore scores **66.67 by
construction**, and the 100-point ceiling corresponds to a design 1.5x better than
the reference on the PPA geometric mean. The 1.5 cap bounds the reward for any
single axis and prevents degenerate exploits (for example, trading all timing
margin for area). Delay is the worst-path delay at the task's clock target as
reported by OpenSTA. The Track A leaderboard reports pass@1, mean PPA over passed
tasks, an aggregate score, and a per-tier breakdown; the Track B leaderboard
reports objective-met rate, median PPA delta versus baseline, and median token,
tool-call, and wall-clock cost.

## 4.4 Test adequacy via mutation

Because correctness gating is only as strong as the hidden tests behind it, each
task's test suite must kill at least 95% of a generated set of RTL mutants before
the task is admitted. Mutation runs are executed sequentially and treat a timed-out
mutant as indeterminate rather than killed, so that load-induced timeouts cannot
inflate the kill rate. This gate is what licenses the severability design: a
model cannot pass Stage 1 with a subtly wrong design, because the hidden suite is
demonstrably sensitive to injected faults.

## 4.5 Contamination and reproducibility

Each specification embeds a unique canary GUID; released artifacts, including the
generated leaderboard site, are scanned for canary strings before publication.
Reference designs and hidden vectors live in a separate repository gated on human
sign-off and are never shipped with the public task package, so models cannot see
the answers. Every evaluation emits a result manifest signed with a SHA-256 over
its canonical JSON (excluding volatile fields such as timestamp and wall-clock
time), making runs byte-reproducible and tamper-evident; a re-run of the same
design under the same image reproduces the manifest signature exactly.
