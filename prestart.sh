#!/bin/sh
set -eu

# Best-effort prep so the unprivileged cron job can write to mounted volumes;
# ownership may differ on restrictive hosts, hence the fallback.
# Runs as root at container start via the cronos base image's prestart hook.
mkdir -p /app/input /app/output
chown app:app /app/input /app/output 2>/dev/null || true
