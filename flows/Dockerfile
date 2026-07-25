# syntax=docker/dockerfile:1.7

ARG DEBIAN_FRONTEND=noninteractive
ARG DEBIAN_SNAPSHOT=20260708T000000Z
ARG OSS_CAD_SUITE_TAG=2026-07-08
ARG OSS_CAD_SUITE_ASSET_DATE=20260708
ARG OSS_CAD_SUITE_SHA256=5b24af7c0fa639a8105e4b6e128cee24dcfc1316e1bbd7b8a9d06b4dac10313e
ARG IVERILOG_REF=v12_0
ARG VOLARE_SKY130_TAG=sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392
ARG VOLARE_SKY130_HD_SHA256=d4081b3c0fbfa2afe31dba789c03157ad137ea08b11910e2c8b3ec81b2a61bf6

FROM --platform=linux/amd64 debian:bookworm-slim@sha256:60eac759739651111db372c07be67863818726f754804b8707c90979bda511df AS base
ARG DEBIAN_FRONTEND
ARG DEBIAN_SNAPSHOT

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT} bookworm-updates main" \
      "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT} bookworm-security main" \
      > /etc/apt/sources.list \
    && apt-get -o Acquire::Check-Valid-Until=false update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      make \
      autoconf \
      automake \
      g++ \
      flex \
      gperf \
      bison \
      pkg-config \
      python3.11=3.11.2-6+deb12u7 \
      python3.11-dev=3.11.2-6+deb12u7 \
      python3-pip=23.0.1+dfsg-1 \
      python3-venv=3.11.2-1+b1 \
      tcl-dev \
      tk-dev \
      verilator=5.006-3 \
      opensta=0~20191111gitc018cb2+dfsg-1 \
      xz-utils \
      zstd \
    && rm -rf /var/lib/apt/lists/*

FROM base AS iverilog-build
ARG IVERILOG_REF
WORKDIR /build
RUN git clone --filter=blob:none --branch "${IVERILOG_REF}" https://github.com/steveicarus/iverilog.git \
    && cd iverilog \
    && test "$(git rev-parse HEAD)" = "4fd5291632232fbe1ba49b2c26bb6b2bf1c6c9cf" \
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

FROM base AS pdk-subset
ARG VOLARE_SKY130_TAG
ARG VOLARE_SKY130_HD_SHA256
WORKDIR /tmp/pdk
RUN curl -fsSLo sky130_fd_sc_hd.tar.zst \
      "https://github.com/chipfoundry/volare/releases/download/${VOLARE_SKY130_TAG}/sky130_fd_sc_hd.tar.zst" \
    && echo "${VOLARE_SKY130_HD_SHA256}  sky130_fd_sc_hd.tar.zst" | sha256sum -c - \
    && tar --zstd -xf sky130_fd_sc_hd.tar.zst \
    && mkdir -p /pdk/sky130hd \
    && cp sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib /pdk/sky130hd/ \
    && cp sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef /pdk/sky130hd/ \
    && cp sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_ef_sc_hd.lef /pdk/sky130hd/ \
    && test -n "$(find /pdk/sky130hd -name '*.lib' -print -quit)" \
    && test -n "$(find /pdk/sky130hd -name '*.lef' -print -quit)"

FROM base AS runtime
ARG SILICONBENCH_IMAGE_DIGEST=sha256:20a665db641ebf3c4dc260a30c22817611081b48a749842d38cdc38b10ad8f62
ENV PATH="/work:/opt/iverilog/bin:/opt/oss-cad-suite/bin:${PATH}"
ENV PYTHONUNBUFFERED=1
ENV PDK_ROOT=/pdk
ENV SILICONBENCH_PLATFORM=linux/amd64

COPY --from=iverilog-build /opt/iverilog /opt/iverilog
COPY --from=oss-cad-suite /opt/oss-cad-suite /opt/oss-cad-suite
COPY --from=pdk-subset /pdk/sky130hd /pdk/sky130hd

RUN printf '%s\n' "$SILICONBENCH_IMAGE_DIGEST" > /etc/siliconbench-image-digest

RUN ln -sf /usr/bin/python3.11 /usr/local/bin/python \
    && ln -sf /usr/bin/python3.11 /usr/local/bin/python3 \
    && python --version \
    && python3 --version

RUN python3.11 -m pip install --no-cache-dir --break-system-packages \
      cocotb==1.9.2 \
      pytest==8.3.4 \
      ruff==0.8.4 \
      pydantic==2.10.4

RUN set -eux; \
    test "$(uname -m)" = "x86_64"; \
    verilator --version | grep -E 'Verilator 5\.'; \
    test "$(command -v python)" = "/usr/local/bin/python"; \
    test "$(command -v python3)" = "/usr/local/bin/python3"; \
    python --version | grep -E 'Python 3\.11\.'; \
    python3 --version | grep -E 'Python 3\.11\.'; \
    test "$(command -v iverilog)" = "/opt/iverilog/bin/iverilog"; \
    iverilog -V; \
    yosys -V; \
    sta -version; \
    sby --help >/dev/null; \
    eqy --help >/dev/null; \
    python3.11 -c "import cocotb, pydantic"; \
    ls /pdk/sky130hd/*.lib /pdk/sky130hd/*.lef >/dev/null

WORKDIR /work
CMD ["/bin/bash"]
