# 6 Results

We evaluate seven contemporary models spanning three providers and a wide
capability/price range: Anthropic `claude-opus-4-8`, `claude-sonnet-4-6`, and
`claude-haiku-4-5`; OpenAI `gpt-5` and `gpt-5-mini`; and, via OpenRouter, Google
`gemini-2.5-pro` and Meta `llama-4-maverick`. All numbers below come from the
official evaluation harness at a single pinned toolchain image
(`siliconbench:v1`, digest `sha256:20a6…`), executed under the frozen scoring and
severability rules of Section 5. Each model was run once over the full task set;
transient provider failures (rate limits, connection resets, malformed or empty
responses) are retried in the transport layer with a bounded, deterministic
policy, and every reported run is complete and untruncated (no task fell back to
a baseline submission because of an infrastructure error). Deterministic HTTP 4xx
responses are never retried, so a genuine request-construction bug surfaces rather
than being masked.

## 6.1 Track A: static generation from specification

In Track A the model receives a natural-language specification plus a locked
interface and must emit synthesizable RTL in a single shot. Correctness gates
(lint, simulation against hidden vectors, and formal properties where declared)
are severability gates: a design that fails any gate scores zero for that task.
Surviving designs are scored on the PPA geometric mean against the human
reference, and the per-task score is `100 * min(ppa, 1.5) / 1.5`, so the human
reference design scores **66.67 by construction** and the ceiling (a design
1.5x better than the reference on the PPA geomean) is 100.

Table (eval_table) reports the aggregate score over all 60 tasks.

| Model | Aggregate score | Cost (USD) |
|---|---:|---:|
| claude-opus-4-8 | 46.67 | 1.58 |
| claude-sonnet-4-6 | 45.56 | 0.86 |
| claude-haiku-4-5 | 34.44 | 0.30 |
| gpt-5-mini | 33.33 | 0.20 |
| gpt-5 | 31.11 | 0.93 |
| llama-4-maverick | 25.56 | 0.03 |
| gemini-2.5-pro | 17.78 | 2.16 |
| *human reference* | *66.67* | — |

Three findings stand out. First, **every model trails the human reference by a
wide margin**: the strongest, Opus, reaches 46.67, roughly 70% of the reference
score, and the field falls off steeply from there. The gap is not an artifact of
a punishing PPA target — it is dominated by correctness-gate failures, where a
single hidden-vector mismatch or lint error zeroes an otherwise plausible design.
The benchmark therefore measures a capability current models have not saturated.

Second, **cost and quality are decoupled**. The cheapest run, Llama at three
cents, outscores the most expensive, Gemini at \$2.16, by eight points
(25.56 vs 17.78). Gemini is both the costliest and the lowest-scoring model in the
set, and `gpt-5` scores *below* its smaller sibling `gpt-5-mini` (31.11 vs 33.33)
despite costing roughly 4.5x more. Aggregate spend to evaluate all seven models
across 60 tasks each was approximately \$6.

Third, **the Anthropic models occupy the top three places** in a strict
capability ordering (Opus > Sonnet > Haiku), while the cross-provider ordering is
noisier — a reminder that a single aggregate score compresses correctness and PPA
into one number and should be read alongside the per-tier breakdown.

## 6.2 Track B: agentic PPA repair under budget

Track B is agentic: starting from a correct but deliberately suboptimal baseline,
the model iterates (edit, lint, simulate, synthesize, read timing) under a fixed
token, tool-call, and wall-clock budget, aiming to meet a per-task objective
(close timing, reduce area, reduce power, remove latches, or add a property)
*without* regressing correctness. Objectives are pass/fail; a task counts as met
only if the correctness gates still pass and the objective threshold is reached.

Table (trackb_table) reports objectives met over the 8 Track B tasks and the
median per-task PPA delta relative to baseline.

