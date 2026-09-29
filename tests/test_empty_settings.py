"""An entry left empty is the default (audit 2026-09-28, BE-13; Jan's rule of 2026-09-28).

A panel or a .env writes a field left blank as ``VAR=``, and pydantic read that as the value "": 34 of 67 settings
refused it and kept all five containers in a restart loop, 20 took "" for their value - ``LOG_LEVEL=`` broke the start,
``CONFIG_DIR=`` read the configuration from ".", ``ZIM_DOWNLOAD_HOSTS=`` allowed no download host. Four settings give
"empty" a meaning of their own and keep it: no collections, only the configured repository, no embeddings, no spaCy
model - the last two although the image sets both (audit 2026-09-29, S5).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from app import main, serve
from app.main import create_app
from app.settings import Settings

KEEP_THEIR_EMPTY = {"edu_sharing_base_url", "edu_sharing_repositories", "model2vec_path", "spacy_model"}
# What compose empties for the four sidecars (x-no-secrets in docker-compose.yml)
SIDECAR_SECRETS = ("B_API_KEY", "EDU_SHARING_USER", "EDU_SHARING_PASSWORD", "ADMIN_TOKEN", "METRICS_TOKEN", "API_KEYS")


@pytest.mark.parametrize("entered", ["", "   "])
@pytest.mark.parametrize("name", sorted(set(Settings.model_fields) - KEEP_THEIR_EMPTY))
def test_a_setting_left_empty_is_its_default(monkeypatch: pytest.MonkeyPatch, name: str, entered: str) -> None:
    monkeypatch.setenv(name.upper(), entered)

    settings = Settings(_env_file=None)

    assert getattr(settings, name) == Settings.model_fields[name].default


@pytest.mark.parametrize("entered", ["", "   "])
@pytest.mark.parametrize("name", sorted(KEEP_THEIR_EMPTY))
def test_the_settings_whose_empty_means_something_keep_it(
    monkeypatch: pytest.MonkeyPatch, name: str, entered: str
) -> None:
    monkeypatch.setenv(name.upper(), entered)

    settings = Settings(_env_file=None)

    assert getattr(settings, name) == ""


def test_an_empty_model_is_named_at_start(settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    """An entry emptied in a panel overrides the model the image sets, and empty switches it off: entities without
    the spaCy model, the QA rules on four templates, the matching without embeddings (audit 2026-09-29, S5)."""
    with caplog.at_level("WARNING"):
        create_app(settings.model_copy(update={"model2vec_path": "", "spacy_model": ""}))

    assert "MODEL2VEC_PATH is empty" in caplog.text and "without embeddings" in caplog.text
    assert "SPACY_MODEL is empty" in caplog.text and "four templates" in caplog.text


def test_a_model_that_is_set_is_not_called_empty(
    settings: Settings, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "load_spacy", lambda model: object())
    monkeypatch.setattr(main, "active_components", lambda name, path: ["bm25", "char_tfidf", "model2vec"])

    with caplog.at_level("WARNING"):
        create_app(settings.model_copy(update={"model2vec_path": "/models/m2v", "spacy_model": "de_core_news_md"}))

    assert "is empty" not in caplog.text


def test_an_emptied_secret_does_not_come_back_from_the_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # compose empties the secrets of the sidecars in their environment; the .env must not fill them in again
    env_file = tmp_path / ".env"
    env_file.write_text("".join(f"{name}={'s' * 32}\n" for name in SIDECAR_SECRETS), encoding="utf-8")
    for name in SIDECAR_SECRETS:
        monkeypatch.setenv(name, "")

    settings = Settings(_env_file=env_file)

    assert [getattr(settings, name.lower()) for name in SIDECAR_SECRETS] == [""] * len(SIDECAR_SECRETS)


@pytest.mark.parametrize(
    ("name", "default"), [("WEB_CONCURRENCY", "2"), ("FORWARDED_ALLOW_IPS", "127.0.0.1,::1"), ("UVICORN_HTTP", "h11")]
)
def test_uvicorn_gets_the_default_of_a_process_variable_left_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, default: str
) -> None:
    # uvicorn reads WEB_CONCURRENCY with int(): an empty entry stopped the API before any setting was read
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    monkeypatch.setattr(serve, "DEFAULT_DIR", str(tmp_path / "metrics"))
    monkeypatch.setenv(name, "")
    handed: list[dict[str, Any]] = []
    monkeypatch.setattr(os, "execvpe", lambda file, args, env: handed.append(env))

    serve.main()

    assert handed[0][name] == default
