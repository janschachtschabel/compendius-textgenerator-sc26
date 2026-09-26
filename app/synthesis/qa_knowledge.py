"""What the pairs of /qa are asked about: the prose of a compendium, its glossary and actors, and its topic (D55, D60).

A topic or node gets part 1 of its compendium made by the endpoint; a caller may also send the markdown of a
compendium they already have. Both are read alike: the prose of the content blocks is asked, the glossary and
the actor list fill up when it runs out (app/synthesis/qa_rules.py), and the sources block stays out. Any other
text is asked as it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.compose.regeneration import parse_document
from app.domain.models import Compendium, SectionStatus
from app.synthesis.citations import without_markers
from app.synthesis.qa_rules import is_actor_block, is_glossary_block

_TITLE = re.compile(r"^# Kompendium: (?P<topic>.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Knowledge:
    """What the pairs are asked about: the prose, and for a compendium its glossary and actors and its topic."""

    text: str
    glossary: str = ""
    actors: str = ""
    topic: str | None = None


def text_of_compendium(compendium: Compendium) -> str:
    """The prose of the content blocks, in reading order - not the apparatus around them.

    Two things are left out, and both for the same reason: they are apparatus, not subject matter.
    The markdown of the finished document carries headings, citation numbers and facet markers, so
    only the block texts are read. And of those the generated blocks are skipped - the sources block,
    the glossary and the actor directory are link lists and tables that a question generator turns
    into nonsense.

    Measured against the running service on 2026-09-21 for one topic: of 27 614 characters of blocks,
    20 522 were the three generated ones. Asked about, they produced a question about the year 1999
    answered with a literature line and its ISBN - three quarters of the text taught nothing, and the
    literature lines are where the flood of year questions came from.
    """
    joined = "\n\n".join(
        section.text.strip()
        for section in compendium.sections
        if section.text.strip() and section.status is not SectionStatus.GENERATED
    )
    return without_markers(joined)


def knowledge_of_compendium(compendium: Compendium) -> Knowledge:
    """The prose of part 1, and the two generated blocks the rules can read on their own terms (D55).

    The glossary holds one definition per related article and the actor list the first sentence of each person's
    article: no prose a parse could ask about, but a definition asks "Was ist …?" and a person "Wer war …?".
    """
    blocks = {section.slot_key: section.text for section in compendium.sections if section.text.strip()}
    title = compendium.resolution.title if compendium.resolution is not None else compendium.topic
    return Knowledge(
        text=text_of_compendium(compendium),
        glossary=blocks.get("glossar", ""),
        actors=blocks.get("akteure", ""),
        topic=title,
    )


def knowledge_of_text(text: str) -> Knowledge:
    """A text as the pairs see it: the markdown of a compendium as the compendium, anything else as it is (D60).

    The markers of its blocks say which block is prose and which is generated; of the generated ones the glossary
    and the actor list are told apart by their rows, and the sources block, which is neither, stays out. The topic
    is the one the heading names.
    """
    sections = [section for section in parse_document(text).values() if section.text.strip()]
    prose = [section.text.strip() for section in sections if section.status is not SectionStatus.GENERATED]
    if not prose:
        return Knowledge(text=text)
    generated = [section.text for section in sections if section.status is SectionStatus.GENERATED]
    title = _TITLE.search(text)
    return Knowledge(
        text=without_markers("\n\n".join(prose)),
        glossary="\n\n".join(block for block in generated if is_glossary_block(block)),
        actors="\n\n".join(block for block in generated if is_actor_block(block)),
        topic=title.group("topic").strip() if title else None,
    )
