# SiliconBench Flows

`flows/Dockerfile` defines the primary linux/amd64 image for SB-001.

Build once Docker Desktop/WSL2 is installed:

```bash
docker build --platform linux/amd64 -t siliconbench:v1 -f flows/Dockerfile flows/
```

Record the local image digest:

```bash
flows/record_digest.sh siliconbench:v1
```

The current Dockerfile intentionally fails if the oss-cad-suite archive hash or sky130 standard-cell commit are left as placeholders. Replace those pins from upstream release evidence before moving SB-001 to review.
