import os
import pathlib
import tempfile
import unittest
from unittest import mock

import forager
import pymupdf
from pydantic import ValidationError

import main
from main import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_USER_PROMPT,
    build_pipeline,
    resolve_destination_path,
    sanitize_name,
)


class SanitizeNameTest(unittest.TestCase):
    def test_strips_surrounding_quotes_and_backticks(self):
        for raw in ('"Invoice 2024"', "'Invoice 2024'", "`Invoice 2024`"):
            with self.subTest(raw=raw):
                self.assertEqual(sanitize_name(raw), "Invoice 2024")

    def test_preserves_accents(self):
        self.assertEqual(sanitize_name("Ação e Descrição"), "Ação e Descrição")
        self.assertEqual(sanitize_name("2025-03 Serviços Prestados"), "2025-03 Serviços Prestados")

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


class BuildPipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.llm_settings = forager.LlmSettings(
            base_url="http://localhost:8080/v1",
            model="some/model",
            api_key="sk-test",
        )
        cls.pipeline = build_pipeline(cls.llm_settings, "Name this document.")

    def test_build_pipeline_passes_str_base_url(self):
        with mock.patch("openai.OpenAI") as client_cls:
            build_pipeline(self.llm_settings, "Name this document.")
        base_url = client_cls.call_args.kwargs["base_url"]
        self.assertIsInstance(base_url, str)
        self.assertEqual(base_url, "http://localhost:8080/v1")

    @staticmethod
    def _make_pdf(folder: pathlib.Path, name: str = "doc.pdf") -> pathlib.Path:
        pdf_path = folder / name
        with pymupdf.open() as document:
            document.new_page()
            document.save(pdf_path)
        return pdf_path

    def test_ask_sends_image_as_multimodal_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(pathlib.Path(tmp))
            with mock.patch("openai.OpenAI") as client_cls:
                pipeline = build_pipeline(self.llm_settings, "Name this document.")
                client = client_cls.return_value
                client.chat.completions.create.return_value.choices[0].message.content = "Invoice 2024"
                result = pipeline._llm(pdf_path)
        self.assertEqual(result, "Invoice 2024")
        create_kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(create_kwargs["model"], "some/model")
        messages = create_kwargs["messages"]
        self.assertEqual(messages[0]["role"], "system")
        user_message = messages[1]
        self.assertEqual(user_message["role"], "user")
        content = user_message["content"]
        self.assertIsInstance(content, list)
        types = [part["type"] for part in content]
        self.assertIn("text", types)
        self.assertIn("image_url", types)
        text_part = next(part for part in content if part["type"] == "text")
        self.assertEqual(text_part["text"], "Name this document.")
        image_part = next(part for part in content if part["type"] == "image_url")
        self.assertTrue(image_part["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_ask_retries_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(pathlib.Path(tmp))
            with mock.patch("openai.OpenAI") as client_cls, mock.patch("main.time.sleep"):
                pipeline = build_pipeline(self.llm_settings, "Name this document.")
                client = client_cls.return_value
                client.chat.completions.create.side_effect = [
                    RuntimeError("boom"),
                    mock.Mock(choices=[mock.Mock(message=mock.Mock(content="Invoice 2024"))]),
                ]
                result = pipeline._llm(pdf_path)
        self.assertEqual(result, "Invoice 2024")
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_ask_raises_after_exhausting_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = self._make_pdf(pathlib.Path(tmp))
            with mock.patch("openai.OpenAI") as client_cls, mock.patch("main.time.sleep"):
                pipeline = build_pipeline(self.llm_settings, "Name this document.")
                client = client_cls.return_value
                client.chat.completions.create.side_effect = RuntimeError("boom")
                with self.assertRaises(RuntimeError):
                    pipeline._llm(pdf_path)
        self.assertEqual(client.chat.completions.create.call_count, self.llm_settings.max_attempts)

    def test_file_filter_keeps_only_pdfs(self):
        file_filter = self.pipeline._file_filter
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            (folder / "a.pdf").touch()
            (folder / "b.PDF").touch()
            (folder / "c.txt").touch()
            self.assertTrue(file_filter(folder / "a.pdf"))
            self.assertTrue(file_filter(folder / "b.PDF"))
            self.assertFalse(file_filter(folder / "c.txt"))
            self.assertFalse(file_filter(folder))

    def test_result_filter_rejects_empty_responses(self):
        result_filter = self.pipeline._result_filter
        self.assertFalse(result_filter(None))
        self.assertFalse(result_filter(""))
        self.assertFalse(result_filter("***"))
        self.assertTrue(result_filter("Invoice 2024"))

    def test_action_moves_and_renames_file(self):
        action = self.pipeline._action
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            input_dir = root / "in"
            output_dir = root / "out"
            input_dir.mkdir()
            output_dir.mkdir()
            source = input_dir / "scan.pdf"
            source.touch()
            destination = action(source, "Invoice 2024", output_dir)
            assert destination is not None
            self.assertEqual(destination, output_dir / "Invoice 2024.pdf")
            self.assertFalse(source.exists())
            self.assertTrue(destination.exists())

    def test_action_avoids_collisions(self):
        action = self.pipeline._action
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            input_dir = root / "in"
            output_dir = root / "out"
            input_dir.mkdir()
            output_dir.mkdir()
            (output_dir / "Invoice 2024.pdf").touch()
            source = input_dir / "scan.pdf"
            source.touch()
            destination = action(source, "Invoice 2024", output_dir)
            assert destination is not None
            self.assertEqual(destination, output_dir / "Invoice 2024_1.pdf")
            self.assertTrue(destination.exists())

    def test_action_falls_back_to_stem(self):
        action = self.pipeline._action
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            input_dir = root / "in"
            output_dir = root / "out"
            input_dir.mkdir()
            output_dir.mkdir()
            source = input_dir / "scan.pdf"
            source.touch()
            destination = action(source, "***", output_dir)
            self.assertEqual(destination, output_dir / "scan.pdf")


class MainConfigurationTest(unittest.TestCase):
    def test_uses_openrouter_defaults_when_env_not_set(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("main.build_pipeline") as build:
                build.return_value.run.return_value = None
                main.main()
        settings = build.call_args.args[0]
        self.assertEqual(str(settings.base_url), DEFAULT_LLM_BASE_URL)
        self.assertEqual(settings.model, DEFAULT_LLM_MODEL)

    def test_uses_default_user_prompt_when_env_not_set(self):
        env = {"LLM_BASE_URL": "http://localhost:8080/v1", "LLM_MODEL": "some/model"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("main.build_pipeline") as build:
                build.return_value.run.return_value = None
                main.main()
        self.assertEqual(build.call_args.args[1], DEFAULT_USER_PROMPT)

    def test_uses_user_prompt_from_environment(self):
        env = {"LLM_BASE_URL": "http://localhost:8080/v1", "LLM_MODEL": "some/model", "LLM_USER_PROMPT": "Name it."}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("main.build_pipeline") as build:
                build.return_value.run.return_value = None
                main.main()
        self.assertEqual(build.call_args.args[1], "Name it.")

    def test_rejects_empty_values(self):
        env = {"LLM_BASE_URL": "http://localhost:8080/v1", "LLM_MODEL": "  ", "LLM_USER_PROMPT": "Name it."}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValidationError):
                main.main()

    def test_rejects_zero_attempts(self):
        env = {"LLM_MAX_ATTEMPTS": "0", "LLM_USER_PROMPT": "Name it."}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValidationError):
                main.main()


if __name__ == "__main__":
    unittest.main()
