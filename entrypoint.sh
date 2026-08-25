#!/bin/sh
set -eu

ENV_FILE="/app/runtime_env.sh"

INPUT_DIR="${INPUT_DIR:-/app/input}"
OUTPUT_DIR="${OUTPUT_DIR:-/app/output}"

mkdir -p "$INPUT_DIR" "$OUTPUT_DIR"

{
    printf '#!/bin/sh\n'
    printf 'set -u\n'
    env | sort | while IFS= read -r linha; do
        chave=${linha%%=*}
        case "$chave" in
            INPUT_DIR|OUTPUT_DIR|LLM_BASE_URL|LLM_MODEL|LLM_API_KEY|TZ)
                valor=${linha#*=}
                escapado=$(printf '%s' "$valor" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/`/\\`/g' -e 's/\$/\\\$/g')
                printf 'export %s="%s"\n' "$chave" "$escapado"
                ;;
        esac
    done
} > "$ENV_FILE"

exec "$@"
