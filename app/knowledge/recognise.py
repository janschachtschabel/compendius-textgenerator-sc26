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
# A genitive ending hides the title ("des Wassers", "Abraham Lincolns"; M18). After one of these words, one word
# in between allowed, a noun ending in s or es is most likely a genitive, and its base form names the article.
_GENITIVE_ARTICLES = frozenset("des eines dieses jenes jedes keines meines deines seines ihres unseres eures".split())
_GENITIVE_ENDINGS = ("es", "s")  # "es" first: Reiches is the genitive of Reich, not of Reiche
MIN_BASE_CHARS = 3  # "Os" is no genitive of "O"
_SENTENCE_MARKS = ".!?:\n"  # a sentence or a line ends before the next word
# Adverbs in -s, capitalised when they open a sentence: read as a genitive, "Bereits Thales" named the person
# Johann Bereit (M20 draft). Some are genitives of nouns too ("des Falls"), so only the reading without an
# article is barred.
_ADVERBS_IN_S = frozenset(
    "bereits stets damals nachts morgens abends mittags anfangs meistens mindestens höchstens wenigstens "
    "spätestens frühestens rechts links anders teils falls jedenfalls ebenfalls allerdings übrigens erstens "
    "zweitens drittens daraus hieraus woraus heraus hinaus voraus durchaus jenseits diesseits abseits".split()
)


@dataclass(frozen=True)
class Mention:
    """One entity as it stands in the text, with where it was found."""

    text: str
    start: int
    end: int
    kind: str  # the model's label (PER, LOC, ORG, MISC); empty for a term from the archives
    source: str  # "ner" | "dictionary"
    title: str | None = None  # the article's title where it differs from the text: the base of a genitive


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


def _genitive_bases(text: str) -> list[str]:
    """The text without a genitive ending on its last word, "es" first: Reiches -> Reich, Wassers -> Wasser."""
    return [
        text[: -len(ending)]
        for ending in _GENITIVE_ENDINGS
        if text.endswith(ending) and len(text) - len(ending) >= MIN_BASE_CHARS
    ]


def title_candidates(text: str, *, after_genitive_article: bool = False, may_be_genitive: bool = True) -> list[str]:
    """The titles a mention may name, in the order to try them.

    The text itself, then its genitive bases ("Abraham Lincolns" -> Abraham Lincoln). After a genitive article
    the bases come first: "des Wassers" means the water, not the village Wassers. ``may_be_genitive`` false keeps
    to the text: one word opening a sentence before a small word is an adverb, not a genitive ("Daraus folgt").
    """
    bases = _genitive_bases(text)
    if after_genitive_article:
        return [*bases, text]
    return [text, *bases] if may_be_genitive else [text]


def _candidates(text: str) -> Iterable[tuple[str, int, int, bool, bool]]:
    """Every run of up to ``MAX_TERM_WORDS`` words that may name an article, longest first per position.

    Two flags for the genitive: whether a genitive article stands before the run, one word in between allowed
    ("des kalten"), and whether the run may be a genitive without one - not an adverb in -s, and not one word that
    opens a sentence before a small word ("Daraus folgt").
    """
    words = [(match.group(), match.start(), match.end()) for match in _WORD.finditer(text)]
    for index, (word, start, _) in enumerate(words):
        if word.lower() in _SKIP or not word[0].isupper():
            continue
        after_article = any(before.lower() in _GENITIVE_ARTICLES for before, _, _ in words[max(0, index - 2) : index])
        opens_sentence = index == 0 or any(mark in text[words[index - 1][2] : start] for mark in _SENTENCE_MARKS)
        for length in range(min(MAX_TERM_WORDS, len(words) - index), 0, -1):
            end = words[index + length - 1][2]
            following = words[index + length][0] if index + length < len(words) else ""
            may_be_genitive = length > 1 or (
                word.lower() not in _ADVERBS_IN_S and (not opens_sentence or following[:1].isupper())
            )
            yield text[start:end], start, end, after_article, may_be_genitive


def mentions_from_titles(archives: Sequence[Any], text: str) -> list[Mention]:
    """Terms of the text that name an article in one of the archives; the longest match at a position wins."""
    found: list[Mention] = []
    taken_until = 0
    for candidate, start, end, after_article, may_be_genitive in _candidates(text):
        if start < taken_until:
            continue
        titles = title_candidates(candidate, after_genitive_article=after_article, may_be_genitive=may_be_genitive)
        title = next((title for title in titles if any(archive.has(title) for archive in archives)), None)
        if title is not None:
            named = None if title == candidate else title
            found.append(Mention(text=candidate, start=start, end=end, kind="", source="dictionary", title=named))
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
