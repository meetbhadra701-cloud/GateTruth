## What this changes

Briefly describe the change and link any related issue.

## Type

- [ ] Bug fix
- [ ] New task
- [ ] Harness / flow / site improvement
- [ ] Documentation

## Evidence

Paste the raw output of the checks you ran inside the pinned image:

```
# pytest -q && ruff check harness/
...
```

For a **new task**, also include:

- [ ] Original-prose spec with a fresh canary GUID
- [ ] ≥8 enumerated edge cases in the hidden tests
- [ ] Mutation kill rate ≥95% (paste the number)
- [ ] Reference clears the full pipeline (attach the signed manifest)

## Checklist

- [ ] I ran the tests and linter inside `siliconbench:v1`
- [ ] I did not modify unrelated tasks or results
- [ ] I agree to license my contribution under Apache 2.0
