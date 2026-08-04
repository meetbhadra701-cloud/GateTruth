# External Mutation Audit Reproduction

This directory contains a private, pre-publication GateTruth audit artifact.
Do not cite it publicly or use it in outreach without Architect approval.

## Frozen Inputs

- GateTruth artifact commit: `6cd91ce`
- GateTruth audit implementation recorded in every g2001-condition result: `5ea85d0`
- GateTruth audit implementation recorded in every g2012-condition result
  (`results/rtllm/final-g2012/`, `results/rtllm/redo-g2012/`; this is the paper's reported
  condition): `564ac46d0d912711db799b07a42720b98588e9c1`
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

## Exact Reproduction (g2012, reported condition)

Everything through "Prepare an empty writable output directory" above is shared setup --
checkout, image build, and vendor fetch do not depend on the language-generation mode. This
section replaces only the two `run_audit.py` invocations and the final packaging/diff step with
their `-g2012` equivalents; `--generation-flag` defaults to `-g2001` when omitted, which is why
the section above never passes it.

```bash
mkdir -p "$OUT/final-g2012" "$OUT/redo-g2012"

docker run --rm \
  --network none \
  --cap-drop=ALL \
  --security-opt no-new-privileges \
  --memory=4g \
  --pids-limit=512 \
  -e GATETRUTH_GIT_COMMIT=564ac46d0d912711db799b07a42720b98588e9c1 \
  --mount "type=bind,src=$PWD,dst=/work,readonly" \
  --mount "type=bind,src=$OUT,dst=/output" \
  --workdir /work \
  gatetruth:v1 \
  python external-audit/run_audit.py \
    --suite rtllm \
    --designs all \
    --seed 20260729 \
    --generation-flag=-g2012 \
    --out /output/final-g2012
```

Derive the real 20% sample from the completed g2012 reports, then rerun only those designs with
the same seed and generation flag:

```bash
SAMPLED_G2012="$(
  docker run --rm \
    --network none \
    --mount "type=bind,src=$PWD,dst=/work,readonly" \
    --mount "type=bind,src=$OUT,dst=/output" \
    --workdir /work \
    gatetruth:v1 \
    python external-audit/package_results.py \
      --final-dir /output/final-g2012 \
      --seed 20260729 \
      --print-sample
)"

docker run --rm \
  --network none \
  --cap-drop=ALL \
  --security-opt no-new-privileges \
  --memory=4g \
  --pids-limit=512 \
  -e GATETRUTH_GIT_COMMIT=564ac46d0d912711db799b07a42720b98588e9c1 \
  --mount "type=bind,src=$PWD,dst=/work,readonly" \
  --mount "type=bind,src=$OUT,dst=/output" \
  --workdir /work \
  gatetruth:v1 \
  python external-audit/run_audit.py \
    --suite rtllm \
    --designs "$SAMPLED_G2012" \
    --seed 20260729 \
    --generation-flag=-g2012 \
    --out /output/redo-g2012
```

Generate the summary from the raw JSON and verify every sampled report. `package_results.py`
takes no `--generation-flag` of its own -- it reads each raw report's already-recorded `notes`
field, written by `run_audit.py` above, rather than being told the flag a second time:

```bash
docker run --rm \
  --network none \
  --mount "type=bind,src=$PWD,dst=/work,readonly" \
  --mount "type=bind,src=$OUT,dst=/output" \
  --workdir /work \
  gatetruth:v1 \
  python external-audit/package_results.py \
    --final-dir /output/final-g2012 \
    --redo-dir /output/redo-g2012 \
    --seed 20260729 \
    --metadata /output/determinism-g2012.json \
    --summary /output/summary-g2012.md

diff -r external-audit/results/rtllm/final-g2012 "$OUT/final-g2012"
diff -r external-audit/results/rtllm/redo-g2012 "$OUT/redo-g2012"
diff external-audit/results/rtllm/determinism-g2012.json "$OUT/determinism-g2012.json"
diff external-audit/results/summary-g2012.md "$OUT/summary-g2012.md"
git -C external-audit/vendor/RTLLM status --porcelain
```

All five comparison/status commands must produce no output. Note the different
`GATETRUTH_GIT_COMMIT` above (`564ac46d...`, not `5ea85d0`): every g2012-condition result records
that longer commit as the implementation that produced it (see "Frozen Inputs"), and reproducing
against a different harness commit is a different experiment, not a verification of this one.

## Measured Run (g2012, reported condition)

The run above uses Icarus's `-g2001` language mode. The paper's headline RTLLM audit numbers
use `-g2012` instead (`--generation-flag=-g2012`; note the `=` -- `run_audit.py`'s argparse
otherwise reads a `-g...` value as another flag), because that is the newer, better-supported
language generation and the condition this audit reports as primary. It was re-run in full
against the same catalog, seed, and vendor tree:

- 50 designs reported
- 46 audited
- 4 unsupported
- 775 mutants
- 440 killed
- 335 not killed (320 survived, 15 indeterminate)
- Aggregate kill fraction: `440/775`
- Determinism sample (9, derived the same way as the g2001 sample above): `instr_reg`,
  `traffic_light`, `multi_booth_8bit`, `freq_divbyfrac`, `barrel_shifter`, `edge_detect`,
  `comparator_4bit`, `alu`, `serial2parallel`
- Determinism result: byte-identical per-design JSON (`results/rtllm/determinism-g2012.json`)

Two designs change eligibility between language modes: `freq_divbyodd` and `multi_8bit` are
`unsupported` under `-g2001` (Icarus rejects their syntax) but `audited` under `-g2012`, which
is why g2012 has fewer unsupported designs (4, not 6) and more total mutants (775, not 751)
despite auditing the same 50-design catalog. The four designs unsupported under both modes are
`asyn_fifo`, `clkgenerator`, `radix2_div`, and `ring_counter`, for the reasons given below.
Per-design g2012 results live in `results/rtllm/final-g2012/` and
[`results/summary-g2012.md`](results/summary-g2012.md).

Every `notes` field in `results/rtllm/final-g2012/*.json` and `results/rtllm/sweep-g2012.json`
now correctly records the generation flag actually used. An earlier committed version of this
audit hardcoded the string ``Icarus Verilog-2001`` into every design's notes regardless of which
flag ran, including the g2012 runs; that was a provenance-recording bug in
`external-audit/sweep_rtllm.py`, not a scoring error; the kill rates, mutant counts, and verdicts
above are unaffected and were verified byte-identical against the pre-fix numbers before this fix
was committed.

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
- Results measure the shipped testbenches under two Icarus language modes,
  `-g2001` and `-g2012` (see "Measured Run (g2012, reported condition)" above); neither claims
  compatibility with, or equivalence to, RTLLM's VCS environment.
- The six unsupported baselines are reported but are not assigned mutation
  kill rates.
- Double timeouts are conservatively indeterminate and count against the kill
  rate.
- CVDP is not mutation-audited because its public release provides no usable
  golden RTL in the inspected 302 rows. See `results/cvdp/FINDING.md`.
