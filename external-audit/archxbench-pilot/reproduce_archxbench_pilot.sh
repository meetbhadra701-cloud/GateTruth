#!/usr/bin/env bash
# One-command, fail-closed reproduction of the GateTruth x ArchXBench pilot.
#
#   ./reproduce_archxbench_pilot.sh [--out DIR] [--vendor-dir DIR] [--skip-image-build]
#
# Needs: bash, git, docker (linux/amd64 capable), network for the first clone / image build.
# Never writes to the vendor checkout or the GateTruth repository: both are mounted
# read-only into a container started with --network none.
set -euo pipefail

PINNED_ARCHXBENCH_SHA="0db0d0de25aad5238393d51bd97ce952e579fa1a"
IMAGE="gatetruth:v1"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
OUT="" ; VENDOR="" ; BUILD_IMAGE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2;;
    --vendor-dir) VENDOR="$2"; shift 2;;
    --skip-image-build) BUILD_IMAGE=0; shift;;
    *) echo "unknown argument: $1" >&2; exit 64;;
  esac
done
die() { echo "REPRODUCTION_BLOCKED: $*" >&2; exit 2; }
fail() { echo "PILOT_NOT_REPRODUCED: $*" >&2; exit 1; }

command -v git >/dev/null    || die "git not found"
command -v docker >/dev/null || die "docker not found"
docker info >/dev/null 2>&1  || die "docker daemon not reachable"
[ -f "$REPO/flows/Dockerfile" ] || die "not inside a GateTruth checkout: $REPO"

# Native Windows Docker needs Windows-style paths for bind mounts (Git Bash); the
# MSYS_NO_PATHCONV prefix is applied to docker run only, never exported (it breaks git).
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

OUT="${OUT:-$REPO/build/archxbench-pilot-out}"
if [ -e "$OUT" ] && [ -n "$(ls -A "$OUT" 2>/dev/null)" ]; then die "output dir exists and is not empty: $OUT"; fi
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"

VENDOR="${VENDOR:-$REPO/build/vendor/ArchXBench}"
if [ ! -d "$VENDOR/.git" ]; then
  mkdir -p "$(dirname "$VENDOR")"
  # core.autocrlf=false: a CRLF-converted testbench would silently change the benchmark.
  git -c core.autocrlf=false clone -q https://github.com/sureshpurini/ArchXBench.git "$VENDOR"
  git -C "$VENDOR" checkout -q --detach "$PINNED_ARCHXBENCH_SHA"
fi
[ "$(git -C "$VENDOR" rev-parse HEAD)" = "$PINNED_ARCHXBENCH_SHA" ] || die "vendor checkout is not at the pinned commit"
[ -z "$(git -C "$VENDOR" status --porcelain)" ] || die "vendor checkout is dirty"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  [ "$BUILD_IMAGE" = 1 ] || die "image $IMAGE missing and --skip-image-build given"
  docker build --platform linux/amd64 -t "$IMAGE" -f "$REPO/flows/Dockerfile" "$REPO/flows"
fi
IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE")"
GT_COMMIT="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo unknown)"
GT_DIRTY="$(git -C "$REPO" status --porcelain 2>/dev/null | { grep -v '^?? build/' || true; } | wc -l | tr -d ' ')"
echo "image: $IMAGE_ID"

USER_ARGS=()
if [ "$(uname -s)" = "Linux" ]; then USER_ARGS=(--user "$(id -u):$(id -g)"); chmod 0777 "$OUT"; fi
RUN=(env MSYS_NO_PATHCONV=1 docker run --rm --platform linux/amd64 --network none "${USER_ARGS[@]}"
     --mount "type=bind,src=$(native "$REPO"),dst=/work,readonly"
     --mount "type=bind,src=$(native "$VENDOR"),dst=/vendor/ArchXBench,readonly"
     --mount "type=bind,src=$(native "$OUT"),dst=/out"
     -e GATETRUTH_DOCKER_DIGEST="$IMAGE_ID" -e GT_COMMIT="$GT_COMMIT" -e GT_DIRTY_FILES="$GT_DIRTY" -e PYTHONDONTWRITEBYTECODE=1 --workdir /work "$IMAGE")

echo "== 1/3 unit + regression tests (external-audit) =="
"${RUN[@]}" python -I -m pytest -p no:cacheprovider -q external-audit/tests 2>&1 | tee "$OUT/pytest.log" \
  || fail "tests failed (see $OUT/pytest.log)"
grep -Eq "[0-9]+ passed" "$OUT/pytest.log" || fail "no passing-test summary found"
! grep -Eq "[0-9]+ (failed|error)" "$OUT/pytest.log" || fail "pytest reported failures"

echo "== 2/3 experiment (each task twice, determinism + committed-result comparison) =="
"${RUN[@]}" python -I external-audit/archxbench-pilot/run_pilot.py \
  --vendor-root /vendor/ArchXBench --out /out \
  --committed-results /work/external-audit/archxbench-pilot/results 2>&1 | tee "$OUT/run_pilot.log" \
  || fail "experiment verdict negative (see $OUT/results/verdict.json)"

echo "== 3/3 manifest =="
"${RUN[@]}" python -I external-audit/archxbench-pilot/make_manifest.py --out /out/REPRODUCIBILITY_MANIFEST.json \
  --vendor-root /vendor/ArchXBench --image-id "$IMAGE_ID" --host "$(uname -s)-$(uname -m)" \
  || fail "manifest generation failed"

grep -q '"verdict": "PILOT_REPRODUCED"' "$OUT/results/verdict.json" || fail "verdict file does not say PILOT_REPRODUCED"
echo "PILOT_REPRODUCED  (outputs: $OUT)"
