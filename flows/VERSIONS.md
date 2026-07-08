# SB-001 Pinned Tool Versions

This file records the toolchain pins consumed by `flows/Dockerfile`.

| Component | Pin |
|---|---|
| Base image | `debian:bookworm-slim` |
| Python | Debian bookworm `python3.11` packages |
| Verilator | Debian bookworm `verilator` package, must report 5.x |
| Icarus Verilog | source tag `v12_0` from `steveicarus/iverilog` |
| oss-cad-suite | release `2026-07-08`, asset `oss-cad-suite-linux-x64-20260708.tgz`, SHA-256 `5b24af7c0fa639a8105e4b6e128cee24dcfc1316e1bbd7b8a9d06b4dac10313e` |
| Yosys/yosys-slang/SymbiYosys/boolector/eqy | from the pinned oss-cad-suite archive |
| OpenSTA | from the pinned oss-cad-suite archive as `sta` |
| cocotb | `1.9.2` |
| pytest | `8.3.4` |
| ruff | `0.8.4` |
| pydantic | `2.10.4` |
| open_pdks | tag `1.0.604`, commit `d658698bd8bcf4e05fc7b5991a701247ba0d744c` |
| sky130hd PDK subset | copied from the pinned open_pdks sky130 install: `sky130_fd_sc_hd` `.lib` and `.lef`, excluding `*.magic.lef` |

The Docker build must fail rather than silently using an unpinned floating tool or a missing SystemVerilog frontend.