| Model | Objectives met | Median PPA delta (area / power / WNS) | Cost (USD) |
|---|---:|---|---:|
| claude-opus-4-8 | 5/8 (62.5%) | 0.55x / 0.37x / −1.56 ns | 1.65 |
| claude-sonnet-4-6 | 3/8 (37.5%) | 1.00x / 1.00x / +0.00 ns | 4.16 |
| gpt-5 | 1/8 (12.5%) | 1.00x / 1.00x / +0.00 ns | 3.96 |
| claude-haiku-4-5 | 0/8 | 1.00x / 1.00x / +0.00 ns | 2.04 |
| gemini-2.5-pro | 0/8 | 1.00x / 1.00x / +0.00 ns | 6.59 |
| gpt-5-mini | 0/8 | — | 0.50 |
| llama-4-maverick | 0/8 | — | 0.04 |

Track B is **sharply discriminating**: four of seven models meet *zero*
objectives, and only three make any headway. This is not an artifact of
infrastructure — every run is complete, and the zero-scoring models spent real
effort (Haiku alone consumed \$2.04 in tool calls and Gemini \$6.59), producing
edits that either broke correctness or failed to move PPA past threshold.
Agentic PPA-repair-to-specification is, for most of this field, an unsolved task.

Opus is the clear outlier. It meets **5 of 8 objectives**, and it is the only
model whose *median* task improves PPA at all: a median 45% area reduction, 63%
power reduction, and a 1.56 ns worst-negative-slack improvement. Every other
model's median delta is exactly neutral (1.00x), meaning that even Sonnet
(3/8) and `gpt-5` (1/8) leave the median task untouched — their successes are
concentrated on a minority of tasks while the typical task sees no change. The
eight-task set is small and these rates carry corresponding uncertainty, but the
separation between Opus and the field is large relative to that caveat.

## 6.3 Cross-track observations

The two tracks agree on the top of the ordering — Opus and Sonnet lead both — but
Track B **stretches the top of the distribution** in a way Track A does not. In
Track A, Opus and Sonnet are separated by roughly one point (46.67 vs 45.56); in
Track B, Opus meets nearly twice as many objectives (5 vs 3) and is alone in
improving the median design. Iterative, tool-using PPA optimization exposes a
capability difference that single-shot generation compresses. Conversely, several
models that produce respectable one-shot RTL (Haiku, `gpt-5-mini`) fail Track B
entirely, indicating that agentic self-correction under a synthesis-in-the-loop
budget is a distinct skill from static generation, not merely a harder version of
it. Cost remains decoupled from capability in both tracks: the Track B leader,
Opus, is mid-priced, while the most expensive Track B run (Gemini, \$6.59) meets
no objectives.

## 6.4 Reliability and threats to validity

**Single run per model.** Each cell is one evaluation at temperature 0 (or the
provider's fixed default for reasoning models that reject a temperature
override). Model outputs are not perfectly deterministic, so per-cell scores
carry run-to-run variance we have not yet quantified; the Track B rates in
particular, over only eight tasks, should be read as indicative rather than
precise. Repeated-run confidence intervals are the most important next
measurement.

**Infrastructure vs capability.** An earlier evaluation pass produced spurious
zeros when concurrent load triggered provider rate limits and malformed responses
that truncated agent episodes; we treat such truncations as invalid and re-ran
every affected model in isolation on a transport layer hardened to retry transient
failures while leaving deterministic errors terminal. All results in this section
are from complete, untruncated runs; no reported zero is an infrastructure
artifact.

**Contamination controls.** Every task package carries a unique canary GUID; the
generated site and released artifacts are scanned for canary strings, and the
hidden simulation vectors and reference designs are held in a separate repository
gated on human sign-off. Reported PPA is computed by the same pinned flow used for
the reference, so model and reference designs are measured identically.

**Scope.** The suite is 60 Track A and 8 Track B tasks on a single sky130hd
technology at fixed clock targets; results may not transfer to other PDKs,
larger designs, or different objective families. We make no claim beyond the
measured tasks.
