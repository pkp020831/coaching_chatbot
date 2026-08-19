import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from serve_search_web import load_project_environment


class WebServerEnvironmentTest(unittest.TestCase):
    def test_loads_env_before_health_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("GEMINI_API_KEY=test-key\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                load_project_environment(env_path)
                self.assertEqual(os.environ.get("GEMINI_API_KEY"), "test-key")

    def test_existing_environment_value_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("GEMINI_API_KEY=file-key\n", encoding="utf-8")

            with patch.dict(os.environ, {"GEMINI_API_KEY": "shell-key"}, clear=True):
                load_project_environment(env_path)
                self.assertEqual(os.environ.get("GEMINI_API_KEY"), "shell-key")


if __name__ == "__main__":
    unittest.main()
