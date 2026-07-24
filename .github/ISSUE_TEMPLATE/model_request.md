---
name: Model request
about: Request a model be added to the leaderboard
title: "[model] "
labels: model-request
---

**Model**
Provider and model id (e.g. `anthropic / claude-opus-4-8`).

**Access**
How the model is reached (official API, OpenRouter, local weights).

**Why**
What the model adds to the leaderboard's coverage.

Note: models are added as a documented, balanced set expansion under the identical
official protocol — not selectively. New models are evaluated on the frozen task
suite; they do not change existing models' results.
