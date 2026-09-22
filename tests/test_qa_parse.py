"""The parse stage of POST /api/v2/qa: the sentence subject swapped for a question word.

The rules live in ``question_from``, which sees no spaCy at all - it is handed what the parse found and
decides. That keeps every guard below testable without a gigabyte of weights, and it is where the guards
earn their place: each one of them was written against a wrong question a measurement produced.
"""

from __future__ import annotations

from app.synthesis.qa_parse import Subject, parse_based_pairs, question_from, subject_of

SENTENCE = "Christiaan Huygens bemerkte um 1650, dass Licht sich wie eine Welle ausbreitet."


def subject(
    text: str = "Christiaan Huygens", *, person: bool = True, singular: bool = True, sentence: str = SENTENCE
) -> Subject:
    return Subject(text=text, end_char=sentence.index(text) + len(text), is_person=person, verb_is_singular=singular)


def test_a_person_subject_becomes_wer_and_the_rest_stays_as_it_stands() -> None:
    """The subject leads the sentence, so replacing it keeps the verb in second position - German stays German."""
    assert question_from(SENTENCE, subject()) == ("Wer bemerkte um 1650, dass Licht sich wie eine Welle ausbreitet?")


def test_a_thing_becomes_was() -> None:
    sentence = "Das snelliussche Brechungsgesetz beschreibt die Brechung des Lichtes."
    got = question_from(sentence, subject("Das snelliussche Brechungsgesetz", person=False, sentence=sentence))
    assert got == "Was beschreibt die Brechung des Lichtes?"


def test_a_plural_verb_asks_nothing() -> None:
    """ "Was gelten …?" is not German. Measured on real text: 15 of 172 sentences would have asked it."""
    sentence = "Viele Gesetzmäßigkeiten der Optik gelten auch außerhalb dieser Bereiche."
    assert (
        question_from(
            sentence, subject("Viele Gesetzmäßigkeiten der Optik", person=False, singular=False, sentence=sentence)
        )
        is None
    )


def test_a_plural_verb_asks_nothing_for_a_person_either() -> None:
    """The guard is not about the question word: "Wer dauern …?" came out of a mis-tagged plural subject."""
    sentence = "Prüfungsvorbereitungskurse an Meisterschulen dauern ungefähr ein Jahr."
    assert (
        question_from(
            sentence, subject("Prüfungsvorbereitungskurse an Meisterschulen", singular=False, sentence=sentence)
        )
        is None
    )


def test_an_unbalanced_bracket_in_the_subject_asks_nothing() -> None:
    """The parse cut "Ernst Karl Abbe [ˈabə] (* 23. Januar 1840 …" mid-bracket and asked the remainder."""
    sentence = "Ernst Karl Abbe [ˈabə] wurde 1840 in Eisenach geboren."
    assert question_from(sentence, subject("Ernst Karl Abbe [", sentence=sentence)) is None


def test_a_remainder_that_starts_with_a_comma_asks_nothing() -> None:
    """An apposition outside the subtree left "Was , wird durch Verfolgen des Strahlenverlaufs konstruiert?"."""
    sentence = "Der Weg des Lichtes, etwa durch ein Instrument, wird konstruiert."
    assert question_from(sentence, subject("Der Weg des Lichtes", person=False, sentence=sentence)) is None


def test_a_subject_longer_than_the_bound_asks_nothing() -> None:
    long_subject = "Der " + "sehr " * 20 + "lange Gegenstand"
    sentence = f"{long_subject} ist ein Beispiel."
    assert question_from(sentence, subject(long_subject, person=False, sentence=sentence)) is None


def test_a_question_longer_than_the_bound_asks_nothing() -> None:
    sentence = "Die Optik " + "beschreibt sehr viele verschiedene Erscheinungen des Lichtes " * 4 + "."
    assert question_from(sentence, subject("Die Optik", person=False, sentence=sentence)) is None


def test_a_sentence_with_nothing_behind_the_subject_asks_nothing() -> None:
    assert question_from("Die Optik.", subject("Die Optik", person=False, sentence="Die Optik.")) is None


class _Morph:
    def __init__(self, number: str) -> None:
        self._number = number

    def get(self, key: str) -> list[str]:
        return [self._number] if key == "Number" else []


class _Token:
    def __init__(self, text: str, index: int, idx: int, pos: str, dep: str, number: str) -> None:
        self.text, self.i, self.idx, self.pos_, self.dep_ = text, index, idx, pos, dep
        self.morph = _Morph(number)
        self.children: list[_Token] = []
        self.subtree: list[_Token] = [self]


class _Span:
    def __init__(self, tokens: list[_Token], sentence: str) -> None:
        self.start_char = tokens[0].idx
        self.end_char = tokens[-1].idx + len(tokens[-1].text)
        self.text = sentence[self.start_char : self.end_char]


