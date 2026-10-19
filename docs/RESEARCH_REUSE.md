# Using GateTruth in independent research

**Paper:** [GateTruth: Auditing the Rigor of RTL Design Benchmarks via Mutation Testing](https://arxiv.org/abs/2608.12635) (2026).  
**Software:** [GitHub repository](https://github.com/meetbhadra701-cloud/GateTruth) (Apache-2.0).  
**Machine-readable citation:** [CITATION.cff](../CITATION.cff).

GateTruth asks a narrower question than "is this RTL benchmark correct?": *when a specified fault is introduced into a reference RTL implementation, does a particular testbench detect it?*

## Research applications

| Research area | Appropriate use | Appropriate output |
|---|---|---|
| LLM-generated RTL benchmark design | Assess sensitivity of the evaluation testbench to defined RTL mutations | Kill/survival outcomes, valid/inconclusive counts, operator distribution |
| Testbench generation (including structural or LLM-based) | Compare testbenches against the **same** valid mutant set and common simulation budget | Paired per-mutant outcomes and detection rates |
| RTL bug repair | Supply controlled faulty RTL and associated reference/spec to test repair pipelines | Repair success using an independent correctness oracle |
| Hardware-design agents | Add fault-sensitivity auditing as a supplementary evaluation dimension | Detection analysis alongside functional, PPA, and cost metrics |
| Coverage research | Compare code/functional coverage against mutation detection | Coverage metrics and per-mutant detection outcomes |

## Interpretation cautions

- **Mutation survival is not proof of an erroneous testbench:** a mutant may be functionally equivalent under legal inputs, outside the natural-language specification's obligations, or unreachable.
- **Mutation killing is not proof of complete specification coverage:** it tests only the faults actually introduced.
- **Do not conflate golden-reference divergence with specification violation.** When possible, independently adjudicate the mutant against the task specification and report ambiguities.
- **State the mutation-operator distribution, validity/exclusion rules, and stimulus/time budgets.** Kill rates can change when any of these change.
- **The 95% floor used for GateTruth's internal audit is a declared analysis threshold, not a universal standard or formal certificate.**
- **Do not silently pool incomparable mutant sets** across different designs. Report task-level statistics, denominators, and operator-stratified results.
- For cross-tool comparisons, use **the same mutant IDs** for every tested tool and make any simulator/environment differences visible.
- Follow the existing repository security and reproducibility instructions. Some official model score reproductions need maintainer-held hidden data, as described in the root README.

## A minimal independent replication report

Include:

1. Source benchmark/testbench and pinned revision or artifact hash.
2. Reference RTL and public task specification used for comparison.
3. Mutation operators and random seeds, with generated/valid/equivalent/invalid/inconclusive counts.
4. Testbench commands, simulator and tool versions, runtime constraints, and legal input assumptions.
5. Per-mutant detection outcome, including why any mutant was excluded.
6. Task-wise mutation-detection rates and confidence/uncertainty assessment where appropriate.
7. Results for any baseline testbenches, using the same accepted mutants.
8. Limits of the conclusions and any deviations from the original GateTruth workflow.

## How to engage

If you want to reproduce or extend the methodology, open an issue describing the benchmark, your available artifacts and execution environment, and the specific comparison you want to test. The maintainer can help identify relevant task packages and reproduction scripts. Negative and null results are welcome.

If the method, dataset or findings materially support a publication, cite the [GateTruth preprint](https://arxiv.org/abs/2608.12635). Citations should reflect actual scholarly use; no citation is expected in exchange for technical help.
