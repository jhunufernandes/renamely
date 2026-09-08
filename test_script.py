import os
import pathlib
import tempfile
import unittest
from unittest import mock

from script import (
    DEFAULT_INPUT_DIR,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_USER_PROMPT,
    list_pdf_files,
    load_configuration,
    resolve_destination_path,
    sanitize_name,
)


class SanitizeNameTest(unittest.TestCase):
    def test_strips_surrounding_quotes_and_backticks(self):
        for raw in ('"Invoice 2024"', "'Invoice 2024'", "`Invoice 2024`"):
            with self.subTest(raw=raw):
                self.assertEqual(sanitize_name(raw), "Invoice 2024")

    def test_removes_accents(self):
        self.assertEqual(sanitize_name("Ação e Descrição"), "Acao e Descricao")

    def test_removes_unsafe_characters(self):
        self.assertEqual(sanitize_name('a/b\\c:d*e?f"g<h>i|j'), "abcdefghij")
        self.assertEqual(sanitize_name("Recibo — Setembro"), "Recibo Setembro")

    def test_collapses_whitespace(self):
        self.assertEqual(sanitize_name("  foo \t bar  "), "foo bar")

    def test_strips_pdf_suffix(self):
        self.assertEqual(sanitize_name("report.PDF"), "report")
        self.assertEqual(sanitize_name("report.pdf.pdf"), "report.pdf")

    def test_strips_trailing_separators(self):
        self.assertEqual(sanitize_name("report -_ "), "report")

    def test_empty_result(self):
        for raw in ("   ", "***", "'`'"):
            with self.subTest(raw=raw):
                self.assertEqual(sanitize_name(raw), "")


class ResolveDestinationPathTest(unittest.TestCase):
    def test_no_collision_uses_base_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            self.assertEqual(
                resolve_destination_path(folder, "invoice"),
                folder / "invoice.pdf",
            )

    def test_collision_appends_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            (folder / "invoice.pdf").touch()
            self.assertEqual(
                resolve_destination_path(folder, "invoice"),
                folder / "invoice_1.pdf",
            )

    def test_multiple_collisions_increment_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            (folder / "invoice.pdf").touch()
            (folder / "invoice_1.pdf").touch()
            self.assertEqual(
                resolve_destination_path(folder, "invoice"),
                folder / "invoice_2.pdf",
            )


class ListPdfFilesTest(unittest.TestCase):
    def test_returns_only_pdf_files_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            (folder / "b.PDF").touch()
            (folder / "a.pdf").touch()
            (folder / "c.txt").touch()
            (folder / "subdir").mkdir()
            self.assertEqual(
                list_pdf_files(folder),
                [folder / "a.pdf", folder / "b.PDF"],
            )

    def test_empty_folder_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(list_pdf_files(pathlib.Path(tmp)), [])


class LoadConfigurationTest(unittest.TestCase):
    def test_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            configuration = load_configuration()
        self.assertEqual(configuration.llm_base_url, "https://openrouter.ai/api/v1")
        self.assertEqual(configuration.llm_model, "z-ai/glm-5.3-flash")
        self.assertEqual(configuration.llm_api_key, "")
        self.assertEqual(configuration.user_prompt, DEFAULT_USER_PROMPT)
        self.assertEqual(configuration.input_dir, pathlib.Path(DEFAULT_INPUT_DIR))
        self.assertEqual(configuration.output_dir, pathlib.Path(DEFAULT_OUTPUT_DIR))

    def test_environment_overrides(self):
        env = {
            "LLM_BASE_URL": "http://localhost:8080/v1",
            "LLM_MODEL": "some/model",
            "LLM_API_KEY": "sk-test",
            "LLM_USER_PROMPT": "Name this document.",
            "INPUT_DIR": "/data/in",
            "OUTPUT_DIR": "/data/out",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            configuration = load_configuration()
        self.assertEqual(configuration.llm_base_url, "http://localhost:8080/v1")
        self.assertEqual(configuration.llm_model, "some/model")
        self.assertEqual(configuration.llm_api_key, "sk-test")
        self.assertEqual(configuration.user_prompt, "Name this document.")
        self.assertEqual(configuration.input_dir, pathlib.Path("/data/in"))
        self.assertEqual(configuration.output_dir, pathlib.Path("/data/out"))


if __name__ == "__main__":
    unittest.main()
