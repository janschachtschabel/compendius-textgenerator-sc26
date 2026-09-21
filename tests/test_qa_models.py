"""The model stage of POST /api/v2/qa (docs/umbau.md U5b), without torch.

The two models are an external boundary: the generator turns a sentence with a highlighted answer into a
question, the answer model marks the place in the text that answers it. Both are injected here as plain
callables, so the pipeline around them - candidates, highlighting, bounds, what is thrown away - is tested
without a gigabyte of weights. That the real models load and produce German is checked in the image
(scripts/smoke_image.py).
"""

from __future__ import annotations

from collections.abc import Sequence

from app.synthesis.qa_models import (
    HIGHLIGHT,
    Candidate,
    QaModels,
    answer_candidates,
    answer_span,
    highlighted,
    model_pairs,
    spread,
)

TEXT = "Die Optik ist ein Teilgebiet der Physik. Ernst Abbe entwickelte in Jena das Lichtmikroskop."
FIRST = "Die Optik ist ein Teilgebiet der Physik."
SECOND = "Ernst Abbe entwickelte in Jena das Lichtmikroskop."


def at(sentence: str, span: str) -> Candidate:
    """Offsets computed, not counted: a hand-written offset is a bug the test would blame on the code."""
    start = sentence.index(span)
    return Candidate(text=span, sentence=sentence, start=start, end=start + len(span))


CANDIDATES = [at(FIRST, "Die Optik"), at(FIRST, "der Physik"), at(SECOND, "Ernst Abbe")]


def models(question: str = "Was ist das?", answer: str = "ein Teilgebiet der Physik") -> QaModels:
    return QaModels(
        generate_questions=lambda marked: [question] * len(marked),
        extract_answer=lambda q, context: answer,
    )


def test_the_answer_is_highlighted_the_way_the_generator_expects() -> None:
    """The model card asks for the answer between two <hl> markers, behind a task prefix."""
    assert highlighted(CANDIDATES[1]) == "generate question: Die Optik ist ein Teilgebiet <hl> der Physik <hl>."


def test_a_pair_carries_the_generated_question_and_the_extracted_answer() -> None:
    pairs = model_pairs(CANDIDATES[:1], models("Was ist Optik?", "ein Teilgebiet der Physik"), count=5)
    assert len(pairs) == 1
    assert pairs[0].question == "Was ist Optik?"
    assert pairs[0].answer == "ein Teilgebiet der Physik"


def test_a_candidate_the_answer_model_cannot_answer_is_dropped() -> None:
    """An empty span means: the text does not answer this question. Inventing one would break the promise."""
    assert model_pairs(CANDIDATES, models(answer="   "), count=5) == []


def test_the_same_question_is_not_asked_twice() -> None:
    pairs = model_pairs(CANDIDATES, models("Worum geht es?", "um Optik"), count=5)
    assert len(pairs) == 1, "three candidates, one question text"


def test_the_count_bounds_the_pairs_and_stops_the_work() -> None:
    asked: list[str] = []

    def generate(marked: Sequence[str]) -> list[str]:
        start = len(asked)
        asked.extend(marked)
        return [f"Frage {start + n}?" for n in range(len(marked))]

    pairs = model_pairs(CANDIDATES, QaModels(generate, lambda q, c: "Antwort"), count=2)
    assert len(pairs) == 2
    assert len(asked) == 2, "the generator is not run for candidates beyond the count"


def test_the_generator_is_asked_for_a_whole_round_at_once() -> None:
    """One call per candidate leaves the machine idle between them; a batch fills it.

    Measured in the image on 2026-09-21 over ten candidates of a real compendium text: 1.97 s per
    question one at a time against 1.03 s in one batch, with four beams in both cases and the same
    wording for all ten. The gain is the generator running once instead of ten times, not a cheaper
    model - so it costs no quality.
    """
    batches: list[int] = []

    def generate(marked: Sequence[str]) -> list[str]:
        batches.append(len(marked))
        return [f"Frage {len(batches)}.{n}?" for n in range(len(marked))]

    pairs = model_pairs(CANDIDATES, QaModels(generate, lambda q, c: "Antwort"), count=3)
    assert len(pairs) == 3
    assert batches == [3], "three candidates, one call to the generator"


