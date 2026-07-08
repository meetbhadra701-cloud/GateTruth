# ORFS Native amd64 Go/No-Go

Status: FAIL
Date: 2026-07-08
Ticket: SB-009

## Inputs

- Host: Windows Docker Desktop/WSL2 on x86-64 hardware.
- ORFS image: `siliconbench-orfs:v1`.
- Base image: official `openroad/orfs`, linux/amd64 manifest digest `sha256:25cba7b97fd4fec67481564e37096825010b499d7afca791ced28130cf03b252`.
- Smoke design: ORFS built-in `flow/designs/sky130hd/gcd/config.mk`.
- Hard timeout: 7200 seconds.

## Command

```bash
docker build --platform linux/amd64 -t siliconbench-orfs:v1 -f flows/orfs/Dockerfile flows/orfs/
timeout 7200 flows/orfs/run_gcd_sky130hd.sh
echo "EXIT:$?"
```

## Result

FAIL. The image built and the native amd64 gcd/sky130hd run started on `x86_64`, but ORFS exited before route during CTS with exit code 2.

Raw logs:

- `results/logs/sb009-orfs-run.log`
- `results/logs/sb009-orfs-run.err.log`

Key output:

```text
uname=x86_64
openroad=26Q3-79-gf4e5e40f47
Yosys 0.64+post
Error: cts.tcl, 83 child killed: illegal instruction
EXIT:2
```

The 7200-second timeout was not reached. Per SB-009, this is recorded as the ORFS go/no-go FAIL path; ADR-0006 carries the decision.