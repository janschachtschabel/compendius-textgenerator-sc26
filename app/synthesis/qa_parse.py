"""Questions from the dependency parse: the sentence subject swapped for a question word.

The template stage (app/synthesis/qa.py) matches four fixed sentence openings and, measured over 172
sentences of four real compendium texts on 2026-09-22, catches 8 of them - the rest is carried by a
catch-all that asks "Was geschah im Jahr …?" about any sentence with a year in it. That is where its
thinness comes from, not from its speed.

This stage uses what the spaCy model computes anyway. A German declarative sentence puts its subject
first and its finite verb second, so replacing the subject with "Wer" or "Was" and keeping the rest
verbatim leaves grammatical German, and the answer is the subject itself rather than the whole sentence:

    "Christiaan Huygens bemerkte um 1650, dass Licht sich wie eine Welle ausbreitet."
    -> "Wer bemerkte um 1650, dass Licht sich wie eine Welle ausbreitet?" / "Christiaan Huygens"

Measured on the same 172 sentences: 33 of them (19 percent against 5) yield a question this way, at
about 4 ms per sentence with ``nlp.pipe`` once spaCy is warm, and 26 of the 33 were free of a
checkable defect. That is four times the yield of the templates and well short of the two small
models (30 of 32), which is why this is a third option and not a replacement - see docs/umbau.md.

Named entities alone were tried first and do not carry: on the same texts spaCy labelled a plural
course name as a person and a plain sentence of physics prose as an organisation, and MISC - which says
nothing about what a thing is - was the largest bucket of all in the historical text. The parse decides
here; the entity only chooses between "Wer" and "Was".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.knowledge.segmentation import split_sentences
from app.synthesis.qa import MIN_SENTENCE_CHARS, QaPair, cut

MAX_SUBJECT_CHARS = 70  # a longer one makes the question unreadable before it makes it wrong
MAX_QUESTION_CHARS = 160
_ROOT = "ROOT"
_SUBJECT = "sb"
_VERBS = frozenset({"VERB", "AUX"})
_NOUNS = frozenset({"NOUN", "PROPN"})
# An apposition outside the subject's subtree leaves the comma behind: "Was , wird konstruiert?"
_BAD_REMAINDER_START = ",;:)]"
_BRACKETS = (("(", ")"), ("[", "]"))


@dataclass(frozen=True)
class Subject:
    """What the parse found at the head of a sentence, and the two facts the rules need about it.

    Keeping this between the parse and the rules is what lets every guard in ``question_from`` be tested
    without spaCy: the rules never see a token, only what was found.
    """

    text: str  # the subject phrase, verbatim from the sentence
    end_char: int  # where it ends inside that sentence
    is_person: bool  # decides between "Wer" and "Was"
    verb_is_singular: bool


def subject_of(doc: Any) -> Subject | None:
    """The subject of the sentence's finite verb, when it leads the sentence and names a thing.

    A subject that does not lead cannot be swapped: German puts the finite verb second, so replacing a
    later subject would leave the verb in first position and the sentence as a question of another kind.
    A pronoun is rejected because it would become the answer - measured on real text, 12 of 172 sentences
    would have answered "Sie", and spaCy carries no coreference that could resolve it.
    """
    root = next((token for token in doc if token.dep_ == _ROOT), None)
    if root is None or root.pos_ not in _VERBS:
        return None
    head = next((child for child in root.children if child.dep_ == _SUBJECT), None)
    if head is None or head.pos_ not in _NOUNS:
        return None
    indices = [token.i for token in head.subtree]
    span = doc[min(indices) : max(indices) + 1]
    if span.start_char != 0:
        return None
    return Subject(
        text=span.text,
        end_char=span.end_char,
        # Only at the head: a person anywhere in the subject repaired two wrong questions on the measured
        # texts and broke two others, so it buys nothing (docs/umbau.md).
        is_person=head.pos_ == "PROPN"
        and any(entity.label_ == "PER" and entity.start <= head.i < entity.end for entity in doc.ents),
        verb_is_singular="Sing" in root.morph.get("Number"),
    )


def question_from(sentence: str, subject: Subject) -> str | None:
    """The sentence with its subject replaced by a question word, or ``None`` when a guard refuses.

    Every guard here stands for a wrong question a measurement produced, not for a case that was imagined:
    a plural verb ("Was gelten …?", 15 of 172 sentences), a subject the parse cut mid-bracket
    ("Wer ˈabə] (* 23. Januar 1840 …?"), and an apposition that left its comma behind.
    """
    if len(subject.text) > MAX_SUBJECT_CHARS or not subject.verb_is_singular:
        return None
    if any(subject.text.count(opened) != subject.text.count(closed) for opened, closed in _BRACKETS):
        return None
    remainder = sentence[subject.end_char :].strip().rstrip(" .")
    if not remainder or remainder[0] in _BAD_REMAINDER_START:
        return None
    question = f"{'Wer' if subject.is_person else 'Was'} {remainder}?"
    return question if len(question) <= MAX_QUESTION_CHARS else None


def parse_based_pairs(
    text: str,
    *,
    limit: int,
    max_answer_length: int,
    level_property: str | None = None,
    nlp: Any,
) -> list[QaPair]:
    """One pair per sentence whose subject can be swapped, up to ``limit``.

    ``nlp.pipe`` parses the sentences in batches rather than one call each; measured on 2026-09-22 that
    is under 4 ms per sentence against 12.5 ms one at a time, the same lesson the model stage learned.
    The first text of a process pays for warming spaCy up - 18 ms per sentence, once. The
    loop stops at ``limit``, and because ``pipe`` yields lazily the sentences behind it are never parsed.
    """
    sentences = [s for s in split_sentences(" ".join(text.split())) if len(s) >= MIN_SENTENCE_CHARS]
    pairs: list[QaPair] = []
    asked: set[str] = set()
    for sentence, doc in zip(sentences, nlp.pipe(sentences), strict=True):
        if len(pairs) >= limit:
            break
        found = subject_of(doc)
        if found is None:
            continue
        question = question_from(sentence, found)
        if question is None or question in asked:
            continue
        asked.add(question)
        pairs.append(
            QaPair(question=question, answer=cut(found.text, max_answer_length), level_property=level_property)
        )
    return pairs
