import base64
import os
import pathlib
import re
import shutil
import sys
import time
import unicodedata
from dataclasses import dataclass

import pymupdf
from openai import OpenAI

# Prompts sent to the LLM on every request.
SYSTEM_PROMPT = (
    "You read document images and reply with exactly one file name "
    "and nothing else."
)

DEFAULT_USER_PROMPT = (
    "Suggest a short, descriptive file name for this document, based on "
    "its most distinctive content.\n"
    "Answer with ONLY the file name: no extension, no quotes, no "
    "backticks, no explanation."
)

# Configuration defaults, overridable via environment variables
# (LLM_BASE_URL, LLM_MODEL, LLM_API_KEY, LLM_USER_PROMPT, INPUT_DIR,
# OUTPUT_DIR).
DEFAULT_LLM_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_LLM_MODEL = "z-ai/glm-5.3-flash"
DEFAULT_LLM_API_KEY = ""
DEFAULT_INPUT_DIR = "/app/input"
DEFAULT_OUTPUT_DIR = "/app/output"

# LLM request behavior.
MAX_LLM_ATTEMPTS = 3
LLM_TIMEOUT_SECONDS = 180.0

# PDF page rendering.
RENDER_DPI = 150

# Filename sanitization.
_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9 ._\-]")


@dataclass(frozen=True)
class Configuration:
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    user_prompt: str
    input_dir: pathlib.Path
    output_dir: pathlib.Path


def load_configuration() -> Configuration:
    return Configuration(
        llm_base_url=os.environ.get("LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        llm_model=os.environ.get("LLM_MODEL", DEFAULT_LLM_MODEL),
        llm_api_key=os.environ.get("LLM_API_KEY", DEFAULT_LLM_API_KEY),
        user_prompt=os.environ.get("LLM_USER_PROMPT", DEFAULT_USER_PROMPT),
        input_dir=pathlib.Path(os.environ.get("INPUT_DIR", DEFAULT_INPUT_DIR)),
        output_dir=pathlib.Path(os.environ.get("OUTPUT_DIR", DEFAULT_OUTPUT_DIR)),
    )


def list_pdf_files(folder: pathlib.Path) -> list[pathlib.Path]:
    return sorted(
        (
            file
            for file in folder.iterdir()
            if file.is_file() and file.suffix.lower() == ".pdf"
        ),
        key=lambda file: file.name,
    )


def render_first_page_as_base64(pdf_path: pathlib.Path) -> str:
    with pymupdf.open(pdf_path) as document:
        page = document.load_page(0)
        pixmap = page.get_pixmap(dpi=RENDER_DPI)
        png_bytes = pixmap.tobytes("png")
    return base64.b64encode(png_bytes).decode("utf-8")


def request_name_from_llm(
    client: OpenAI, model: str, base64_image: str, user_prompt: str
) -> str | None:
    last_exception = None
    for attempt in range(1, MAX_LLM_ATTEMPTS + 1):
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
                                "image_url": {
                                    "url": f"data:image/png;base64,{base64_image}"
                                },
                            },
                        ],
                    },
                ],
            )
            return response.choices[0].message.content
        except Exception as exception:
            last_exception = exception
            print(
                f"    Attempt {attempt}/{MAX_LLM_ATTEMPTS} failed: {exception}",
                flush=True,
            )
            if attempt < MAX_LLM_ATTEMPTS:
                time.sleep(3 * attempt)
    raise RuntimeError(
        f"Failed to query the LLM after {MAX_LLM_ATTEMPTS} attempts: {last_exception}"
    )


def sanitize_name(raw_name: str) -> str:
    name = raw_name.strip().strip("\"'")
    name = name.replace("`", "")
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
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


def main() -> int:
    configuration = load_configuration()
    input_folder = configuration.input_dir
    output_folder = configuration.output_dir

    print(f"INPUT_DIR={input_folder} | OUTPUT_DIR={output_folder}", flush=True)
    print(
        f"LLM_BASE_URL={configuration.llm_base_url} | LLM_MODEL={configuration.llm_model}",
        flush=True,
    )

    if not input_folder.exists():
        print(f"Input folder '{input_folder}' does not exist. Exiting.", flush=True)
        return 1

    output_folder.mkdir(parents=True, exist_ok=True)

    pdf_files = list_pdf_files(input_folder)

    if not pdf_files:
        print(
            f"No PDF files found in '{input_folder}'. Folder is empty. Exiting.",
            flush=True,
        )
        return 0

    total = len(pdf_files)
    print(f"Found {total} PDF file(s) to process.", flush=True)

    client = OpenAI(
        base_url=configuration.llm_base_url,
        api_key=configuration.llm_api_key or "not-needed",
        timeout=LLM_TIMEOUT_SECONDS,
    )
    model = configuration.llm_model
    user_prompt = configuration.user_prompt

    successes = 0
    failures = 0

    for index, pdf_file in enumerate(pdf_files, start=1):
        print(
            f"[Iteration {index}/{total}] Processing current file: {pdf_file.name}",
            flush=True,
        )

        try:
            base64_image = render_first_page_as_base64(pdf_file)

            raw_suggestion = request_name_from_llm(client, model, base64_image, user_prompt)
            new_name = sanitize_name(raw_suggestion or "")

            if not new_name:
                new_name = sanitize_name(pdf_file.stem) or f"document_{index}"
                print(
                    f"    LLM returned an empty/invalid result. Using fallback name: {new_name}",
                    flush=True,
                )

            destination_path = resolve_destination_path(output_folder, new_name)
            shutil.move(str(pdf_file), str(destination_path))

            successes += 1
            print(
                f"[Iteration {index}/{total}] Success: '{pdf_file.name}' renamed "
                f"to '{destination_path.name}' and moved to '{destination_path}'",
                flush=True,
            )
        except Exception as exception:
            failures += 1
            print(
                f"[Iteration {index}/{total}] Error processing '{pdf_file.name}': {exception}",
                flush=True,
            )

    print(
        f"Processing complete: {successes} success(es), {failures} failure(s), total {total}.",
        flush=True,
    )
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
