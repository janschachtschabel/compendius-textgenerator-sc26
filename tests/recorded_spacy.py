"""spaCy parses recorded in the image and replayed without spaCy, for the rule stage of /qa (D55).

The rule stage reads the dependency parse of de_core_news_md: word classes, dependency labels, heads,
morphology and named entities. The model lives in the image, not in the test environment, so the parses of the
test inputs were recorded there once (tests/fixtures/qa_rule_parses.json, 2026-09-25) and are replayed here.
What the tests pin is how the rules read a real parse; whether the parse itself is right is the model's business.

Only what the rules touch is rebuilt: a token's text, whitespace, word class, tag, dependency label, head,
lemma, morphology, children and subtree, and the entities of a document. An input that was not recorded is a
KeyError, so a new test input has to be recorded first rather than silently parsed as something else.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

RECORDING = Path(__file__).parent / "fixtures" / "qa_rule_parses.json"


class RecordedMorph:
    def __init__(self, features: str) -> None:
        self._features = dict(pair.split("=", 1) for pair in features.split("|") if "=" in pair)

    def get(self, key: str) -> list[str]:
        value = self._features.get(key)
        return value.split(",") if value else []


class RecordedToken:
    def __init__(self, doc: RecordedDoc, index: int, fields: list[Any]) -> None:
        text, whitespace, pos, tag, dep, head, lemma, morph = fields
        self.doc, self.i, self.text, self.whitespace_ = doc, index, text, whitespace
        self.pos_, self.tag_, self.dep_, self.lemma_ = pos, tag, dep, lemma
        self.head_index = head
        self.morph = RecordedMorph(morph)

    @property
    def text_with_ws(self) -> str:
        return self.text + self.whitespace_

    @property
    def lower_(self) -> str:
        return self.text.lower()

    @property
    def head(self) -> RecordedToken:
        return self.doc[self.head_index]

    @property
    def children(self) -> list[RecordedToken]:
        return [token for token in self.doc if token.head_index == self.i and token.i != self.i]

    @property
    def subtree(self) -> list[RecordedToken]:
        found = {self.i}
        frontier = [self]
        while frontier:
            for child in frontier.pop().children:
                if child.i not in found:
                    found.add(child.i)
                    frontier.append(child)
        return [self.doc[index] for index in sorted(found)]


class RecordedSpan:
    def __init__(self, doc: RecordedDoc, start: int, end: int, label: str) -> None:
        self.start, self.end, self.label_ = start, end, label
        self.text = "".join(doc[index].text_with_ws for index in range(start, end)).strip()


class RecordedDoc:
    def __init__(self, parse: dict[str, Any]) -> None:
        self.tokens = [RecordedToken(self, index, fields) for index, fields in enumerate(parse["tokens"])]
        self.ents = [RecordedSpan(self, start, end, label) for start, end, label in parse["ents"]]

    def __iter__(self) -> Iterator[RecordedToken]:
        return iter(self.tokens)

    def __len__(self) -> int:
        return len(self.tokens)

    def __getitem__(self, index: int) -> RecordedToken:
        return self.tokens[index]


class RecordedNlp:
    """``nlp(text)`` and ``nlp.pipe(texts)`` as spaCy offers them, answered from the recording."""

    def __init__(self, parses: dict[str, Any] | None = None) -> None:
        self.parses = parses if parses is not None else recorded_parses()

    def __call__(self, text: str) -> RecordedDoc:
        return RecordedDoc(self.parses[text])

    def pipe(self, texts: Iterable[str]) -> Iterator[RecordedDoc]:
        for text in texts:
            yield self(text)


@lru_cache(maxsize=1)
def recorded_parses() -> dict[str, Any]:
    parses: dict[str, Any] = json.loads(RECORDING.read_text(encoding="utf-8"))["parses"]
    return parses
