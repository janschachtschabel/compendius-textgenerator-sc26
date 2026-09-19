"""The developer's shell never configures the tests: B_API_KEY, LLM_ENABLED, MODEL2VEC_PATH, POLICY_* ..."""

import os
from pathlib import Path

import pytest

from app.settings import Settings


def test_the_shell_configuration_does_not_reach_the_tests() -> None:
    fields = {name.lower() for name in Settings.model_fields}
    assert [key for key in os.environ if key.lower() in fields] == []


def test_a_dotenv_file_in_the_working_directory_does_not_reach_the_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("LLM_ENABLED=true\nB_API_KEY=only-a-test-value\n", encoding="utf-8")
    settings = Settings()  # as get_settings() builds it for the CLI commands under test
    assert settings.llm_enabled is False and settings.b_api_key == ""
