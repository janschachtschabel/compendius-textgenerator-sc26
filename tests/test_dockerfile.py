"""The runtime of the image names the models its build installed (audit 2026-09-29, O9).

The build arguments MODEL2VEC_ID and SPACY_MODEL chose the models of the builder stage, while the runtime stage set
MODEL2VEC_PATH=/models/m2v and SPACY_MODEL=de_core_news_md for good. An image built without the Model2Vec model, as
docs/installation.md offers, logged an ERROR at every start for a model it was meant to lack, and another spaCy model
lay in the image unused. An ARG ends with its stage, so the runtime stage has to declare both again; their defaults
stand once, before the first FROM, so that the two stages cannot drift apart.
"""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

import pytest

from tests.conftest import ROOT

DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
MODELS = ("MODEL2VEC_ID", "SPACY_MODEL")


def stages() -> dict[str, str]:
    """The text before the first FROM (key "") and of each stage, by its name."""
    parts = re.split(r"^FROM \S+ AS (\w+)$", DOCKERFILE, flags=re.MULTILINE)
    return {"": parts[0], **dict(zip(parts[1::2], parts[2::2], strict=True))}


def declared(text: str) -> dict[str, str]:
    """The ARGs a part of the Dockerfile declares, with their default ("" without one)."""
    return dict(re.findall(r"^ARG (\w+)(?:=(\S*))?$", text, re.MULTILINE))


def test_the_model_arguments_have_one_default_that_both_stages_take() -> None:
    parts = stages()

    assert all(declared(parts[""]).get(name) for name in MODELS), "a default for each, before the first FROM"
    for stage in ("builder", "runtime"):
        assert {name: declared(parts[stage]).get(name, "missing") for name in MODELS} == dict.fromkeys(MODELS, "")


def test_the_runtime_takes_its_model_settings_from_the_build_arguments() -> None:
    runtime = stages()["runtime"]

    assert "MODEL2VEC_PATH=${MODEL2VEC_ID:+/models/m2v}" in runtime  # empty without the model
    assert "SPACY_MODEL=${SPACY_MODEL}" in runtime


def healthcheck_code() -> str:
    """The Python the image's HEALTHCHECK runs."""
    lines = DOCKERFILE.splitlines()
    at = next(number for number, line in enumerate(lines) if line.startswith("HEALTHCHECK "))
    command = json.loads(lines[at + 1].strip().removeprefix("CMD "))
    assert command[:2] == ["python", "-c"]
    return str(command[2])


@pytest.mark.parametrize(
    ("environment", "port"),
    [
        ({}, "9000"),
        ({"INTERNAL_PORT": ""}, "9000"),
        ({"INTERNAL_PORT": "9100"}, "9100"),
        ({"INTERNAL_PORT": "0"}, "8000"),
        ({"INTERNAL_PORT": "00"}, "8000"),  # Settings reads a number: 00 switches the port off as 0 does
        ({"INTERNAL_PORT": "0", "PUBLIC_PORT": "8100"}, "8100"),
        ({"INTERNAL_PORT": "9100", "PUBLIC_PORT": "8100"}, "9100"),
    ],
)
def test_the_healthcheck_asks_the_port_where_health_answers(
    monkeypatch: pytest.MonkeyPatch, environment: dict[str, str], port: str
) -> None:
    """/health answers on the internal port, with INTERNAL_PORT=0 on the API's (D110); both ports are settings."""
    for name in ("INTERNAL_PORT", "PUBLIC_PORT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    asked: list[str] = []

    class Answer:
        status = 200

    def urlopen(url: str, timeout: float) -> Any:
        asked.append(url)
        return Answer()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(SystemExit) as stop:
        exec(healthcheck_code(), {})  # noqa: S102 - the image's own healthcheck line

    assert stop.value.code == 0 and asked == [f"http://127.0.0.1:{port}/health"]
