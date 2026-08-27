# renamely

Renames PDF receipts using an LLM. Each PDF's first page is rendered as an
image, sent to an OpenAI-compatible vision model (Ollama, OpenRouter, ...),
and the returned suggestion is sanitized into a filename like
`pix_payee_name_42_50.pdf`. Files move from `/app/input` to `/app/output`,
never colliding with existing names.

Runs unattended inside a container: cron triggers the script at **04:00 on the
1st day of every month** (container timezone).

## How it works

1. Scan `/app/input` for PDF files.
2. Render page 1 of each at 150 DPI → PNG → base64.
3. Ask the LLM to suggest a filename.
4. Sanitize it (lowercase, ASCII-only, spaces → `_`, forced `pix_` prefix,
   `&` → `and`), de-duplicate against existing output files, and move it.

Exit codes: `0` all good · `2` some failures · `1` missing input folder.

## Configuration

Environment variables read by `script.py`:

| Variable | Default | Description |
| --- | --- | --- |
| `INPUT_DIR` | `/app/input` | Folder scanned for PDFs |
| `OUTPUT_DIR` | `/app/output` | Destination folder |
| `LLM_BASE_URL` | `http://host.docker.internal:11434/v1` | OpenAI-compatible endpoint |
| `LLM_MODEL` | `gemma4:12b` | Model slug |
| `LLM_API_KEY` | *(empty)* | API key; placeholder is used if empty (fine for local Ollama) |
| `LLM_USER_PROMPT` | *built-in Pix prompt* | Instruction sent with every image |

> Note: cron jobs do not inherit container environment variables, so scheduled
> runs always use these defaults baked into `script.py`. Edit them there (or
> run manually with overrides).

For **OpenRouter**, set:

```
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=<openrouter-model-slug>
LLM_API_KEY=sk-or-v1-...
```

## Running

### Docker Compose

```sh
mkdir -p input output
docker compose up -d --build
```

### Prebuilt image

CI (GitHub Actions) builds multi-arch images (`amd64` + `arm64`) and pushes to
GHCR on every push to `main`:

```sh
docker pull ghcr.io/<owner>/renamely:latest
docker run -d \
    -v ./input:/app/input \
    -v ./output:/app/output \
    ghcr.io/<owner>/renamely:latest
```

Schedule lives in [`crontab`](crontab) (`0 4 1 * *`); change it there and
rebuild. Timezone comes from the container (`TZ`, default `America/Sao_Paulo`).

## Development

Requires Python ≥ 3.14.

```sh
python3 -m venv .venv
.venv/bin/pip install -e . --group dev   # runtime + ruff + ty

.venv/bin/ruff check .
.venv/bin/ty check script.py
```

Project layout: single-module package (`script.py`) defined in
[`pyproject.toml`](pyproject.toml); the Dockerfile installs dependencies
directly from it with `pip install .`.

## License / ownership notes

- Receipts are processed by whatever LLM endpoint you configure — keep data
  sensitivity in mind before pointing this at a hosted provider.
