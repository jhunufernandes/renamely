#!/bin/bash
set -euo pipefail

# Run script.py locally (no Docker, no cron) using the same configuration
# the container would receive as environment variables.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ENV_FILE="${1:-$SCRIPT_DIR/.env}"
if [ ! -f "$ENV_FILE" ]; then
    echo "Missing $ENV_FILE. Create it from .env.example first." >&2
    exit 1
fi
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

# Prefer the project virtualenv if it exists, otherwise fall back to PATH.
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
else
    PYTHON="python3"
fi

cd "$SCRIPT_DIR"

mkdir -p "${INPUT_DIR:-./input}" "${OUTPUT_DIR:-./output}"

exec "$PYTHON" script.py
