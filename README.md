# renamely

Renames PDF documents using an LLM. Each PDF's first page is rendered as an
image, sent to an OpenAI-compatible vision model (OpenRouter, Ollama, ...),
and the returned suggestion becomes the new filename (shape dictated by the
configured prompt). Files move from `/app/input` to `/app/output`, never
colliding with existing names.

Ships with domain-agnostic defaults — OpenRouter + `z-ai/glm-5.3-flash` (a
vision-capable model) and a generic "suggest a filename" prompt.
Receipt-specific rules belong in `LLM_USER_PROMPT` (see
[Custom prompts](#custom-prompts)).

Runs unattended inside a container: built on the
[cronos](https://github.com/jhunufernandes/cronos) Docker base image, cron
triggers the script on a schedule configured via `CRON_SCHEDULE` (container
timezone).

## How it works

1. Scan `/app/input` for PDF files.
2. Render page 1 of each at 150 DPI → PNG → base64.
3. Ask the LLM to suggest a filename.
4. Sanitize it for filesystem safety only (accents/quotes/backticks/path
   characters removed, whitespace collapsed) — the name's shape is whatever
   the prompt dictates. De-duplicate against existing output files and move.

Exit codes: `0` run completed · `1` fatal error (invalid configuration or
missing input folder). A failure on an individual file is logged and skipped —
the run continues with the next file.

## Configuration

Environment variables read by `main.py`:

| Variable | Default | Description |
| --- | --- | --- |
| `INPUT_DIR` | `/app/input` | Folder scanned for PDFs |
| `OUTPUT_DIR` | `/app/output` | Destination folder for renamed files |
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | OpenAI-compatible endpoint |
| `LLM_MODEL` | `z-ai/glm-5.3-flash` | Model slug — must support image input; other free options: `google/gemma-4-26b-a4b-it:free`, `minimax/minimax-m3:free` |
| `LLM_API_KEY` | *(empty)* | API key — **required for OpenRouter**; placeholder is used if empty (fine for keyless local servers) |
| `LLM_USER_PROMPT` | *generic filename prompt* | Instruction sent with every image |
| `LLM_MAX_ATTEMPTS` | `3` | Retries per document before giving up on it |
| `LLM_TIMEOUT_SECONDS` | `180` | Per-request timeout |

In Docker, `INPUT_DIR`/`OUTPUT_DIR` default to the fixed mount points
`/app/input` and `/app/output` (mount your host folders there). Outside
Docker, point them at any folders via environment variables.

> Note: cron jobs do not inherit container environment variables. At container
> start, the [cronos](https://github.com/jhunufernandes/cronos) base image
> persists every variable that is set into `/app/env.sh` (owned and readable
> only by the unprivileged user), and the scheduled command sources it before
> each run — so configure via `docker run -e` / `--env-file` and scheduled
> runs pick it up too.

For **OpenRouter**, only the API key is needed (URL and model already default
to it):

```
LLM_API_KEY=sk-or-v1-...
```

### Custom prompts

The built-in default prompt is deliberately generic. Receipt-specific rules
(special beneficiaries, date formats, etc.) belong in configuration, not in
code — override via `LLM_USER_PROMPT`:

```sh
export LLM_USER_PROMPT='Suggest a short, descriptive file name for this document, based on its most distinctive content.

Answer with ONLY the file name: no extension, no quotes, no backticks, no explanation.
'

mkdir -p input output
INPUT_DIR=./input OUTPUT_DIR=./output .venv/bin/python main.py
```

Single-quoted strings may span multiple lines in the shell — newlines are kept
as-is. For `docker run`, prefer `--env-file` (same content in a `.env` file) or
join the prompt into one line for `-e`.

## Running

### Local Docker build

```sh
mkdir -p input output
docker build -t renamely .
docker run -d \
    -v ./input:/app/input \
    -v ./output:/app/output \
    renamely
```

### Prebuilt image

CI (GitHub Actions) reuses the workflows from
[jhunufernandes/python-github-actions](https://github.com/jhunufernandes/python-github-actions):
lint (ruff + ty) and tests on pushes/PRs to `main`, and multi-arch images
(`amd64` + `arm64`) pushed to GHCR on every push to `main`:

```sh
docker pull ghcr.io/<owner>/renamely:latest
docker run -d \
    -v ./input:/app/input \
    -v ./output:/app/output \
    ghcr.io/<owner>/renamely:latest
```

Scheduling is handled by the cronos base image and configured with two
container-level variables (not read by `main.py`):

| Variable | Default | Description |
| --- | --- | --- |
| `CRON_SCHEDULE` | *(none — required)* | 5-field cron expression |
| `COMMAND` | `python /app/main.py` | Command cron runs on every tick; baked into the image, override only to change it |

Cron fires in UTC unless you pass `-e TZ=<tz>` to `docker run`.

### Without Docker

Requires Python ≥ 3.14. No cron or root user needed — any scheduler that can
run the command works (systemd timer, host crontab, etc.). Easiest option is
the bundled helper, which sources a `.env` file (create it from
[`.env.example`](.env.example); `INPUT_DIR`/`OUTPUT_DIR` default to
`./input`/`./output` when unset):

```sh
git clone <repo-url> && cd renamely

python3 -m venv .venv
.venv/bin/pip install -e .

cp .env.example .env   # fill in the values
./run_local.sh
```

All environment variables from the table above work the same way, e.g.
pointing at Ollama running locally:

```sh
INPUT_DIR=./input OUTPUT_DIR=./output LLM_BASE_URL=http://localhost:8080/v1 \
    .venv/bin/python main.py
```

To replicate the container's schedule with a host crontab (note: the
container's cron fires in UTC unless you pass `-e TZ=<tz>` to `docker run`):

```cron
0 4 1 * * cd /path/to/renamely && .venv/bin/python main.py >> renamely.log 2>&1
```

## Development

Requires Python ≥ 3.14.

```sh
python3 -m venv .venv
.venv/bin/pip install -e .[dev]   # runtime + ruff + ty

.venv/bin/ruff check .
.venv/bin/ty check main.py
.venv/bin/python -m unittest discover -v
```

Project layout: single-module package (`main.py`) defined in
[`pyproject.toml`](pyproject.toml); the Dockerfile installs dependencies
directly from it with `pip install .` on top of the
[cronos](https://github.com/jhunufernandes/cronos) base image, which provides
the cron scheduling; [`prestart.sh`](prestart.sh) prepares mounted volumes at
container start.

## License / ownership notes

- MIT licensed — see [LICENSE](LICENSE).
- Receipts are processed by whatever LLM endpoint you configure — keep data
  sensitivity in mind before pointing this at a hosted provider.
