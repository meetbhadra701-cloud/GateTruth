---
name: Bug report
about: Report a problem in the harness, flow, or a task
title: "[bug] "
labels: bug
---

**What happened**
A clear description of the bug.

**Where**
Harness / flow / a specific task (`task id`) / site / other.

**To reproduce**
The exact command(s) you ran, ideally the containerized form:

```bash
docker run --rm --network none --cap-drop=ALL \
  --security-opt no-new-privileges --memory=4g --pids-limit=512 --cpus=2 \
  --mount "type=bind,src=$PWD/build/secure-src,dst=/work,readonly" \
  --mount "type=bind,src=$PWD/build/secure-output,dst=/output" \
  --workdir /work siliconbench:v1 ...
```

**Expected vs. actual**
What you expected, and what happened instead. Paste raw output (lint, simulation,
or pipeline logs) rather than a summary.

**Environment**
- Image digest (`docker inspect --format '{{.Id}}' siliconbench:v1`):
- Host OS / architecture:
