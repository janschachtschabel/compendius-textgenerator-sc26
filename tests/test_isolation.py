"""The developer's shell never configures the tests: B_API_KEY, LLM_ENABLED, MODEL2VEC_PATH, POLICY_* ..."""

import os

from app.settings import Settings


def test_the_shell_configuration_does_not_reach_the_tests() -> None:
    fields = {name.lower() for name in Settings.model_fields}
    assert [key for key in os.environ if key.lower() in fields] == []
