#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates docker.io docker-compose-v2
if command -v systemctl >/dev/null && systemctl is-system-running >/dev/null 2>&1; then
  systemctl enable --now docker
else
  service docker start
fi
docker info --format '{{.ServerVersion}}'
docker compose version
