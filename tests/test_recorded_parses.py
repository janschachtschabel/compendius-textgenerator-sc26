"""The recorded spaCy parses are those of the model the image installs (audit 2026-09-28, TE-15).

The rule tests of /qa replay parses recorded in the image (tests/recorded_spacy.py). After the image took another
model or version they would still pass, on parses no running service makes any more.
"""

from __future__ import annotations

import json
import re

from tests.conftest import ROOT
from tests.recorded_spacy import RECORDING


def test_the_recorded_parses_name_the_model_and_version_of_the_image() -> None:
    fixture = json.loads(RECORDING.read_text(encoding="utf-8"))
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    image = dict(re.findall(r"^ARG (SPACY_MODEL|SPACY_MODEL_VERSION)=(\S*)$", dockerfile, re.MULTILINE))

    assert (fixture["model"], fixture.get("version")) == (image["SPACY_MODEL"], image["SPACY_MODEL_VERSION"])
