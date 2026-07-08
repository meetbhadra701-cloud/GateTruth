# syntax=docker/dockerfile:1.7

ARG DEBIAN_FRONTEND=noninteractive
ARG OSS_CAD_SUITE_DATE=2025-10-14
ARG OSS_CAD_SUITE_SHA256=REPLACE_WITH_UPSTREAM_SHA256_BEFORE_REVIEW
ARG IVERILOG_REF=v12_0
ARG SKY130_FD_SC_HD_COMMIT=REPLACE_WITH_PINNED_COMMIT_BEFORE_REVIEW

FROM --platform=linux/amd64 debian:bookworm-slim AS base
ARG DEBIAN_FRONTEND

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      make \
      autoconf \
      g++ \
      flex \
      bison \
      pkg-config \
      python3.11 \
      python3.11-dev \
      python3-pip \
      python3-venv \
      verilator \
      xz-utils \
    && rm -rf /var/lib/apt/lists/*

FROM base AS iverilog-build
ARG IVERILOG_REF
WORKDIR /build
RUN git clone --filter=blob:none --branch "${IVERILOG_REF}" https://github.com/steveicarus/iverilog.git \
    && cd iverilog \
    && sh autoconf.sh \
    && ./configure --prefix=/opt/iverilog \
    && make -j"$(nproc)" \
    && make install

FROM base AS oss-cad-suite
ARG OSS_CAD_SUITE_DATE
ARG OSS_CAD_SUITE_SHA256
WORKDIR /opt
RUN curl -fsSLo oss-cad-suite.tgz \
      "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/${OSS_CAD_SUITE_DATE}/oss-cad-suite-linux-x64-${OSS_CAD_SUITE_DATE}.tgz" \
    && if [[ "${OSS_CAD_SUITE_SHA256}" == REPLACE_* ]]; then \
         echo "OSS_CAD_SUITE_SHA256 must be pinned before SB-001 review" >&2; exit 64; \
       fi \
    && echo "${OSS_CAD_SUITE_SHA256}  oss-cad-suite.tgz" | sha256sum -c - \
    && tar -xzf oss-cad-suite.tgz \
    && rm oss-cad-suite.tgz

FROM base AS pdk
ARG SKY130_FD_SC_HD_COMMIT
WORKDIR /tmp
RUN if [[ "${SKY130_FD_SC_HD_COMMIT}" == REPLACE_* ]]; then \
      echo "SKY130_FD_SC_HD_COMMIT must be pinned before SB-001 review" >&2; exit 64; \
    fi \
    && git clone https://github.com/google/skywater-pdk-libs-sky130_fd_sc_hd.git sky130_fd_sc_hd \
    && cd sky130_fd_sc_hd \
    && git checkout "${SKY130_FD_SC_HD_COMMIT}" \
    && mkdir -p /pdk/sky130hd \
    && find . -path '*/cells/*' -prune -o \( -name '*.lib' -o -name '*.lef' \) -print -exec cp '{}' /pdk/sky130hd/ ';' \
    && test -n "$(find /pdk/sky130hd -name '*.lib' -print -quit)" \
    && test -n "$(find /pdk/sky130hd -name '*.lef' -print -quit)"

FROM base AS runtime
ENV PATH="/opt/oss-cad-suite/bin:/opt/iverilog/bin:${PATH}"
ENV PYTHONUNBUFFERED=1
ENV PDK_ROOT=/pdk
ENV SILICONBENCH_PLATFORM=linux/amd64

COPY --from=iverilog-build /opt/iverilog /opt/iverilog
COPY --from=oss-cad-suite /opt/oss-cad-suite /opt/oss-cad-suite
COPY --from=pdk /pdk/sky130hd /pdk/sky130hd

RUN python3.11 -m pip install --no-cache-dir --break-system-packages \
      cocotb==1.9.2 \
      pytest==8.3.4 \
      ruff==0.8.4 \
      pydantic==2.10.4

RUN set -eux; \
    test "$(uname -m)" = "x86_64"; \
    verilator --version | grep -E 'Verilator 5\.'; \
    iverilog -V; \
    yosys -V; \
    command -v sta; \
    sby --help >/dev/null; \
    eqy --help >/dev/null; \
    python3.11 -c "import cocotb, pydantic"; \
    ls /pdk/sky130hd/*.lib /pdk/sky130hd/*.lef >/dev/null

WORKDIR /work
CMD ["/bin/bash"]
