# SB-001 Pinned Tool Versions

This file records the toolchain pins consumed by `flows/Dockerfile`.

| Component | Pin |
|---|---|
| Base image | `debian:bookworm-slim` |
| Python | Debian bookworm `python3.11` packages |
| Verilator | Debian bookworm `verilator` package, must report 5.x |
| Icarus Verilog | source tag `v12_0` from `steveicarus/iverilog` |
| oss-cad-suite | `2025-10-14` Linux x64 archive |
| Yosys/yosys-slang/SymbiYosys/boolector/eqy | from the pinned oss-cad-suite archive |
| OpenSTA | from the pinned oss-cad-suite archive as `sta` |
| cocotb | `1.9.2` |
| pytest | `8.3.4` |
| ruff | `0.8.4` |
| pydantic | `2.10.4` |
| sky130_fd_sc_hd | pinned by `SKY130_FD_SC_HD_COMMIT` build arg |

The Docker build must fail rather than silently using an unpinned floating tool or a missing SystemVerilog frontend.
