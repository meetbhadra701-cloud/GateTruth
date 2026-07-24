<h1 align="center">SiliconBench</h1>

<p align="center">
  <strong>A PPA-aware benchmark for LLM &amp; agent RTL design.</strong><br>
  Not just <em>does the hardware work</em> — <em>is it good silicon?</em>
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: Apache 2.0" src="https://img.shields.io/badge/License-Apache_2.0-blue.svg"></a>
  <img alt="Python 3.11" src="https://img.shields.io/badge/python-3.11-blue.svg">
  <img alt="Platform linux/amd64" src="https://img.shields.io/badge/platform-linux%2Famd64-lightgrey.svg">
  <img alt="EDA: open-source" src="https://img.shields.io/badge/EDA-Yosys%20%7C%20OpenSTA%20%7C%20sky130-green.svg">
  <img alt="Reproducible" src="https://img.shields.io/badge/results-byte--reproducible-success.svg">
</p>

---

Most benchmarks for language-model hardware design stop at **functional
correctness** — does the generated Verilog simulate? But correctness is the entry
fee in digital design, not the goal. A working divider that is twice the area,
misses timing, or burns needless power is a *bad* design. SiliconBench carries
every submission through a **real, pinned open-source ASIC flow** (synthesis +
static timing/power on the sky130 technology) and scores it on **power,
performance, and area** relative to a human-reviewed reference — with correctness
as a hard gate, so a design that is wrong scores zero no matter how small or fast.

## Leaderboard (v1.0)

Seven models, evaluated under the official pinned flow. The human reference scores
**66.67 by construction**; every model trails it.

### Track A — single-shot RTL generation (60 tasks)

| Rank | Model | Score / 100 |
|:---:|---|---:|
| 🥇 | Claude Opus 4.8 | **46.67** |
| 🥈 | Claude Sonnet 4.6 | 45.56 |
| 🥉 | Claude Haiku 4.5 | 34.44 |
| 4 | GPT-5-mini | 33.33 |
| 5 | GPT-5 | 31.11 |
| 6 | Llama 4 Maverick | 25.56 |
| 7 | Gemini 2.5 Pro | 17.78 |
| — | *human reference* | *66.67* |

### Track B — agentic PPA repair (8 tasks)

| Rank | Model | Objectives met |
|:---:|---|:---:|
| 🥇 | Claude Opus 4.8 | **5 / 8** |
| 🥈 | Claude Sonnet 4.6 | 3 / 8 |
| 🥉 | GPT-5 | 1 / 8 |
| — | Haiku 4.5 · GPT-5-mini · Gemini 2.5 Pro · Llama 4 Maverick | 0 / 8 |

Even the strongest model reaches ~70% of the human reference on generation, and
four of seven make no progress at all on agentic optimization. Cost does not track
quality. See the [paper](#citation) for full per-tier results and analysis.

## Two tracks

- **Track A — RTL generation.** The model receives a natural-language spec and a
  locked interface and emits one synthesizable SystemVerilog module, scored
  through the correctness gates and the PPA pipeline.
- **Track B — agentic optimization.** An agent iterates against the synthesis and
  timing tools — editing, re-linting, re-simulating, re-synthesizing — to meet a
  concrete objective (close timing, reduce area/power, remove latches) under an
  explicit token, time, tool-call, and spend budget, with a sequential-equivalence
  gate that forbids changing what the design computes.

## How scoring works

A submission passes six stages. Stages 0–2 are **correctness gates** — each
independently zeroes the score on failure (severability):

| Stage | Check | Tool |
|---|---|---|
| 0 | Lint | `verilator --lint-only` |
| 1 | Simulation vs. hidden vectors | Icarus + cocotb |
| 2 | Formal properties (where declared) | SymbiYosys |
| 3–5 | Synthesis, timing, power | Yosys + OpenSTA (sky130hd) |

Surviving designs are scored on the PPA geometric mean against the reference:

```
ppa        = geomean(ref_area/area, ref_delay/delay, ref_power/power)
task_score = 100 * min(ppa, 1.5) / 1.5
```

The reference scores `ppa = 1.0` → `66.67`; the 100-point ceiling is a design 1.5×
better than the reference. Correctness is a **gate, not a weight**, so a model
cannot win by removing functionality.

## Quickstart

Build the pinned image from the repository root:

```bash
docker build --platform linux/amd64 -t siliconbench:v1 -f flows/Dockerfile .
```

Score a reference design through the Track A pipeline:

```bash
docker run --rm -v "$PWD:/work" -w /work siliconbench:v1 ./siliconbench run \
  --task t1_gray_counter \
  --submission tasks/t1_gray_counter/ref/ref.sv \
  --out results/refs/t1_gray_counter.json
```

Build the static leaderboard site from signed result manifests:

```bash
docker run --rm -v "$PWD:/work" -w /work siliconbench:v1 ./siliconbench site
```

## Repository layout

```
tasks/       60 Track A task packages (spec, interface, reference, tests, constraints)
tasksB/       8 Track B agentic task packages (baseline, objective, budget)
harness/     evaluation harness — CLI, scoring, provider adapters, spend ledger
flows/       pinned Docker image + synthesis/timing/power flow scripts
scripts/     reproduction and contamination-scan utilities
site/        static leaderboard generator
paper/       auto-generated result/task tables
docs/        design and methodology documentation
```

Each task is a self-contained package: an original-prose spec (with a unique
canary), a locked interface, a human-reviewed reference, public smoke + held-out
hidden tests, formal properties where natural, and a timing constraint. Reference
designs and hidden vectors require human sign-off; models never see them.

## Reproducibility &amp; integrity

- **Pinned flow.** Every score is computed inside one content-addressed image, so
  a result is a function of the design, not the tool versions.
- **Signed manifests.** Each run emits a manifest signed with a SHA-256 over its
  canonical JSON; re-running a design reproduces the signature byte-for-byte.
- **Mutation-gated tests.** Every task's test suite must kill ≥95% of injected RTL
  mutants before the task is admitted.
- **Contamination controls.** Per-task canaries, a sign-off-gated hidden-vector
  set, and a pre-publication canary scan.

## Contributing

New tasks, bug reports, and model requests are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md). Please read the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Citation

A paper describing SiliconBench is in preparation. Until then, please cite the
repository (see [CITATION.cff](CITATION.cff)).

## License

[Apache License 2.0](LICENSE).
