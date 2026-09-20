"""Finding entity mentions in a text (docs/umbau.md, U3).

Two ways that do not depend on each other, so either can be missing:

* **the model** finds names - people, places, organisations - and knows nothing about the archives;
* **the archives** find terms that have an article of that name, which the model does not return at all:
  a subject term is no named entity, yet it is what a teaching text is mostly about.

Both return the same ``Mention``, and ``merge`` decides which survives where they overlap. Nothing here reads
article content or touches the compendium path.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

log = logging.getLogger(__name__)

MAX_TERM_WORDS = 4  # longest term looked up in the archives; "Deutsche Gesellschaft für angewandte Optik" is rarer
_WORD = re.compile(r"\w[\w-]*", re.UNICODE)
# German writes every noun with a capital, so a lower-case word starts no term. Words that do start a sentence
# and are no noun would otherwise be looked up, and a few of them really are article titles ("Die", "Was").
_SKIP = frozenset(
    "der die das den dem des ein eine einen einem einer eines und oder aber auch als wie von vom zu zur zum "
    "mit nach bei für über unter durch gegen ohne um an auf in im ist sind war waren hat haben wird werden "
    "dieser diese dieses jener jene jenes sein seine ihr ihre es er sie man nicht nur noch schon".split()
)


@dataclass(frozen=True)
class Mention:
    """One entity as it stands in the text, with where it was found."""

    text: str
    start: int
    end: int
    kind: str  # the model's label (PER, LOC, ORG, MISC); empty for a term from the archives
    source: str  # "ner" | "dictionary"


@lru_cache(maxsize=2)
def load_spacy(model: str) -> Any | None:
    """Load the pipeline once per process, by installed name or by path; nothing usable means: no NER."""
    if not model:
        return None
    try:
        import spacy  # optional extra "entities"; the service runs without it

        return spacy.load(model)
    except Exception as exc:  # a missing model or a missing spaCy must not take the endpoint down
        log.error("spaCy model %r not usable: %s", model, exc)
        return None


def mentions_from_ner(nlp: Callable[[str], Any], text: str) -> list[Mention]:
    """The named entities the model finds, in reading order."""
    return [
        Mention(text=ent.text, start=ent.start_char, end=ent.end_char, kind=ent.label_, source="ner")
        for ent in nlp(text).ents
    ]


def _candidates(text: str) -> Iterable[tuple[str, int, int]]:
    """Every run of up to ``MAX_TERM_WORDS`` words that may name an article, longest first per position."""
    words = [(match.group(), match.start(), match.end()) for match in _WORD.finditer(text)]
    for index, (word, start, _) in enumerate(words):
        if word.lower() in _SKIP or not word[0].isupper():
            continue
        for length in range(min(MAX_TERM_WORDS, len(words) - index), 0, -1):
            end = words[index + length - 1][2]
            yield text[start:end], start, end


def mentions_from_titles(archives: Sequence[Any], text: str) -> list[Mention]:
    """Terms of the text that name an article in one of the archives; the longest match at a position wins."""
    found: list[Mention] = []
    taken_until = 0
    for candidate, start, end in _candidates(text):
        if start < taken_until:
            continue
        if any(archive.has(candidate) for archive in archives):
            found.append(Mention(text=candidate, start=start, end=end, kind="", source="dictionary"))
            taken_until = end
    return found


def merge(mentions: Iterable[Mention]) -> list[Mention]:
    """Overlapping mentions reduced to one: the longer wins, and on equal length the one that knows its kind."""
    ordered = sorted(mentions, key=lambda m: (m.start, -(m.end - m.start), not m.kind))
    kept: list[Mention] = []
    for mention in ordered:
        if kept and mention.start < kept[-1].end:
            continue
        kept.append(mention)
    return kept
