# External Audit Provenance

Fetch date: 2026-07-29

Vendor source trees are not redistributed. Only GateTruth-generated JSON reports
containing stable identifiers and hashes are committed. Audit runs mount vendor trees
read-only and execute mutants from temporary copies.

## CVDP benchmark dataset

- Upstream: https://huggingface.co/datasets/nvidia/cvdp-benchmark-dataset
- Pinned revision: `5b807d945f6a99aa645f7e43a64a2115e281b4bf`
- License: [Mixed: CC BY 4.0 / Apache-2.0 / component terms](https://huggingface.co/datasets/nvidia/cvdp-benchmark-dataset/blob/main/LICENSE)
- License SHA-256: `420b96aa803efed64225b1c2dd19052292ad154bdee9ee46a367aef5eae502aa`
- Content SHA-256: `1d53f2670447bc1e924655edab9e1f645d1cac263d98735401b3d0017b1b8931`
- Audited inventory: 302 v1.1.0 nonagentic code-generation no-commercial rows
- Local directory: `external-audit/vendor/cvdp-benchmark-dataset` (gitignored)

## CVDP benchmark harness

- Upstream: https://github.com/NVlabs/cvdp_benchmark.git
- Pinned revision: `8e894cf74414ab1eaea1e2b4e80a02f123df07b6`
- License: [Apache-2.0](https://github.com/NVlabs/cvdp_benchmark/blob/main/LICENSE)
- License SHA-256: `e66b23786e059d855861940946df48e460b6e3e006fbcb6cff939d67fd30b53b`
- Content SHA-256: `78575e0beffdd9a6d1d6e9d8848f8f48f5f86c7e8bcfde0ff9c16a648ef66922`
- Audited inventory: infrastructure only
- Local directory: `external-audit/vendor/cvdp_benchmark` (gitignored)

## RTLLM v2.0

- Upstream: https://github.com/hkust-zhiyao/RTLLM.git
- Pinned revision: `41b26896e33b536940116a975626455eed3de65e`
- License: [MIT](https://github.com/hkust-zhiyao/RTLLM/blob/main/LICENSE)
- License SHA-256: `02c59ee76428147643e255e42deb68fa0cf61b9984e8f9096ed9efc148a5f213`
- Content SHA-256: `03c7354b51550210e0d28e6a6dcddf5e5361c68365403e007e9979d3ae6e6158`
- Audited inventory: 50 design directories with self-checking testbenches
- Local directory: `external-audit/vendor/RTLLM` (gitignored)
