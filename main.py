import base64
import os
import pathlib
import re
import shutil
import sys
import time
import unicodedata

import forager
import openai
import pymupdf

# Prompt sent to the LLM on every request when LLM_USER_PROMPT is not set.
DEFAULT_USER_PROMPT = (
    "Suggest a short, descriptive file name for this document, based on "
    "its most distinctive content.\n"
    "Answer with ONLY the file name: no extension, no quotes, no "
    "backticks, no explanation."
)

# LLM defaults. forager's built-in defaults target a local Ollama text model;
# renamely ships vision-capable OpenRouter defaults instead, so LLM_API_KEY is
# the only required variable.
DEFAULT_LLM_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_LLM_MODEL = "z-ai/glm-5.3-flash"

# System prompt framing the model's answers.
SYSTEM_PROMPT = "You read document images and reply with exactly one file name and nothing else."

# LLM retry behavior: linear backoff between attempts.
LLM_BACKOFF_SECONDS = 3

# PDF page rendering.
RENDER_DPI = 150

# Filename sanitization. Unicode word characters (including accented letters)
# are preserved; everything else commonly unsafe in file names is removed.
_FILENAME_UNSAFE = re.compile(r"[^\w .\-]", re.UNICODE)


def _print(message: str) -> None:
    print(message, flush=True)


def render_first_page_as_base64(pdf_path: pathlib.Path) -> str:
    with pymupdf.open(pdf_path) as document:
        page = document.load_page(0)
        pixmap = page.get_pixmap(dpi=RENDER_DPI)
        png_bytes = pixmap.tobytes("png")
    return base64.b64encode(png_bytes).decode("utf-8")


def request_name_from_llm(
    client: openai.OpenAI,
    model: str,
    base64_image: str,
    user_prompt: str,
    max_attempts: int,
) -> str | None:
    last_exception: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{base64_image}"},
                            },
                        ],
                    },
                ],
            )
            return response.choices[0].message.content
        except Exception as exception:
            last_exception = exception
            _print(f"Attempt {attempt}/{max_attempts} failed: {exception}")
            if attempt < max_attempts:
                time.sleep(LLM_BACKOFF_SECONDS * attempt)
    raise RuntimeError(f"Failed to query the LLM after {max_attempts} attempts: {last_exception}")


def sanitize_name(raw_name: str) -> str:
    name = raw_name.strip().strip("\"'")
    name = name.replace("`", "")
    name = unicodedata.normalize("NFKC", name)
    name = _FILENAME_UNSAFE.sub("", name)
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip(" -_")
    if name.lower().endswith(".pdf"):
        name = name[:-4].rstrip(" -_")
    return name


def resolve_destination_path(output_folder: pathlib.Path, base_name: str) -> pathlib.Path:
    candidate = output_folder / f"{base_name}.pdf"
    suffix = 1
    while candidate.exists():
        candidate = output_folder / f"{base_name}_{suffix}.pdf"
        suffix += 1
    return candidate


def build_pipeline(llm_settings: forager.LlmSettings, user_prompt: str) -> forager.Forager:
    client = openai.OpenAI(
        base_url=str(llm_settings.base_url),
        api_key=llm_settings.api_key or "not-needed",
        timeout=llm_settings.timeout_seconds,
    )

    def file_filter(source: pathlib.Path) -> bool:
        return source.is_file() and source.suffix.lower() == ".pdf"

    def ask(source: pathlib.Path) -> str | None:
        _print(f"Processing current file: {source.name}")
        base64_image = render_first_page_as_base64(source)
        return request_name_from_llm(client, llm_settings.model, base64_image, user_prompt, llm_settings.max_attempts)

    def result_filter(response: str | None) -> bool:
        return bool(response and sanitize_name(response))

    def action(source: pathlib.Path, response: str | None, output_dir: pathlib.Path) -> pathlib.Path:
        new_name = sanitize_name(response or "") or sanitize_name(source.stem) or "document"
        destination_path = resolve_destination_path(output_dir, new_name)
        shutil.move(str(source), str(destination_path))
        _print(f"Success: '{source.name}' renamed to '{destination_path.name}' and moved to '{destination_path}'")
        return destination_path

    return forager.Forager(file_filter=file_filter, llm=ask, result_filter=result_filter, action=action)


def main() -> int:
    llm_settings = forager.load_llm(
        base_url=os.environ.get("LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        model=os.environ.get("LLM_MODEL", DEFAULT_LLM_MODEL),
    )
    forager_settings = forager.load_forager()
    user_prompt = llm_settings.user_prompt if os.environ.get("LLM_USER_PROMPT") else DEFAULT_USER_PROMPT

    _print(f"INPUT_DIR={forager_settings.input_dir} | OUTPUT_DIR={forager_settings.output_dir}")
    _print(f"LLM_BASE_URL={llm_settings.base_url} | LLM_MODEL={llm_settings.model}")

    pipeline = build_pipeline(llm_settings, user_prompt)
    pipeline.run(
        pathlib.Path(forager_settings.input_dir),
        pathlib.Path(forager_settings.output_dir),
    )

    _print("Processing complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
