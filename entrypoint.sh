#!/bin/sh
set -eu

# Best-effort prep so the unprivileged cron job can write to mounted volumes;
# ownership may differ on restrictive hosts, hence the fallback.
mkdir -p /app/input /app/output
chown renamely:renamely /app/input /app/output 2>/dev/null || true

# Cron jobs do not inherit container environment variables, so persist every
# configuration variable that is set into a file the scheduled command sources
# before each run. Python + shlex.quote keep multi-line values (e.g.
# LLM_USER_PROMPT) safely shell-quoted.
/usr/local/bin/python - > /app/env.sh <<'PYEOF'
import os
import shlex

VARS = (
    "INPUT_DIR",
    "OUTPUT_DIR",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_USER_PROMPT",
)
for name in VARS:
    if name in os.environ:
        print(f"export {name}={shlex.quote(os.environ[name])}")
PYEOF
chown renamely:renamely /app/env.sh 2>/dev/null || true
chmod 0600 /app/env.sh

exec "$@"