def test_a_long_answer_is_cut_to_the_bound() -> None:
    """A span can be long when its sentence is long; the bound still holds.

    The setup used to hand back an answer ten times the length of its sentence. MAX_ANSWER_SHARE now
    rejects that, and ``extract_answer`` cannot produce it either: the span is a slice of the sentence
    (test_the_answer_is_a_verbatim_slice_of_the_source). A long sentence carries a long slice instead.
    """
    sentence = "Die Optik " + "und die Brechung " * 30 + "sind ein Teilgebiet der Physik."
    pairs = model_pairs([at(sentence, "Die Optik")], models(answer=sentence[:300]), count=1, max_answer_length=50)
    assert len(pairs[0].answer) == 50 and pairs[0].answer.endswith("…")


def test_a_question_without_a_question_mark_is_no_question() -> None:
    """Measured behaviour of small generators: they sometimes echo a fragment instead of asking."""
    assert model_pairs(CANDIDATES, models(question="Die Optik ist ein Teilgebiet"), count=5) == []


class FakeSpan:
    """The bits of a spaCy noun chunk the candidate extraction touches: its text and where it starts."""

    def __init__(self, text: str, start_char: int) -> None:
        self.text, self.start_char = text, start_char


class FakeDoc:
    def __init__(self, noun_chunks: list[FakeSpan]) -> None:
        self.noun_chunks = noun_chunks


def test_candidates_carry_their_place_inside_their_own_sentence() -> None:
    """The offsets are relative to the sentence, not to the document: the generator only sees the sentence."""
    text = f"{FIRST} {SECOND}"
    doc = FakeDoc([FakeSpan("Ernst Abbe", start_char=text.index("Ernst Abbe"))])
    candidate = answer_candidates(doc, text)[0]
    assert candidate.sentence == SECOND
    assert candidate.start == 0 and candidate.end == len("Ernst Abbe")
    assert candidate.sentence[candidate.start : candidate.end] == "Ernst Abbe"


# Measured in the image on 2026-09-20: decoding the token ids gives a reconstruction, not the source.
GREEK = "Die Optik (von altgriechisch ὀπτικός optikós „zum Sehen gehörend“) ist ein Gebiet der Physik."


def spans(context: str) -> list[tuple[int, int]]:
    """Character offsets of a two-token question plus one token per word of the context."""
    offsets = [(0, 0), (0, 0), (0, 0)]  # [CLS] Frage [SEP]
    position = 0
    for word in context.split(" "):
        start = context.index(word, position)
        offsets.append((start, start + len(word)))
        position = start + len(word)
    offsets.append((0, 0))  # [SEP]
    return offsets


def is_context(offsets: list[tuple[int, int]]) -> list[bool]:
    return [index > 2 and offset != (0, 0) for index, offset in enumerate(offsets)]


def scores(offsets: list[tuple[int, int]], start: int, end: int) -> tuple[list[float], list[float]]:
    return (
        [1.0 if i == start else 0.0 for i in range(len(offsets))],
        [1.0 if i == end else 0.0 for i in range(len(offsets))],
    )


def test_the_answer_is_a_verbatim_slice_of_the_source() -> None:
    """Characters outside the model's vocabulary must not vanish, and spacing must not be reinvented."""
    offsets = spans(GREEK)
    start, end = 3, 8  # "Die" through "optikós", across the Greek word
    start_scores, end_scores = scores(offsets, start, end)
    answer = answer_span(GREEK, offsets, start_scores, end_scores, is_context(offsets))
    assert answer == "Die Optik (von altgriechisch ὀπτικός optikós"
    assert answer in GREEK, "an extractive answer is a span of the text, not a reconstruction of it"


def test_the_question_is_never_part_of_the_answer() -> None:
    offsets = spans(GREEK)
    start_scores = [1.0] + [0.0] * (len(offsets) - 1)  # the model likes a question token best
    end_scores = [0.0] * len(offsets)
    end_scores[5] = 1.0
    answer = answer_span(GREEK, offsets, start_scores, end_scores, is_context(offsets))
    assert answer and answer in GREEK and not answer.startswith("[")


def test_an_end_before_the_start_answers_nothing() -> None:
    offsets = spans(GREEK)
    start_scores, end_scores = scores(offsets, 8, 4)
    assert answer_span(GREEK, offsets, start_scores, end_scores, is_context(offsets)) == ""


