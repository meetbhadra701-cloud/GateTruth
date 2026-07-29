# GateTruth Flows

`flows/Dockerfile` defines the primary linux/amd64 image for SB-001.

Build once Docker Desktop/WSL2 is installed:

```bash
docker build --platform linux/amd64 -t gatetruth:v1 -f flows/Dockerfile flows/
```

Record the local image digest:

```bash
flows/record_digest.sh gatetruth:v1
```

The oss-cad-suite archive hash and sky130 standard-cell commit are pinned in flows/VERSIONS.md. Docker Desktop/WSL2 must be installed before the acceptance commands can run.
