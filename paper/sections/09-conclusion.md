# 9 Conclusion

SiliconBench evaluates language models and agents on hardware design the way a
hardware engineer is evaluated: not only on whether the RTL is correct, but on
whether it is efficient once carried through a real synthesis and timing flow. By
making correctness a severability gate and PPA the score, and by measuring both
single-shot generation and agentic, tool-in-the-loop optimization, the benchmark
exposes a capability current models have not saturated — every evaluated model
trails a human reference on generation, cost does not track quality, and most
models make no progress at all on agentic PPA repair. The evaluation is built to
be trusted and reproduced: a pinned flow, signed and byte-stable manifests,
mutation-gated test suites, canary-based contamination controls, and a
sign-off-gated hidden-vector set. We release the harness, tasks, reference
designs, and leaderboard so that PPA-aware progress in hardware-design models can
be measured openly and extended by the community.
