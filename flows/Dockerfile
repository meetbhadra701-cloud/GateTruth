# syntax=docker/dockerfile:1.7

ARG DEBIAN_FRONTEND=noninteractive
ARG OSS_CAD_SUITE_TAG=2026-07-08
ARG OSS_CAD_SUITE_ASSET_DATE=20260708
ARG OSS_CAD_SUITE_SHA256=5b24af7c0fa639a8105e4b6e128cee24dcfc1316e1bbd7b8a9d06b4dac10313e
ARG IVERILOG_REF=v12_0
ARG OPEN_PDKS_REF=1.0.604
ARG OPEN_PDKS_COMMIT=d658698bd8bcf4e05fc7b5991a701247ba0d744c

FROM --platform=linux/amd64 debian:bookworm-slim AS base
ARG DEBIAN_FRONTEND

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      magic \
      make \
      autoconf \
      automake \
      g++ \
      flex \
      gperf \
      bison \
      pkg-config \
      python3.11 \
      python3.11-dev \
      python3-pip \
      python3-venv \
      tcl-dev \
      tk-dev \
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
ARG OSS_CAD_SUITE_TAG
ARG OSS_CAD_SUITE_ASSET_DATE
ARG OSS_CAD_SUITE_SHA256
WORKDIR /opt
RUN curl -fsSLo oss-cad-suite.tgz \
      "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/${OSS_CAD_SUITE_TAG}/oss-cad-suite-linux-x64-${OSS_CAD_SUITE_ASSET_DATE}.tgz" \
    && echo "${OSS_CAD_SUITE_SHA256}  oss-cad-suite.tgz" | sha256sum -c - \
    && tar -xzf oss-cad-suite.tgz \
    && rm oss-cad-suite.tgz

FROM base AS open-pdks-build
ARG OPEN_PDKS_REF
ARG OPEN_PDKS_COMMIT
WORKDIR /build
RUN git clone --filter=blob:none --branch "${OPEN_PDKS_REF}" https://github.com/fossi-foundation/open-pdks.git \
    && cd open-pdks \
    && test "$(git rev-parse HEAD)" = "${OPEN_PDKS_COMMIT}" \
    && ./configure --prefix=/opt/open_pdks --enable-sky130-pdk \
    && make -j"$(nproc)" \
    && make install \
    && mkdir -p /pdk/sky130hd \
    && find /opt/open_pdks/share/pdk -path '*sky130_fd_sc_hd*' \( -name '*.lib' -o -name '*.lef' \) -print -exec cp '{}' /pdk/sky130hd/ ';' \
    && find /pdk/sky130hd -name '*.magic.lef' -delete \
    && test -n "$(find /pdk/sky130hd -name '*.lib' -print -quit)" \
    && test -n "$(find /pdk/sky130hd -name '*.lef' -print -quit)"

FROM base AS runtime
ENV PATH="/opt/oss-cad-suite/bin:/opt/iverilog/bin:${PATH}"
ENV PYTHONUNBUFFERED=1
ENV PDK_ROOT=/pdk
ENV SILICONBENCH_PLATFORM=linux/amd64

COPY --from=iverilog-build /opt/iverilog /opt/iverilog
COPY --from=oss-cad-suite /opt/oss-cad-suite /opt/oss-cad-suite
COPY --from=open-pdks-build /pdk/sky130hd /pdk/sky130hd

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




