"""Texts for the tests of /qa: the markdown of a compendium as parse_document reads it, and inputs built to make a
pattern backtrack (reviews of D60).

Run as a module, it reads every crafted input the way the service reads what a caller sends and prints one line per
input with its seconds. A pattern that backtracks holds the interpreter lock, so no thread could stop it: the tests
start this in a process of their own and stop that after a deadline (tests/test_crafted_inputs.py).
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable

from annotated_types import MaxLen

from app.api.v2.qa_schemas import MAX_TEXT_CHARS
from app.compose.regeneration import parse_document
from app.domain.requests import GenerateRequest
from app.synthesis.qa_knowledge import knowledge_of_text
from app.synthesis.qa_rules import actor_candidates, glossary_candidates

PROSE = "Die Optik ist ein Teilgebiet der Physik."
GLOSSARY_ROW = "| **Optik** | Die Optik ist ein Teilgebiet. | `skos:related` |"
# the longest earlier compendium /compendium takes along (existing_markdown)
MARKDOWN_CHARS = next(
    rule.max_length for rule in GenerateRequest.model_fields["existing_markdown"].metadata if isinstance(rule, MaxLen)
)


class NoEntities:
    """An nlp stand-in whose doc names no entity, so no glossary term is taken for a person."""

    ents: tuple[()] = ()

    def __call__(self, text: str) -> NoEntities:
        return self


def block(slot: str, status: str, text: str) -> str:
    return f"### {slot}\n<!-- kompendium:section id={slot} status={status} hash=0 -->\n\n{text}\n\n"


def compendium_markdown(prose: str, generated: str) -> str:
    """The markdown of a compendium with one prose block and one generated block, as parse_document reads it."""
    return (
        "# Kompendium: Optik\n\n"
        + block("einstieg", "maschinell-extraktiv", prose)
        + block("glossar", "maschinell-generiert", generated)
    )


def crafted_markdown(length: int = MARKDOWN_CHARS) -> dict[str, str]:
    """What parse_document meets in an earlier compendium sent along: a heading and a citation row over and over."""
    return {"headings": "### " * (length // 4), "citation rows": "| [1] | [t](\n" * (length // 13)}


def crafted_texts(length: int = MAX_TEXT_CHARS) -> dict[str, str]:
    """A text of at most ``length`` characters for every place where a caller's text meets a pattern that could
    backtrack: runs of blanks in a glossary row, its term and its definition, in an actor's name and summary and in
    the prose; runs of "(" in a term and a name; and the shapes parse_document meets."""
    run, brackets, related = " " * (length - 500), "(" * (length - 500), "`skos:related`"
    return {
        "blanks in a glossary row": compendium_markdown(PROSE, f"| **a** |{run}x"),
        "blanks in a glossary term": compendium_markdown(
            PROSE, f"| **a{run}(x** | Die Optik ist ein Teilgebiet. | {related} |"
        ),
        "blanks in a definition": compendium_markdown(
            PROSE, f"| **Optik** | Die{run}Optik nennt man Lichtlehre. | {related} |"
        ),
        "blanks in an actor summary": compendium_markdown(PROSE, f"#### Person\n- **[A](u)** — x{run}("),
        "blanks in an actor name": compendium_markdown(
            PROSE, f"#### Person\n- **[A{run}(x](u)** — Er war ein deutscher Physiker und Optiker."
        ),
        "blanks in the prose": compendium_markdown(f"a{run}b", GLOSSARY_ROW),
        "brackets in a glossary term": compendium_markdown(
            PROSE, f"| **a{brackets}** | Die Optik ist ein Teilgebiet. | {related} |"
        ),
        "brackets in an actor name": compendium_markdown(
            PROSE, f"#### Person\n- **[A{brackets}](u)** — Er war ein deutscher Physiker und Optiker."
        ),
        **crafted_markdown(length),
    }


def read_as_qa(text: str) -> None:
    """What /qa does with a caller's text before it picks a method."""
    knowledge = knowledge_of_text(text)
    glossary_candidates(knowledge.glossary, NoEntities())
    actor_candidates(knowledge.actors)


if __name__ == "__main__":
    readers: list[tuple[str, Callable[[str], object], dict[str, str]]] = [
        ("qa", read_as_qa, crafted_texts()),
        ("compendium", parse_document, crafted_markdown()),
    ]
    for where, read, inputs in readers:
        for name, text in inputs.items():
            started = time.perf_counter()
            read(text)
            sys.stdout.write(f"{where}\t{name}\t{time.perf_counter() - started:.3f}\n")
            sys.stdout.flush()
