"""What the pairs of /qa are asked about: a compendium the endpoint makes, or a text the caller sends (D55, D60).

Jan, 2026-09-26: when a text yields little, the glossary and the actors fill up. A caller who sends the markdown of a
compendium - what README and /docs suggest - has both in it, but the text used to be asked as it was: the sources
block fed the rules year questions from literature lines, and the glossary and actor rows were read as prose.
"""

from __future__ import annotations

from app.compose.assembler import EMPTY_SECTION_TEXT
from app.domain.requests import GenerateRequest
from app.markup.facets import END_MARKER
from app.service import CompendiumService
from app.synthesis.citations import CONCLUSION_OPEN, MODEL_KNOWLEDGE_LABEL, MODEL_KNOWLEDGE_OPEN
from app.synthesis.qa_knowledge import knowledge_of_compendium, knowledge_of_text
from tests.qa_texts import GLOSSARY_ROW, PROSE, block, compendium_markdown


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


def test_the_note_of_an_empty_block_is_no_prose() -> None:
    """With empty_slot_policy note the markdown says where a block found nothing; the prose of the compendium holds
    no such sentence, and asked, the note became a question about the sources (review of D60)."""
    text = compendium_markdown(PROSE, GLOSSARY_ROW) + block("geschichte", "leer", EMPTY_SECTION_TEXT)
    assert knowledge_of_text(text).text == PROSE


def test_a_compendium_without_prose_is_not_read_as_plain_text() -> None:
    """With empty_slot_policy omit the markdown may hold generated blocks alone. Read as plain text, their table rows
    and literature lines were asked (review of D60); like a topic without texts, it holds no prose to ask."""
    text = "# Kompendium: Optik\n\n" + block("glossar", "maschinell-generiert", GLOSSARY_ROW)
    knowledge = knowledge_of_text(text)
    assert (knowledge.text, knowledge.glossary, knowledge.topic) == ("", GLOSSARY_ROW, "Optik")


def test_sentences_of_model_knowledge_or_conclusions_and_comments_are_no_prose() -> None:
    """A compendium an LLM wrote keeps a sentence beyond its evidence in a marked block: nothing supports it. Read as
    prose, its comments stayed too, and the rules joined it to the sentence before: "Was geschah im Jahr 1905?" was
    answered with Newton's sentence, the comment and Einstein's (audit 2026-09-29, T1)."""
    prose = (
        "Isaac Newton zerlegte weißes Licht mit einem Prisma in seine Farben [3]. "
        f"{MODEL_KNOWLEDGE_OPEN}Im Jahr 1905 erklärte Albert Einstein den photoelektrischen Effekt mit Lichtquanten. "
        f"{MODEL_KNOWLEDGE_LABEL}{END_MARKER} {CONCLUSION_OPEN}Also besteht Licht aus Teilchen.{END_MARKER}\n\n"
        "Ein Prisma bricht blaues Licht<!-- Redaktion: prüfen --> stärker als rotes [4]."
    )
    assert knowledge_of_text(compendium_markdown(prose, GLOSSARY_ROW)).text == (
        "Isaac Newton zerlegte weißes Licht mit einem Prisma in seine Farben.\n\n"
        "Ein Prisma bricht blaues Licht stärker als rotes."
    )


def test_a_compendium_of_blank_blocks_is_no_plain_text() -> None:
    """A block marker with nothing under it is still a compendium: read as plain text, its marker comment was asked
    (review of D60)."""
    knowledge = knowledge_of_text("# Kompendium: Optik\n\n" + block("einstieg", "maschinell-extraktiv", ""))
    assert (knowledge.text, knowledge.topic) == ("", "Optik")
