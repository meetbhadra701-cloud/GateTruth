# 7 Discussion

**PPA gating changes what "good" means.** The headline result — that the strongest
model reaches only about 70% of the human reference score on Track A, and that the
field falls off sharply below it — is driven less by the PPA target than by the
correctness gates. Most lost points come from designs that fail lint, a hidden
vector, or a formal property and are zeroed before PPA is ever computed. This is
the intended behavior: a benchmark that averaged PPA over only the passing subset
would reward a model that produces a few excellent designs and many broken ones.
Severability ties the score to the joint event of being both correct and efficient,
which is the standard a hardware engineer is actually held to.

**Single-shot and agentic ability are distinct.** The two tracks agree on the top
of the ordering but disagree on its shape. On Track A, the top two models are
separated by roughly a point; on Track B, the leader meets nearly twice as many
objectives as the runner-up and is the only model to improve the *median* design's
PPA at all, while several models that produce respectable single-shot RTL meet zero
optimization objectives. Agentic optimization under synthesis-in-the-loop feedback
is not simply a harder version of generation; it demands reading timing reports,
forming a hypothesis, and preserving correctness across edits — a loop most of the
evaluated models do not yet close. That four of seven models score zero on Track B
suggests substantial headroom and makes it a useful target for measuring progress.

**Cost is not a proxy for capability.** In both tracks the most expensive model
was among the weakest, and a small model outscored its larger sibling. Practitioners
choosing a design assistant cannot infer quality from price, which is itself an
argument for task-level, PPA-aware evaluation rather than reliance on general
model reputation.

## 7.1 Limitations

The most important limitation is statistical: each cell is a single run, so we do
not yet report run-to-run variance, and the eight-task Track B rates in particular
should be read as indicative. Repeated-run confidence intervals are the highest
priority for the next revision. The suite is also scoped to one technology
(sky130hd) at fixed clock targets, and it scores pre-route synthesis metrics —
post-route metrics via an open place-and-route flow were disabled for v1.0 after a
platform go/no-go failure, so reported area, timing, and power are synthesis-stage
estimates rather than signoff-quality numbers. Results may not transfer to other
process technologies, larger blocks, or different objective families, and we make
no claim beyond the measured tasks. Finally, the reference designs define the PPA
baseline; a stronger reference would lower every model's score, so absolute numbers
are meaningful only relative to the released references, which we publish in full.

## 7.2 Future work

Natural extensions are repeated-run statistics with confidence intervals;
re-enabling post-route metrics behind a validated place-and-route flow; broadening
coverage to additional technologies, larger designs, and further Track B objective
families; and periodic, balanced expansion of the evaluated model set across
providers as new models appear. The harness, tasks, reference flow, and
leaderboard are released to make such extensions, and independent reproduction,
straightforward.
