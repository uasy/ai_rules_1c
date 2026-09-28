"""Offline regression for transcription model selection and the Gemini call boundary."""

import contextlib
import io
import os
from pathlib import Path
import runpy
import sys
import types
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[2] / "content/skills/transcribe/scripts/transcribe.py"


def load_script(env, dotenv_values=None):
    dotenv = types.ModuleType("dotenv")

    def load_dotenv(*args, **kwargs):
        for key, value in (dotenv_values or {}).items():
            os.environ.setdefault(key, value)

    dotenv.load_dotenv = load_dotenv
    google = types.ModuleType("google")
    google.genai = types.ModuleType("google.genai")
    # No credentials, network calls or installed SDK are needed by these tests.
    with patch.object(Path, "home", return_value=SCRIPT.parent), patch.dict(os.environ, env, clear=True), patch.dict(
        sys.modules, {"dotenv": dotenv, "google": google, "google.genai": google.genai}
    ):
        return runpy.run_path(str(SCRIPT), run_name="transcribe_regression")


class TranscribeRegression(unittest.TestCase):
    def test_default_and_blank_model(self):
        for env in ({}, {"GEMINI_MODEL": ""}, {"GEMINI_MODEL": " \t "}):
            with self.subTest(env=env):
                module = load_script(env)
                client = Mock()
                client.models.generate_content.return_value.text = "transcript"
                self.assertEqual(module["generate"](client, "media", "prompt"), "transcript")
                client.models.generate_content.assert_called_once_with(
                    model="gemini-3.6-flash", contents=["media", "prompt"]
                )

    def test_environment_overrides_dotenv(self):
        module = load_script({"GEMINI_MODEL": " custom-model "}, {"GEMINI_MODEL": "dotenv-model"})
        client = Mock()
        client.models.generate_content.return_value.text = "transcript"
        module["generate"](client, "media", "prompt")
        client.models.generate_content.assert_called_once_with(
            model="custom-model", contents=["media", "prompt"]
        )

    def test_model_loaded_after_dotenv(self):
        module = load_script({}, {"GEMINI_MODEL": "dotenv-model"})
        self.assertEqual(module["MODEL"], "dotenv-model")

    def test_generic_modes_use_selected_model(self):
        module = load_script({"GEMINI_MODEL": "custom-model"})
        client = Mock()
        client.models.generate_content.return_value.text = "[00:00] transcript"
        self.assertIn("transcript", module["transcribe_generic"](client, "media"))
        self.assertIn("transcript", module["generate_summary_generic"](client, "media"))
        for call in client.models.generate_content.call_args_list:
            self.assertEqual(call.kwargs["model"], "custom-model")

    def test_ui_mode_uses_selected_model_for_all_four_requests(self):
        module = load_script({"GEMINI_MODEL": "custom-model"})
        client = Mock()
        client.models.generate_content.side_effect = [
            types.SimpleNamespace(text=text)
            for text in ("summary", "details", "[]", "transcript")
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            result = module["analyze_ui_single"](client, "media", "video", "output")
        self.assertEqual(result, ("summary", "details", "transcript"))
        self.assertEqual(client.models.generate_content.call_count, 4)
        for call in client.models.generate_content.call_args_list:
            self.assertEqual(call.kwargs["model"], "custom-model")

    def test_empty_response_is_still_an_error(self):
        module = load_script({})
        client = Mock()
        client.models.generate_content.return_value = types.SimpleNamespace(text="", candidates=[])
        with self.assertRaises(RuntimeError):
            module["generate"](client, "media", "prompt")


if __name__ == "__main__":
    unittest.main(verbosity=2)
