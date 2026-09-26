"""What the pairs of /qa are asked about: a compendium the endpoint makes, or a text the caller sends (D55, D60).

Jan, 2026-09-26: when a text yields little, the glossary and the actors fill up. A caller who sends the markdown of a
compendium - what README and /docs suggest - has both in it, but the text used to be asked as it was: the sources
block fed the rules year questions from literature lines, and the glossary and actor rows were read as prose.
"""

from __future__ import annotations

from app.domain.requests import GenerateRequest
from app.service import CompendiumService
from app.synthesis.qa_knowledge import knowledge_of_compendium, knowledge_of_text


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
