"""The main clause of a parsed sentence and what its phrases name - what the /qa rule stage reads of a parse (D55).

A German declarative main clause puts one constituent before the finite verb (the front field), the rest behind
it, and the non-finite verbs and verb particles at its end. ``Clause.of`` finds that clause in the parse of
de_core_news_md - where it ends, which verbs complete it, which subject it has - or refuses a sentence whose parse
it cannot trust: reported speech, a second root inside the clause, a verb particle cut off by a dash. The phrase
readers say whether a phrase names a time or a place. What questions come of it is app/synthesis/qa_questions.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.synthesis.qa_words import (
    ABSTRACT_HEADS,
    ACCUSATIVE,
    CATAPHORA,
    CLAUSE_ENDERS,
    CLAUSE_OPENERS,
    LOCATION_PREPOSITIONS,
    LOCATION_VERBS,
    NOUNS,
    PLACE_PREPOSITIONS,
    SINCE_UNTIL,
    TIME_NOUNS,
    TIME_PREPOSITIONS,
    VERBS,
    YEAR,
)


@dataclass
class Clause:
    """The main clause of a parsed sentence: its finite verb, front field, end and subject."""

    doc: Any
    root: Any
    front: set[int]
    end: int
    verbs: list[Any]  # the finite verb and the non-finite verbs that complete it
    subject: Any | None
    subject_ids: set[int]

    @classmethod
    def of(cls, doc: Any) -> Clause | None:
        root = next((token for token in doc if token.dep_ == "ROOT"), None)
        if root is None or root.pos_ not in VERBS or "Fin" not in root.morph.get("VerbForm") or root.i == 0:
            return None  # no verb-second clause: a fragment, a list line, a heading
        if "Sub" in root.morph.get("Mood"):
            return None  # reported speech: "Die Wirkung sei so nicht möglich" is somebody's claim, no fact to ask
        end, cut_at_colon = _clause_end(doc, root.i)
        if cut_at_colon and any(doc[i].lower_ in CATAPHORA for i in range(end)):
            return None  # "so rekonstruiert:" - what the clause says stands behind the colon
        if any(token.dep_ == "ROOT" and token.i != root.i and token.i < end for token in doc):
            return None  # two roots in one clause: the parse split the sentence where it has no seam
        verbs = _verb_complex(root)
        bracket = [verb.i for verb in verbs[1:]] + [c.i for verb in verbs for c in verb.children if c.dep_ == "svp"]
        if bracket and max(bracket) >= end:
            return None  # the end cut off the verb's particle: "Am 1. März fand … – Eine Zeitreise statt"
        subject = next((child for child in root.children if child.dep_ == "sb"), None)
        subject_ids = subtree(subject) if subject is not None else set()
        if subject is not None and not contiguous(subject_ids):
            subject, subject_ids = None, set()
        return cls(doc, root, set(range(root.i)), end, verbs, subject, subject_ids)

    @property
    def verb(self) -> int:
        return int(self.root.i)

    @property
    def subject_first(self) -> bool:
        return self.subject is not None and self.subject_ids == self.front

    @property
    def singular(self) -> bool:
        return "Sing" in self.root.morph.get("Number")

    @property
    def lemmas(self) -> set[str]:
        """The verbs' lemmas, a separated particle in front: "leitet … ab" is "ableiten"."""
        found = set()
        for verb in self.verbs:
            particle = next((c.lower_ for c in verb.children if c.dep_ == "svp"), "")
            found.add(particle + verb.lemma_.lower())
        return found

    @property
    def lexical(self) -> str:
        """The lemma of the verb that carries the meaning: "veröffentlichen" in "hat … veröffentlicht"."""
        return str(self.verbs[-1].lemma_).lower()

    def ambiguous_object(self) -> bool:
        """An accusative noun that could be read as the subject once the subject is "Was"."""
        return any(
            child.dep_ == "oa" and child.pos_ in NOUNS and not any(d.lower_ in ACCUSATIVE for d in child.children)
            for verb in self.verbs
            for child in verb.children
        )

    def joined(self) -> bool:
        """Two verbs joined by "und": removing an object of one leaves the other without its own."""
        return any(child.dep_ in {"cd", "cj"} for child in self.root.children)


def _clause_end(doc: Any, verb: int) -> tuple[int, bool]:
    """Where the main clause ends, and whether a colon ends it."""
    for token in doc:
        if token.i <= verb:
            continue
        if token.text in {";", ":", "–", "—"}:
            return token.i, token.text == ":"
        if token.text == "," and token.i + 1 < len(doc) and doc[token.i + 1].lower_ in CLAUSE_ENDERS:
            return token.i, False
        if token.text == "," and _second_main_clause(doc, token.i, verb):
            return token.i, False
        if token.dep_ == "cd" and token.head.i == verb and _joins_a_finite_verb(token):
            return token.i, False  # "… leitete die Firma und war an … beteiligt": a second statement (M30, D60)
    return len(doc), False


