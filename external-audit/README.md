# External Mutation Audit Reproduction

This directory contains a private, pre-publication GateTruth audit artifact.
Do not cite it publicly or use it in outreach without Architect approval.

## Frozen Inputs

- GateTruth artifact commit: `6cd91ce`
- GateTruth audit implementation recorded in every result: `5ea85d0`
- Seed: `20260729`
- RTLLM revision: `41b26896e33b536940116a975626455eed3de65e`
- RTLLM content SHA-256:
  `03c7354b51550210e0d28e6a6dcddf5e5361c68365403e007e9979d3ae6e6158`
- Local image used: `gatetruth:v1`,
  `sha256:4252e032bfbf6eaf86fda83668d44c945ddb446dabbfbfc1cf577109960da578`

The vendor revision, license hash, and content hash are also pinned in
[`PROVENANCE.md`](PROVENANCE.md) and `provenance.lock.json`. Vendor source is
never committed.

## Exact Reproduction

Run from a clean GateTruth checkout. The setup commands require network access
only to clone the pinned RTLLM revision and build the GateTruth image. The
mutation commands run with networking disabled and the repository, including
the vendor tree, mounted read-only.

```bash
git checkout 6cd91ce
docker build --platform linux/amd64 -t gatetruth:v1 -f flows/Dockerfile .

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$PWD,dst=/work" \
  --workdir /work \
  gatetruth:v1 \
  python external-audit/fetch_vendor.py --only rtllm

git -C external-audit/vendor/RTLLM status --porcelain
```

The final command must print nothing. The fetcher pins the checkout text
convention so the content hash is identical on Linux, macOS, and Windows
hosts.

Prepare an empty writable output directory:

```bash
OUT="$PWD/build/external-audit-output"
test ! -e "$OUT"
mkdir -p "$OUT/final" "$OUT/redo"
chmod -R 0777 "$OUT"
```

Run all 50 catalogued designs sequentially:

```bash
docker run --rm \
  --network none \
  --cap-drop=ALL \
  --security-opt no-new-privileges \
  --memory=4g \
  --pids-limit=512 \
  -e GATETRUTH_GIT_COMMIT=5ea85d0 \
  --mount "type=bind,src=$PWD,dst=/work,readonly" \
  --mount "type=bind,src=$OUT,dst=/output" \
  --workdir /work \
  gatetruth:v1 \
  python external-audit/run_audit.py \
    --suite rtllm \
    --designs all \
    --seed 20260729 \
    --out /output/final
```

Derive the real 20% sample from the completed reports, then rerun only those
designs with the same seed:

```bash
SAMPLED="$(
  docker run --rm \
    --network none \
    --mount "type=bind,src=$PWD,dst=/work,readonly" \
    --mount "type=bind,src=$OUT,dst=/output" \
    --workdir /work \
    gatetruth:v1 \
    python external-audit/package_results.py \
      --final-dir /output/final \
      --seed 20260729 \
      --print-sample
)"

docker run --rm \
  --network none \
  --cap-drop=ALL \
  --security-opt no-new-privileges \
  --memory=4g \
  --pids-limit=512 \
  -e GATETRUTH_GIT_COMMIT=5ea85d0 \
  --mount "type=bind,src=$PWD,dst=/work,readonly" \
  --mount "type=bind,src=$OUT,dst=/output" \
  --workdir /work \
  gatetruth:v1 \
  python external-audit/run_audit.py \
    --suite rtllm \
    --designs "$SAMPLED" \
    --seed 20260729 \
    --out /output/redo
```

Generate the summary from the raw JSON and verify every sampled report:

```bash
docker run --rm \
  --network none \
  --mount "type=bind,src=$PWD,dst=/work,readonly" \
  --mount "type=bind,src=$OUT,dst=/output" \
  --workdir /work \
  gatetruth:v1 \
  python external-audit/package_results.py \
    --final-dir /output/final \
    --redo-dir /output/redo \
    --seed 20260729 \
    --metadata /output/determinism.json \
    --summary /output/summary.md

diff -r external-audit/results/rtllm/final "$OUT/final"
diff -r external-audit/results/rtllm/redo "$OUT/redo"
diff external-audit/results/rtllm/determinism.json "$OUT/determinism.json"
diff external-audit/results/summary.md "$OUT/summary.md"
git -C external-audit/vendor/RTLLM status --porcelain
```

All five comparison/status commands must produce no output.

## Measured Run

On the certification host using the image above:

- Full 50-design sequential audit: `1251.147 s`
- Eight-design determinism rerun: `175.371 s`
- Report packaging: under `2 s`

Setup requires only a few minutes of active work. The two mutation commands run
unattended.

The committed result is:

- 50 designs reported
- 44 audited
- 6 unsupported
- 751 mutants
- 418 killed
- 318 survived
- 15 indeterminate
- Aggregate kill fraction: `418/751`

The generated per-design table, including zero and 100 percent kill rates, is
[`results/summary.md`](results/summary.md). The deterministic sample is stored
in `results/rtllm/determinism.json`.

## Eligibility and Verdicts

A design is `audited` only when its unmodified golden source passes its shipped
testbench under the catalogued Icarus flow. A baseline compile, simulation, or
pass-banner failure makes the design `unsupported`; no mutants are run and no
0 percent kill rate is inferred.

Each mutant runs once with a 20-second test timeout. A timeout receives one
60-second disambiguation retry. A compile or test failure is `killed`, a
passing test is `survived`, and a second timeout is `indeterminate`.
Indeterminate mutants remain in the kill-rate denominator. Certification is
strictly sequential.

The six unsupported designs are:

- `asyn_fifo`: its testbench uses the unsupported `break` task.
- `clkgenerator`: Icarus rejects the output-port connection during elaboration.
- `freq_divbyodd`: Icarus rejects a continuous assignment driving a `reg`.
- `multi_8bit`: Icarus rejects the shipped `for` loop syntax.
- `radix2_div`: the unmodified golden fails its shipped functional check.
- `ring_counter`: Icarus rejects the `reg` drive and requires SystemVerilog for
  the testbench's whole-array assignment.

## Known Limitations

- Mutation generation uses only GateTruth's generic text-level operators:
  comparator-boundary flip, operator inversion, logic inversion, bitwise
  inversion, shift inversion, reset-polarity flip, dropped-enable, assignment
  deletion, output inversion, assignment hold, and blocking-output inversion.
  No GateTruth task-specific mutation specification is used.
- Results measure the shipped testbenches under Icarus Verilog-2001. They do
  not claim compatibility with, or equivalence to, RTLLM's VCS environment.
- The six unsupported baselines are reported but are not assigned mutation
  kill rates.
- Double timeouts are conservatively indeterminate and count against the kill
  rate.
- CVDP is not mutation-audited because its public release provides no usable
  golden RTL in the inspected 302 rows. See `results/cvdp/FINDING.md`.
