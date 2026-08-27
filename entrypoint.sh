#!/bin/sh
set -eu

# Best-effort prep so the unprivileged cron job can write to mounted volumes;
# ownership may differ on restrictive hosts, hence the fallback.
mkdir -p /app/input /app/output
chown renamely:renamely /app/input /app/output 2>/dev/null || true

exec "$@"
