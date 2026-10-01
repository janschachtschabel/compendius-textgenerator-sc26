"""M46: mc_llm_dienst.py with a layout of the matcher prompt of its own, past the b-api's response cache.

v1s  the layout of paragraph_assignment v1: blocks and rules in the user message, one space after the last word
v2s  the layout of v2 (D69): blocks and rules in the system message, one space after the last word

The b-api answers a request it has seen word for word from its response cache; the space makes it new without
changing what the model reads. mc_llm_dienst.py as it is runs the layout of the service (v2).

The key comes from B_API_KEY. About 106,000 tokens per run.

Usage (from the project folder): python mc_zuordnung_aufbau.py v1s|v2s <m5_llm_zuordnung.json> <out.json> <token_limit>
"""

from __future__ import annotations

import runpy
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import app.matching.llm_assignment as assignment
from app.domain.models import Chunk, Source
from app.llm.prompts import get_prompt
from app.templates.schema import Template

V1_USER = (
    "Thema des Kompendiums: {topic}\n\nBausteine:\n{blocks}\n\n{rules}Absätze:\n{paragraphs}\n\nGib das JSON-Objekt "
    "zurück. "
)
v2 = assignment.render_messages


def v1s(template: Template, topic: str, chunks: Sequence[Chunk], sources: Mapping[str, Source]) -> list[dict[str, str]]:
    messages = v2(template, topic, chunks, sources)
    system = get_prompt("paragraph_assignment").system
    blocks, _, rules = messages[0]["content"][len(system) + 2 :].removeprefix("Bausteine:\n").partition("\n\n")
    paragraphs = messages[1]["content"].split("Absätze:\n", 1)[1].rsplit("\n\nGib das JSON-Objekt zurück.", 1)[0]
    user = V1_USER.format(topic=topic, blocks=blocks, rules=f"{rules}\n\n" if rules else "", paragraphs=paragraphs)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def v2s(template: Template, topic: str, chunks: Sequence[Chunk], sources: Mapping[str, Source]) -> list[dict[str, str]]:
    messages = v2(template, topic, chunks, sources)
    return [messages[0], {"role": "user", "content": messages[1]["content"] + " "}]


if __name__ == "__main__":
    layout = sys.argv.pop(1)
    assignment.render_messages = {"v1s": v1s, "v2s": v2s}[layout]
    script = Path(__file__).with_name("mc_llm_dienst.py")
    sys.argv[0] = str(script)
    runpy.run_path(str(script), run_name="__main__")
