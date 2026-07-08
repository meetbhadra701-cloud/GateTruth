#!/usr/bin/env bash
set -euo pipefail

image="${1:-siliconbench:v1}"
docker image inspect "$image" --format '{{.Id}}'
