# SiliconBench

SiliconBench is a PPA-aware benchmark for evaluating RTL design systems with open-source EDA
tools. It measures functional correctness, synthesis area, static timing, and estimated power in a
pinned `linux/amd64` environment.

The benchmark has two tracks:

- **Track A - RTL generation:** a model receives a specification and locked interface, produces one
  SystemVerilog module, and is scored through the correctness and PPA pipeline.
- **Track B - agentic optimization:** an agent edits a sandboxed design against a measurable timing,
  area, power, or property objective under explicit token, time, tool-call, and spend budgets.

## Status

M1 proof-of-loop is complete. The 60-task Track A suite and eight Track B packages are implemented,
and the first model evaluation has been scored through the full pipeline. Official results remain
subject to the task review gates recorded in each package.

## Quickstart

Build the pinned image from the repository root:

```powershell
docker build --platform linux/amd64 -t siliconbench:v1 -f flows/Dockerfile .
```

Run the `t1_gray_counter` reference through the Track A pipeline:

```powershell
docker run --rm -v "${PWD}:/work" -w /work siliconbench:v1 ./siliconbench run `
  --task t1_gray_counter `
  --submission tasks/t1_gray_counter/ref/ref.sv `
  --out results/refs/t1_gray_counter.json
```

The static [leaderboard](site/build/index.html) is generated from signed result manifests with:

```powershell
docker run --rm -v "${PWD}:/work" -w /work siliconbench:v1 ./siliconbench site
```

The project is licensed under [Apache License 2.0](LICENSE).
