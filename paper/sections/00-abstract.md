# Abstract

We present SiliconBench, a power-, performance-, and area-aware (PPA) benchmark
for evaluating large language models and agents on register-transfer-level (RTL)
hardware design. Unlike prior RTL benchmarks that score functional correctness
alone, SiliconBench measures whether a model's *correct* design is also a *good*
one, by pushing every submission through a pinned open-source ASIC flow
(synthesis and static timing/power analysis on the sky130 technology) and scoring
it on the geometric mean of area, delay, and power relative to a human-reviewed
reference. The benchmark comprises two tracks: Track A, single-shot RTL generation
from a natural-language specification and a locked interface (60 tasks across
three difficulty tiers); and Track B, agentic PPA repair, in which a model
iterates against synthesis-in-the-loop tooling under a fixed budget to optimize a
correct-but-suboptimal baseline (8 tasks). Correctness gates — lint, simulation
against held-out vectors, and formal property checks — are severability gates: a
design that is wrong scores zero regardless of its PPA. Test adequacy is enforced
by a mutation-kill threshold, contamination by per-task canaries and a
sign-off-gated hidden-vector repository, and reproducibility by signed, byte-stable
result manifests. Evaluating seven contemporary models, we find that all trail the
human reference by a wide margin on Track A, that cost and quality are decoupled,
and that Track B is sharply discriminating: four of seven models meet zero
optimization objectives, and only one improves the median design's PPA. We release
the harness, tasks, reference flow, and leaderboard to support reproducible,
PPA-aware evaluation of hardware-design models.