def test_a_context_without_a_single_usable_token_answers_nothing() -> None:
    offsets = spans(GREEK)
    start_scores, end_scores = scores(offsets, 0, 1)
    assert answer_span(GREEK, offsets, start_scores, end_scores, [False] * len(offsets)) == ""


# Measured in the image on 2026-09-20: spaCy cuts the Optik lead into three pieces (36, 66 and 242 characters),
# the first of them "Die Optik (von altgriechisch ὀπτικός". The project's own splitter keeps such leads whole.
LEAD = (
    "Ernst Karl Abbe [ˈabə] (* 23. Januar 1840 in Eisenach; † 14. Januar 1905 in Jena) war ein deutscher "
    "Physiker. Er schuf mit Carl Zeiß die Grundlagen der modernen Optik."
)


def test_the_sentence_comes_from_the_projects_splitter_not_from_the_model() -> None:
    """spaCy breaks German leads at abbreviations and dates; a fragment yields a fragment of an answer."""
    doc = FakeDoc([FakeSpan("Ernst Karl Abbe", start_char=0)])
    candidate = answer_candidates(doc, LEAD)[0]
    assert candidate.sentence.endswith("war ein deutscher Physiker.")
    assert "23. Januar 1840" in candidate.sentence, "the date must not end the sentence"


def test_a_chunk_behind_the_last_sentence_is_left_out() -> None:
    doc = FakeDoc([FakeSpan("Ernst Karl Abbe", start_char=len(LEAD) + 50)])
    assert answer_candidates(doc, LEAD) == []


def test_the_pairs_do_not_all_come_from_the_first_sentence() -> None:
    """The order of the candidates is the coverage of the text, because the generator works per sentence.

    Measured against the real Wikipedia on 2026-09-21: taken in reading order, all twenty pairs asked for
    "Optik" came out of the first two sentences, and all eight for "Ernst Abbe" out of his birth-and-death
    line - so every question wanted a date or a place.
    """
    echo = QaModels(
        generate_questions=lambda marked: [f"Was ist {one.split(HIGHLIGHT)[1].strip()}?" for one in marked],
        extract_answer=lambda question, context: context.split()[0],
    )
    pairs = model_pairs(CANDIDATES, echo, count=2, max_answer_length=300)
    assert [pair.answer for pair in pairs] == ["Die", "Ernst"]


def test_a_sentence_with_more_candidates_contributes_them_in_the_later_rounds() -> None:
    """Nothing is dropped by the spreading; the extra candidates of a rich sentence come after the others."""
    rich = [at(FIRST, "Die Optik"), at(FIRST, "ein Teilgebiet"), at(FIRST, "der Physik")]
    order = spread([*rich, at(SECOND, "Ernst Abbe")])
    assert [c.text for c in order] == ["Die Optik", "Ernst Abbe", "ein Teilgebiet", "der Physik"]


def test_spreading_nothing_is_no_error() -> None:
    """A text the tagger finds no noun phrase in must answer with no pairs, not with a traceback."""
    assert spread([]) == []
    assert model_pairs([], models(), count=3, max_answer_length=300) == []


def test_an_answer_that_repeats_the_whole_sentence_is_dropped() -> None:
    """A span equal to its sentence answers nothing; it reads the sentence back.

    Measured in the image on 2026-09-21 over 32 pairs from four real topics: 7 of them had an answer
    covering more than 80 percent of its own sentence, and they carry most of the pairs a reader would
    call useless ("Was ist die Wellennatur des Lichtes?" answered with "Grundlage der Wellenoptik ist die
    Wellennatur des Lichts").
    """
    assert model_pairs([at(FIRST, "Die Optik")], models("Was ist die Optik?", FIRST), count=5) == []


def test_a_dropped_repetition_does_not_cost_the_candidates_behind_it() -> None:
    """The loop goes on: one rejected pair may not end the search."""
    questions = iter(["Was ist die Optik?", "Wo entwickelte er das Mikroskop?"])
    answers = iter([FIRST, "in Jena"])
    one_each = QaModels(
        generate_questions=lambda marked: [next(questions) for _ in marked],
        extract_answer=lambda question, context: next(answers),
    )
    pairs = model_pairs([at(FIRST, "Die Optik"), at(SECOND, "Ernst Abbe")], one_each, count=5)
    assert [pair.answer for pair in pairs] == ["in Jena"]