def _joins_a_finite_verb(conjunction: Any) -> bool:
    """Whether "und" or "oder" joins a second finite verb to the clause's own - a second statement, not a list."""
    return any(child.dep_ == "cj" and "Fin" in child.morph.get("VerbForm") for child in conjunction.children)


def _second_main_clause(doc: Any, comma: int, verb: int) -> bool:
    """Whether the comma opens a clause of its own: its finite verb has no "dass", "ob" or relative pronoun.

    ", in Deutschland sei das Recht stabil" is one - the question must end before it -, ", dass Licht sich …
    ausbreitet" and ", die die Physik veränderte" belong to the clause they stand in.
    """
    for index in range(comma + 1, len(doc)):
        token = doc[index]
        if token.text == ",":
            return False  # the next comma comes first: what stands between is an insertion
        if index != verb and "Fin" in token.morph.get("VerbForm"):
            return not any(child.dep_ == "cp" or child.tag_ in CLAUSE_OPENERS for child in token.children)
    return False


def _verb_complex(root: Any) -> list[Any]:
    """The finite verb and the participles and infinitives an auxiliary takes into its clause.

    Not the finite verb of a dass-clause, not a zu-infinitive, and not the participle of a full verb
    ("findet sich bezogen auf …"): their objects belong to another clause or to no verb at all.
    """
    verbs, frontier = [root], [root]
    while frontier:
        parent = frontier.pop()
        if parent.pos_ != "AUX":
            continue
        for child in parent.children:
            non_finite = "Fin" not in child.morph.get("VerbForm")
            if (
                child.dep_ == "oc"
                and child.pos_ in VERBS
                and non_finite
                and not any(g.dep_ == "pm" for g in child.children)
            ):
                verbs.append(child)
                frontier.append(child)
    return verbs


def span(doc: Any, indices: set[int] | range) -> str:
    """The text of the tokens, in their order and with their own spacing."""
    text = "".join(doc[index].text_with_ws for index in sorted(indices)).strip()
    return re.sub(r"\s+([,.;:!?“])", r"\1", text)


def subtree(token: Any) -> set[int]:
    return {child.i for child in token.subtree}


def contiguous(indices: set[int]) -> bool:
    return max(indices) - min(indices) + 1 == len(indices)


def lowered(text: str, first: Any) -> str:
    """A phrase moved behind the verb: "Die Nutzung" becomes "die Nutzung", a noun keeps its capital."""
    return text if first.pos_ in NOUNS else text[:1].lower() + text[1:]


def is_person(doc: Any, head: Any) -> bool:
    """A person entity at the head, or right behind it in apposition ("der Franzose Hippolyte Pixii")."""
    return any(e.label_ == "PER" and (e.start <= head.i < e.end or e.start == head.i + 1) for e in doc.ents)


def _phrase_head(doc: Any, ids: set[int]) -> tuple[Any, Any | None]:
    """The preposition that opens a phrase and the noun or number it governs."""
    first = doc[min(ids)]
    if first.pos_ != "ADP":
        return first, None
    return first, next((c for c in first.children if c.dep_ == "nk" and (c.pos_ in NOUNS or c.pos_ == "NUM")), None)


def time_word(doc: Any, ids: set[int]) -> str | None:
    """ "Wann", "Seit wann" or "Bis wann" for a phrase that names a time - "im Jahr 1922", "um 1650", "1905"."""
    first, head = _phrase_head(doc, ids)
    if first.pos_ == "NUM":
        return "Wann" if len(ids) == 1 and YEAR.match(first.text) else None
    if first.lower_ not in TIME_PREPOSITIONS or head is None:
        return None
    word = SINCE_UNTIL.get(first.lower_, "Wann")
    if head.pos_ == "NUM":
        return word if YEAR.match(head.text) else None
    if head.lower_ not in TIME_NOUNS:
        return None
    inside = [doc[index] for index in ids]
    if head.lower_.startswith("jahr") and not any(token.pos_ == "NUM" for token in inside):
        return None  # "im Jahr" without its number: the parse put the year elsewhere
    if head.lower_ in {"zeit", "zeiten"} and not any(t.pos_ in {"PROPN", "NUM"} or t.dep_ == "ag" for t in inside):
        return None  # "im Laufe der Zeit", "zu dieser Zeit" name no time
    return word


def place_word(doc: Any, ids: set[int], lemmas: set[str]) -> str | None:
    """ "Wo" or "Woher" for a phrase that names a place entity, or any place where the verb says where."""
    first, head = _phrase_head(doc, ids)
    if head is None or head.pos_ == "NUM" or head.lower_ in TIME_NOUNS | ABSTRACT_HEADS:
        return None
    if first.lower_ in PLACE_PREPOSITIONS and any(e.label_ == "LOC" and e.start <= head.i < e.end for e in doc.ents):
        return PLACE_PREPOSITIONS[first.lower_]
    if first.lower_ in LOCATION_PREPOSITIONS and lemmas & LOCATION_VERBS:
        return "Wo"
    return None
