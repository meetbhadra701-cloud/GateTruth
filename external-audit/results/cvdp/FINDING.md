# CVDP Public Golden-RTL Availability

GateTruth inspected the pinned CVDP v1.1.0 nonagentic code-generation
no-commercial dataset identified in
[`PROVENANCE.md`](../../PROVENANCE.md). The resulting
[`gap_report.json`](gap_report.json) covers 302 rows and records:

- `usable_rows`: 0
- `withheld_output_rows`: 302
- `oss_origin_rows`: 17

This matches the
[pinned CVDP harness README](https://github.com/NVlabs/cvdp_benchmark/blob/8e894cf74414ab1eaea1e2b4e80a02f123df07b6/README.md#front-matter),
which says the release "excluded the reference solutions" (`output` for
nonagentic tasks and `patch` for agentic tasks) "to help mitigate data
contamination." The
[pinned dataset NOTICE](https://huggingface.co/datasets/nvidia/cvdp-benchmark-dataset/blob/5b807d945f6a99aa645f7e43a64a2115e281b4bf/NOTICE)
identifies upstream origins for some rows, but those provenance entries do not
supply known-correct RTL in the public dataset.

A mutation-kill audit must begin with known-correct RTL that passes the
benchmark's unmodified testbench. Because the public CVDP release does not
provide that RTL for any inspected row, GateTruth cannot perform a CVDP
mutation-kill audit against the public release as distributed. No CVDP kill
rate is claimed.

A future audit would require a lawfully available, license-cleared source of
known-correct RTL and a fresh baseline-validation gate.
