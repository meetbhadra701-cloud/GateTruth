#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
log_root="${repo_root}/results/logs/orfs"
run_id="gcd-sky130hd-$(date -u +%Y%m%dT%H%M%SZ)"
out_dir="${log_root}/${run_id}"
mkdir -p "${out_dir}"

if command -v cygpath >/dev/null 2>&1; then
  docker_out_dir="$(cygpath -w "${out_dir}")"
else
  docker_out_dir="${out_dir}"
fi

image="${SILICONBENCH_ORFS_IMAGE:-siliconbench-orfs:v1}"

echo "SB-009 ORFS native amd64 go/no-go"
echo "image=${image}"
echo "out_dir=${out_dir}"

set +e
env MSYS_NO_PATHCONV=1 docker run --rm \
  --platform linux/amd64 \
  -v "${docker_out_dir}:/siliconbench-orfs-output" \
  "${image}" \
  bash -lc '
    set -euo pipefail
    source /OpenROAD-flow-scripts/env.sh
    cd /OpenROAD-flow-scripts/flow
    echo "uname=$(uname -m)"
    echo "openroad=$(openroad -version)"
    echo "yosys=$(yosys -V)"
    make clean_all DESIGN_CONFIG=./designs/sky130hd/gcd/config.mk || true
    set +e
    make DESIGN_CONFIG=./designs/sky130hd/gcd/config.mk
    status=$?
    set -e
    mkdir -p /siliconbench-orfs-output
    for kind in logs reports results; do
      src="${kind}/sky130hd/gcd/base"
      if [ -e "${src}" ]; then
        cp -r "${src}" "/siliconbench-orfs-output/${kind}-gcd-base"
      fi
    done
    if [ "${status}" -eq 0 ]; then
      test -f results/sky130hd/gcd/base/6_final.gds -o -f results/sky130hd/gcd/base/6_1_merged.gds
    fi
    exit "${status}"
  '
status=$?

if [ "${status}" -eq 0 ]; then
  echo "ORFS_GCD_SKY130HD_PASS out_dir=${out_dir}"
else
  echo "ORFS_GCD_SKY130HD_FAIL exit=${status} out_dir=${out_dir}"
fi
exit "${status}"