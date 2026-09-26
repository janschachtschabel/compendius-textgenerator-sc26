"""What the pairs of /qa are asked about: a compendium the endpoint makes, or a text the caller sends (D55, D60).

Jan, 2026-09-26: when a text yields little, the glossary and the actors fill up. A caller who sends the markdown of a
compendium - what README and /docs suggest - has both in it, but the text used to be asked as it was: the sources
block fed the rules year questions from literature lines, and the glossary and actor rows were read as prose.
"""

from __future__ import annotations

import time

import pytest

from app.api.v2.qa_schemas import MAX_TEXT_CHARS
from app.domain.requests import GenerateRequest
from app.service import CompendiumService
from app.synthesis.qa_knowledge import knowledge_of_compendium, knowledge_of_text
from app.synthesis.qa_rules import actor_candidates, glossary_candidates

# Reading the longest text a caller may send is linear work of milliseconds; the patterns the review of D60 found
# backtracked on a long run of blanks - seconds before a bracket or in the prose, hours inside a glossary row
BUDGET_S = 1.0


def test_a_compendium_sent_as_text_is_read_as_the_compendium_it_is(service: CompendiumService) -> None:
    compendium = service.generate(GenerateRequest(topic="Optik", parts=["world"], preset="llm-free"))
    made = knowledge_of_compendium(compendium)
    sent = knowledge_of_text(compendium.markdown)
    assert made.glossary and made.actors, "the sample compendium has both blocks, or this test proves nothing"
    assert (sent.text, sent.glossary, sent.actors, sent.topic) == (made.text, made.glossary, made.actors, made.topic)
    assert "ISBN" not in sent.text and "## Quellen" not in sent.text


def test_any_other_text_is_asked_as_it_is() -> None:
    text = "Die Optik ist ein Teilgebiet der Physik. Ein Fernrohr besteht aus einem Objektiv und einem Okular."
    knowledge = knowledge_of_text(text)
    assert (knowledge.text, knowledge.glossary, knowledge.actors, knowledge.topic) == (text, "", "", None)


class _NoEntities:
    """An nlp stand-in whose doc names no entity, so no glossary term is taken for a person."""

    ents: tuple[()] = ()

    def __call__(self, text: str) -> _NoEntities:
        return self


def _compendium(prose: str, generated: str) -> str:
    """The markdown of a compendium with one prose block and one generated block, as parse_document reads it."""
    return (
        "# Kompendium: Optik\n\n"
        "### Einstieg\n<!-- kompendium:section id=einstieg status=maschinell-extraktiv hash=0 -->\n\n"
        f"{prose}\n\n"
        "### Glossar\n<!-- kompendium:section id=glossar status=maschinell-generiert hash=0 -->\n\n"
        f"{generated}\n"
    )


def crafted_texts(run: str) -> dict[str, str]:
    """A compendium for every place a run of blanks reaches a pattern: in a glossary row, its term and its
    definition, in the name and the summary of an actor, and in the prose."""
    prose, related = "Die Optik ist ein Teilgebiet der Physik.", "`skos:related`"
    return {
        "glossary row": _compendium(prose, f"| **a** |{run}x"),
        "glossary term": _compendium(prose, f"| **a{run}(x** | Die Optik ist ein Teilgebiet. | {related} |"),
        "glossary definition": _compendium(prose, f"| **Optik** | Die{run}Optik nennt man Lichtlehre. | {related} |"),
        "actor summary": _compendium(prose, f"#### Person\n- **[A](u)** — x{run}("),
        "actor name": _compendium(prose, f"#### Person\n- **[A{run}(x](u)** — Er war ein Physiker und Optiker."),
        "prose": _compendium(f"a{run}b", f"| **Optik** | Die Optik ist ein Teilgebiet. | {related} |"),
    }


CRAFTED = crafted_texts(" " * (MAX_TEXT_CHARS - 500))


@pytest.mark.parametrize("text", CRAFTED.values(), ids=CRAFTED.keys())
def test_a_crafted_text_is_read_in_linear_time(text: str) -> None:
    """/qa reads the text of the caller with these rules before it picks a method, and without a login (D60)."""
    assert len(text) <= MAX_TEXT_CHARS
    started = time.perf_counter()
    knowledge = knowledge_of_text(text)
    glossary_candidates(knowledge.glossary, _NoEntities())
    actor_candidates(knowledge.actors)
    seconds = time.perf_counter() - started
    assert seconds < BUDGET_S
