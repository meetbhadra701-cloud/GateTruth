# SB-001 Pinned Tool Versions

This file records the toolchain pins consumed by `flows/Dockerfile`.

| Component | Pin |
|---|---|
| Base image | `debian:bookworm-slim` |
| Python | Debian bookworm `python3.11` packages; runtime aliases `/usr/local/bin/python` and `/usr/local/bin/python3` point to `/usr/bin/python3.11` |
| Verilator | Debian bookworm `verilator` package, must report 5.x |
| Icarus Verilog | source tag `v12_0` from `steveicarus/iverilog`; build dependency `gperf` |
| oss-cad-suite | release `2026-07-08`, asset `oss-cad-suite-linux-x64-20260708.tgz`, SHA-256 `5b24af7c0fa639a8105e4b6e128cee24dcfc1316e1bbd7b8a9d06b4dac10313e` |
| Yosys/yosys-slang/SymbiYosys/boolector/eqy | from the pinned oss-cad-suite archive |
| OpenSTA | Debian bookworm `opensta` package, must provide `/usr/bin/sta` |
| cocotb | `1.9.2` |
| pytest | `8.3.4` |
| ruff | `0.8.4` |
| pydantic | `2.10.4` |
| Volare sky130 prebuilt PDK | release `sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392`, asset `sky130_fd_sc_hd.tar.zst`, SHA-256 `d4081b3c0fbfa2afe31dba789c03157ad137ea08b11910e2c8b3ec81b2a61bf6` |
| sky130hd PDK subset | copied from pinned Volare sky130A `sky130_fd_sc_hd`: TT liberty plus standard and ef LEFs |

The Docker build must fail rather than silently using an unpinned floating tool or a missing SystemVerilog frontend.

## Image Digests

- SB-001 accepted image digest: sha256:ecf156c0f2197dd6602499255e19cea1bfc04a429f3aa5ae9c786cf5c179c74e.
- SB-011 image digest: sha256:76d68432cff5c4b43fc0573868df1e0d0ccb0df3903fc86758f7d66d264fd9be. Supersedes SB-001 for subsequent M1 tickets by adding the unversioned python alias only.
