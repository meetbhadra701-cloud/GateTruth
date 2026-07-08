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

The oss-cad-suite archive hash and sky130 standard-cell commit are pinned in lows/VERSIONS.md. SB-001 still needs Docker Desktop/WSL2 installed before acceptance commands can run.

