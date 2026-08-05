# ORFS Native amd64 Go/No-Go

Status: FAIL
Date: 2026-07-08
Ticket: SB-009

## Inputs

- Host: Windows Docker Desktop/WSL2 on x86-64 hardware.
- ORFS image: `gatetruth-orfs:v1`.
- Base image: official `openroad/orfs`, linux/amd64 manifest digest `sha256:25cba7b97fd4fec67481564e37096825010b499d7afca791ced28130cf03b252`.
- Smoke design: ORFS built-in `flow/designs/sky130hd/gcd/config.mk`.
- Hard timeout: 7200 seconds.

## Command

```bash
docker build --platform linux/amd64 -t gatetruth-orfs:v1 -f flows/orfs/Dockerfile flows/orfs/
timeout 7200 flows/orfs/run_gcd_sky130hd.sh
echo "EXIT:$?"
```

## Result

FAIL. The image built and the native amd64 gcd/sky130hd run started on `x86_64`, but ORFS exited before route during CTS with exit code 2.

Key output:

```text
uname=x86_64
openroad=26Q3-79-gf4e5e40f47
Yosys 0.64+post
Error: cts.tcl, 83 child killed: illegal instruction
EXIT:2
```

The 7200-second timeout was not reached. This is recorded as the ORFS go/no-go
FAIL path (internal ticket SB-009) that led to the project's current flow
choice (Yosys + OpenSTA, not ORFS) for the pinned pipeline `flows/Dockerfile`
actually uses. The raw run logs and the full architectural decision record are
maintainer-local project-management artifacts, not part of this repository,
the same way `results/refs/` and other local-scratch inputs described
elsewhere in this project are not committed — this file preserves the
technical finding itself.