class _Entity:
    def __init__(self, start: int, end: int) -> None:
        self.label_, self.start, self.end = "PER", start, end


class FakeDoc:
    """The pieces of a spaCy document ``subject_of`` touches: a parse, and the entities over it.

    The real parse is checked against real text in the measurement (docs/umbau.md); what is pinned here
    is that this code reads the parse the way it says it does.
    """

    def __init__(
        self,
        sentence: str,
        *,
        subject: str,
        head_pos: str = "PROPN",
        number: str = "Sing",
        person: bool = False,
        root_pos: str = "VERB",
    ) -> None:
        self.sentence = sentence
        self.tokens: list[_Token] = []
        for index, word in enumerate(sentence.split()):
            idx = sentence.index(word, self.tokens[-1].idx + 1 if self.tokens else 0)
            self.tokens.append(_Token(word, index, idx, "NOUN", "", number))
        begin = sentence.index(subject)
        covered = [t for t in self.tokens if begin <= t.idx < begin + len(subject)]
        head = covered[-1]
        head.pos_, head.dep_, head.subtree = head_pos, "sb", covered
        after = self.tokens[covered[-1].i + 1]
        after.pos_, after.dep_, after.children = root_pos, "ROOT", [head]
        self.ents = [_Entity(covered[0].i, covered[-1].i + 1)] if person else []

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.tokens)

    def __getitem__(self, item: slice) -> _Span:
        return _Span(self.tokens[item], self.sentence)


class FakeNlp:
    """A parse that makes the first two words the subject - enough to drive ``parse_based_pairs``."""

    def __init__(self, head_pos: str = "NOUN") -> None:
        self.head_pos = head_pos

    def pipe(self, sentences: list[str]):  # type: ignore[no-untyped-def]
        for sentence in sentences:
            subject = " ".join(sentence.split(" ")[:2])
            yield FakeDoc(sentence, subject=subject, head_pos=self.head_pos)


THING = "Das Brechungsgesetz beschreibt die Brechung des Lichtes an Grenzflächen."


def test_the_subject_is_the_whole_subtree_of_the_verbs_subject() -> None:
    found = subject_of(FakeDoc(SENTENCE, subject="Christiaan Huygens", person=True))
    assert found is not None
    assert found.text == "Christiaan Huygens" and found.end_char == 18
    assert found.is_person and found.verb_is_singular


def test_a_pronoun_subject_is_no_subject() -> None:
    """It would become the answer: "Was ist eine Wissenschaft?" answered with "Sie" teaches nothing."""
    assert subject_of(FakeDoc(THING, subject="Das", head_pos="PRON")) is None


def test_a_subject_that_does_not_lead_the_sentence_is_refused() -> None:
    """German puts the finite verb second; swapping a later subject would leave the verb in front."""
    assert subject_of(FakeDoc(THING, subject="die Brechung")) is None


def test_without_a_finite_verb_at_the_root_there_is_no_subject() -> None:
    assert subject_of(FakeDoc(THING, subject="Das Brechungsgesetz", root_pos="NOUN")) is None


def test_the_answer_is_the_subject_and_the_pairs_keep_reading_order() -> None:
    text = f"{THING} Die Optik beschreibt das Verhalten des Lichtes im Raum."
    pairs = parse_based_pairs(text, limit=5, max_answer_length=300, nlp=FakeNlp())
    assert [(p.question, p.answer) for p in pairs] == [
        ("Was beschreibt die Brechung des Lichtes an Grenzflächen?", "Das Brechungsgesetz"),
        ("Was beschreibt das Verhalten des Lichtes im Raum?", "Die Optik"),
    ]


def test_the_limit_bounds_the_pairs_and_leaves_the_rest_unparsed() -> None:
    text = f"{THING} Die Optik beschreibt das Verhalten des Lichtes im Raum."
    assert len(parse_based_pairs(text, limit=1, max_answer_length=300, nlp=FakeNlp())) == 1


def test_the_same_question_is_not_asked_twice() -> None:
    assert len(parse_based_pairs(f"{THING} {THING}", limit=5, max_answer_length=300, nlp=FakeNlp())) == 1


def test_a_long_subject_is_cut_to_the_bound() -> None:
    pairs = parse_based_pairs(THING, limit=1, max_answer_length=4, nlp=FakeNlp())
    assert pairs[0].answer == "Das…"


def test_a_sentence_the_parse_gives_no_subject_for_is_skipped_not_fatal() -> None:
    """A pronoun subject ends that sentence, not the search: the next sentence is still tried."""
    assert parse_based_pairs(THING, limit=3, max_answer_length=300, nlp=FakeNlp(head_pos="PRON")) == []
