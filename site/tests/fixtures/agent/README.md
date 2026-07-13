# Track B smoke fixture provenance

SB-077 wrote its one real Haiku smoke manifest to container-local `/tmp/real.json`, so the raw file
did not survive container teardown. This fixture preserves the recorded real provider/model outcome
and usage (`1000` input tokens, `230` output tokens, `$0.00215`, token-budget termination), while its
evaluator fields were regenerated without network access from the unchanged `toy_taskB` baseline.
The combined fixture was canonical-signature-recomputed and is schema-validated by every site test.
