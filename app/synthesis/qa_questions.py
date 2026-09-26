"""Questions from one parsed German main clause - the transformations of the rule stage of /qa (D55).

A question word can take the place of the front field as it stands, or of a constituent behind the verb when the
subject leads - the subject then moves behind the verb (app/synthesis/qa_clause.py reads the clause):

    "Einstein veröffentlichte 1905 vier Arbeiten."  ->  "Wann veröffentlichte Einstein vier Arbeiten?"

The parse of de_core_news_md decides which constituent asks which question: a time phrase "Wann", a place "Wo",
the agent of a passive "Von wem", a prepositional object "Worauf", "Wovon" and the like, an accusative object
"Was" or "Wen", a counted noun "Wie viele", a weil-clause "Warum", and the subject itself "Wer" or "Was". The
old templates (app/synthesis/qa.py) knew four sentence openings and asked "Was geschah im Jahr …?" of every other
sentence with a year in it; on the measured compendium texts nearly all their pairs were such year questions.

Every guard stands for a wrong question the prototype asked on real compendium texts on 2026-09-25: a word that
points back to a sentence the question does not show ("diese Form", "dabei", "seine"), an object that reads as the
subject once the subject is "Was", a year the parse left outside its phrase, a verb particle cut off with the rest
of a clause. The answer is not built here: the rule stage answers with the sentence the question came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.synthesis.qa_clause import Clause, contiguous, is_person, lowered, place_word, span, subtree, time_word
from app.synthesis.qa_words import (
    AMOUNT_VERBS,
    ARTICLES,
    CAUSES,
    GOVERNED,
    MEASURING_VERBS,
    NAMING_HEADS,
    NO_OBJECT_VERBS,
    NOUNS,
    WO_PREPOSITIONS,
    YEAR,
    unclear,
    words,
)

MAX_QUESTION_CHARS = 170
MAX_SUBJECT_TOKENS = 10  # a longer subject makes "Wer …?" or "Was …?" a question about a whole clause


@dataclass(frozen=True)
class Question:
    kind: str  # what it asks for; the rule stage takes turns over the kinds
    text: str


def clause_questions(doc: Any, *, topic: str = "", person: str = "") -> list[Question]:
    """The questions the main clause of a parsed sentence yields; an empty list when it yields none.

    ``topic`` keeps the topic itself from becoming an answer - every pair of a quiz on it would be answered by
    its name. ``person`` is the name a subject "er" or "sie" stands for, when the topic is a person: on a
    biography, "er" is nearly always the person the compendium is about.
    """
    clause = Clause.of(doc)
    if clause is None:
        return []
    asker = _Asker(clause, words(topic), person)
    asker.constituents()
    asker.counted()
    asker.cause()
    asker.subject()
    return asker.questions


def _question_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip().rstrip(" .,;:")
    return re.sub(r"\s+([,.;:!?])", r"\1", text) + "?"


def _balanced(text: str) -> bool:
    return (
        text.count("(") == text.count(")") and text.count("[") == text.count("]") and text.count("„") == text.count("“")
    )


def _names_an_amount(verb: str, noun: Any) -> bool:
    """Whether the object of ``verb`` is an amount that "Was" would ask for as a thing: always behind "dauern" or
    "kosten" (M30, D60), behind "messen", "wiegen" or "zählen" only with a number in it (review of D60)."""
    if verb in MEASURING_VERBS:
        return any(token.pos_ == "NUM" for token in noun.subtree)
    return verb in AMOUNT_VERBS


class _Asker:
    """Collects the questions of one clause; ``_ask`` applies the checks every question has to pass."""

    def __init__(self, clause: Clause, topic_words: set[str], person: str) -> None:
        self.clause, self.doc, self.topic_words = clause, clause.doc, topic_words
        subject = clause.subject
        self.pronoun = (
            subject.text
            if person and subject is not None and subject.lower_ in {"er", "sie"} and len(clause.subject_ids) == 1
            and "Sing" in subject.morph.get("Number")
            else ""
        )  # fmt: skip
        self.person = person
        self.questions: list[Question] = []

    def _ask(self, kind: str, text: str, focus: str = "") -> None:
        if self.pronoun:
            text = re.sub(rf"\b{re.escape(self.pronoun)}\b", self.person, text, count=1, flags=re.IGNORECASE)
        question = _question_text(text)
        if (
            len(question) <= MAX_QUESTION_CHARS
            and _balanced(question)
            and not unclear(question)
            and not unclear(focus)
            and self._about_something(question)
        ):
            self.questions.append(Question(kind, question))

    def _about_something(self, question: str) -> bool:
        """Whether a noun, a name or a number of the sentence stands in the question, or the person's name.

        "Was ist notwendig?" or "Was lautet?" asks about nothing the reader can see (M30, D60).
        """
        asked = words(question)
        return bool(self.pronoun) or any(
            words(token.text) & asked for token in self.doc if token.pos_ in NOUNS or token.pos_ == "NUM"
        )

    def _moved(self, question_word: str, removed: set[int]) -> str | None:
        """The question with ``removed`` in the front field, or taken out of the middle while the subject leads."""
        clause, doc = self.clause, self.doc
        if removed == clause.front:
            return f"{question_word} {span(doc, range(clause.verb, clause.end))}"
        if not clause.subject_first or any(doc[i].text == "," for i in range(clause.verb + 1, min(removed))):
            return None
        rest = set(range(clause.verb + 1, clause.end)) - removed
        reflexive = next((doc[i] for i in sorted(rest)[:1] if doc[i].tag_ == "PRF"), None)
        verb = clause.root.text if reflexive is None else f"{clause.root.text} {reflexive.text}"
        rest -= {reflexive.i} if reflexive is not None else set()
        subject = lowered(span(doc, clause.subject_ids), doc[min(clause.subject_ids)])
        return f"{question_word} {verb} {subject} {span(doc, rest)}"

    def _within(self, child: Any) -> set[int]:
        """The part of a constituent inside the clause: a list behind a colon hangs on its object as apposition."""
        return {index for index in subtree(child) if index < self.clause.end}

    def constituents(self) -> None:
        """Time, place, agent, prepositional and accusative objects of the verbs."""
        clause = self.clause
        for verb in clause.verbs:
            for child in verb.children:
                ids = self._within(child)
                if not ids or not contiguous(ids):
                    continue
                found = self._constituent(child, ids)
                if found is None:
                    continue
                question_word, kind, focus = found
                text = self._moved(question_word, ids)
                if text is not None:
                    self._ask(kind, text, focus)

    def _constituent(self, child: Any, ids: set[int]) -> tuple[str, str, str] | None:
        clause, doc = self.clause, self.doc
        if child.dep_ == "mo":
            when = time_word(doc, ids)
            if when is not None:
                return when, "Wann", ""
            where = place_word(doc, ids, clause.lemmas)
            if where is not None:
                return where, "Wo", ""
            return self._prepositional(child, ids, governed_only=True)
        if child.dep_ == "op":
            return self._prepositional(child, ids, governed_only=False)
        if child.dep_ == "sbp":
            agent = next((c for c in child.children if c.dep_ == "nk" and c.pos_ in NOUNS), None)
            if child.lower_ == "von" and agent is not None and agent.pos_ == "PROPN":
                return "Von wem", "Von wem", span(doc, ids)
            return None
        if (
            child.dep_ == "oa"
            and child.pos_ in NOUNS
            and clause.lexical not in NO_OBJECT_VERBS
            and not _names_an_amount(clause.lexical, child)
            and not clause.joined()
        ):
            focus = span(doc, ids)
            if words(focus) <= self.topic_words | ARTICLES:
                return None
            return ("Wen" if is_person(doc, child) else "Was"), "Objekt", focus
        return None

    def _prepositional(self, child: Any, ids: set[int], *, governed_only: bool) -> tuple[str, str, str] | None:
        noun = next((c for c in child.children if c.dep_ == "nk" and c.pos_ in NOUNS), None)
        preposition = child.lower_
        if child.pos_ != "ADP" or preposition not in WO_PREPOSITIONS or noun is None or noun.pos_ == "PROPN":
            return None  # a person or a name would ask "von wem", "mit wem" - not built
        if self.clause.lemmas & AMOUNT_VERBS:
            return None  # "beziffert sich auf …" names an amount: "Worauf" would ask for it as a thing
        if governed_only and not any((lemma, preposition) in GOVERNED for lemma in self.clause.lemmas):
            return None
        return WO_PREPOSITIONS[preposition], "Wo+Präposition", span(self.doc, ids)

    def counted(self) -> None:
        """ "vier Arbeiten" in the object or the leading subject asks "Wie viele Arbeiten …?"."""
        clause, doc = self.clause, self.doc
        for verb in clause.verbs:
            for child in verb.children:
                if child.dep_ not in {"oa", "sb"} or child.pos_ != "NOUN" or "Plur" not in child.morph.get("Number"):
                    continue
                number = next((c for c in child.children if c.pos_ == "NUM" and not YEAR.match(c.text)), None)
                ids = self._within(child)
                if number is None or not ids or number.i != min(ids) or not contiguous(ids):
                    continue
                counted = span(doc, ids - {number.i})
                if child.dep_ == "sb" and ids == clause.front:
                    self._ask("Wie viele", f"Wie viele {counted} {span(doc, range(clause.verb, clause.end))}")
                elif child.dep_ == "oa" and not clause.joined():
                    text = self._moved(f"Wie viele {counted}", ids)
                    if text is not None:
                        self._ask("Wie viele", text)

    def cause(self) -> None:
        """A weil- or da-clause behind the main clause asks "Warum" about the main clause."""
        clause, doc = self.clause, self.doc
        marker = next((t for t in doc if t.i > clause.verb and t.lower_ in CAUSES and t.dep_ == "cp"), None)
        subject = clause.subject
        if marker is None or subject is None or doc[marker.i - 1].text != ",":
            return
        comma = marker.i - 1
        if comma <= clause.verb or any(doc[i].text == "," for i in range(clause.verb + 1, comma)):
            return
        if clause.subject_first:
            moved = lowered(span(doc, clause.subject_ids), doc[min(clause.subject_ids)])
            self._ask("Warum", f"Warum {clause.root.text} {moved} {span(doc, range(clause.verb + 1, comma))}")
        elif min(clause.subject_ids) == clause.verb + 1 and (subject.pos_ in NOUNS or self.pronoun):
            front = lowered(span(doc, clause.front), doc[0])
            after = range(max(clause.subject_ids) + 1, comma)
            self._ask("Warum", f"Warum {clause.root.text} {span(doc, clause.subject_ids)} {front} {span(doc, after)}")

    def subject(self) -> None:
        """The subject itself: "Wer" for a person, "Was" for a thing, in front or right behind the verb."""
        clause, doc = self.clause, self.doc
        subject = clause.subject
        if subject is None or subject.pos_ not in NOUNS or not clause.singular:
            return  # "Was gelten …?" - a plural verb has no singular question word
        if len(clause.subject_ids) > MAX_SUBJECT_TOKENS or subject.lower_ in NAMING_HEADS:
            return
        text = span(doc, clause.subject_ids)
        if subject.lower_ in self.topic_words or subject.lemma_.lower() in self.topic_words:
            return  # the topic of the quiz is no answer
        if words(text) <= self.topic_words | ARTICLES:
            return
        person = is_person(doc, subject)
        if not person and clause.ambiguous_object():
            return
        word = "Wer" if person else "Was"
        if clause.subject_first:
            self._ask(word, f"{word} {span(doc, range(clause.verb, clause.end))}", text)
        elif min(clause.subject_ids) == clause.verb + 1 and not any(doc[i].text == "," for i in clause.front):
            rest = span(doc, range(max(clause.subject_ids) + 1, clause.end))
            if rest:
                front = lowered(span(doc, clause.front), doc[0])
                self._ask(word, f"{word} {clause.root.text} {front} {rest}", text)
