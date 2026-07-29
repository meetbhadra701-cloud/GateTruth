# Reference PPA metrics

`reference_metrics.json` is the committed scoring denominator for the 60-task
Track A suite. It is derived from the signed reference manifests produced by
`gatetruth:v1`, not from model submissions.

Regenerate it only after an intentional reference RTL, flow, task clock, or
image change:

```bash
python scripts/generate_reference_metrics.py \
  --input-dir results/refs \
  --out harness/reference_metrics.json
python scripts/generate_reference_metrics.py \
  --input-dir results/refs \
  --out harness/reference_metrics.json \
  --check
```

The generator requires exactly one signed manifest for each canonical Track A
task, requires every reference gate to pass, and requires one shared Docker
digest. It stores the exact area and power measurements and derives worst-path
delay as `clock_target_ns - wns_ns`. Output keys and task IDs are sorted, and no
timestamp or host path is recorded, so identical inputs produce identical
bytes.
