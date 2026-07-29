#!/usr/bin/env bash
set -euo pipefail

image="${1:-gatetruth:v1}"
docker image inspect "$image" --format '{{.Id}}'
