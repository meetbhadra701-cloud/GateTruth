# syntax=docker/dockerfile:1.7

# Official OpenROAD-flow-scripts ORFS image, pinned to the linux/amd64
# platform manifest resolved from docker.io/openroad/orfs:latest on 2026-07-08.
FROM --platform=linux/amd64 openroad/orfs@sha256:25cba7b97fd4fec67481564e37096825010b499d7afca791ced28130cf03b252

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV GATETRUTH_PLATFORM=linux/amd64
ENV SILICONBENCH_PLATFORM=linux/amd64
ENV ORFS_ROOT=/OpenROAD-flow-scripts

RUN set -eux; \
    test "$(uname -m)" = "x86_64"; \
    test -f "${ORFS_ROOT}/env.sh"; \
    test -f "${ORFS_ROOT}/flow/Makefile"; \
    test -f "${ORFS_ROOT}/flow/designs/sky130hd/gcd/config.mk"; \
    source "${ORFS_ROOT}/env.sh"; \
    openroad -version; \
    yosys -V

WORKDIR /OpenROAD-flow-scripts/flow
CMD ["/bin/bash"]
