#!/bin/bash
set -euo pipefail

# Run main.py locally (no Docker, no cron) using the same configuration
# the container would receive as environment variables.

MAIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ENV_FILE="${1:-$MAIN_DIR/.env}"
if [ ! -f "$ENV_FILE" ]; then
    echo "Missing $ENV_FILE. Create it from .env.example first." >&2
    exit 1
fi
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

# Prefer the project virtualenv if it exists, otherwise fall back to PATH.
if [ -x "$MAIN_DIR/.venv/bin/python" ]; then
    PYTHON="$MAIN_DIR/.venv/bin/python"
else
    PYTHON="python3"
fi

cd "$MAIN_DIR"

mkdir -p "${INPUT_DIR:-./input}" "${OUTPUT_DIR:-./output}"

exec "$PYTHON" main.py
