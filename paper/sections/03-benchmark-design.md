# 3 Benchmark Design

## 3.1 Two tracks

SiliconBench separates two capabilities that are often conflated. **Track A
(single-shot generation)** gives the model a natural-language specification and a
locked module interface and asks for synthesizable RTL in one attempt, with no
tool feedback. **Track B (agentic PPA repair)** gives the model a correct but
deliberately suboptimal baseline design and a concrete optimization objective, and
lets it iterate against the real synthesis and timing tools — editing the design,
re-linting, re-simulating, re-synthesizing, and reading timing reports — under a
fixed budget. Track A tests what a model knows about good RTL; Track B tests
whether it can *use* the physical-design toolchain to get there.

## 3.2 Task tiers

The 60 Track A tasks are stratified into three tiers by design complexity:

- **Tier 1 (20 tasks)** — combinational and simple sequential blocks: priority
  encoder, Gray/binary converters, barrel shifter, popcount, saturating adder,
  LFSR, PWM, one-hot FSM, edge detector, debouncer, and similar. These isolate
  basic synthesizable-RTL competence.
- **Tier 2 (25 tasks)** — protocol and interface blocks: synchronous FIFO, UART
  transmit and receive, SPI master and slave, I2C slave, an AXI4-Lite register
  file, round-robin and priority-interrupt arbiters, clock-domain-crossing
  synchronizers, stream up/down-sizers, a memory-mapped timer, and a watchdog.
  These exercise protocol conformance, back-pressure, and multi-clock discipline.
- **Tier 3 (15 tasks)** — datapath and control-heavy designs: a pipelined
  multiplier and sequential divider, a fixed-point MAC, an 8x8 systolic PE tile,
  loadable and fixed FIR filters, a first-order IIR filter, a Booth multiplier,
  parallel CRC32, an AES S-box datapath, a cache-tag comparator, and a saturating
  accumulator. These stress pipelining, arithmetic, and area/timing trade-offs.

The 8 Track B tasks are built on Track A designs and span the objective families
*close timing*, *reduce area*, *reduce power*, *remove inferred latches*, and *add
a formal property* — for example, closing timing on a fixed-point MAC and a
multiplier, reducing area on an FIR filter, reducing power on an IIR filter,
removing latches from a decoder, making a FIFO clock-domain-crossing-safe, and
adding byte-enable support to an AXI datapath.

## 3.3 Task package

Every task is a self-contained package with a fixed structure: a natural-language
`spec.md` carrying a unique canary; a locked `interface.sv` defining ports and
parameters the submission must match exactly; a human-reviewed reference design in
`ref/`; a `tb/` directory with a public smoke test and a held-out hidden test
suite; a `formal/` directory of properties for tasks where formal verification is
natural; a `constraints.sdc` giving the clock target; and a `task.yaml` recording
tier, clock, formal flag, and PPA weights. Track B packages additionally ship the
suboptimal `baseline/` design and an `objective.yaml` specifying the target and
the token, tool-call, and wall-clock budget.

Two authoring gates apply before any task is admitted: each task must enumerate at
least eight behavioral edge cases exercised by its hidden tests, and its test
suite must achieve at least a 95% mutation-kill rate (Section 4.4). The reference
design and hidden vectors of every task require explicit human sign-off; models
never see the hidden vectors or the reference.
