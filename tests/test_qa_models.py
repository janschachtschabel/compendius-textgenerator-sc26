"""The model stage of POST /api/v2/qa (docs/umbau.md U5b), without torch.

The two models are an external boundary: the generator turns a sentence with a highlighted answer into a
question, the answer model marks the place in the text that answers it. Both are injected here as plain
callables, so the pipeline around them - candidates, highlighting, bounds, what is thrown away - is tested
without a gigabyte of weights. That the real models load and produce German is checked in the image
(scripts/smoke_image.py).
"""

from __future__ import annotations

from app.synthesis.qa_models import Candidate, QaModels, answer_candidates, highlighted, model_pairs

TEXT = "Die Optik ist ein Teilgebiet der Physik. Ernst Abbe entwickelte in Jena das Lichtmikroskop."
FIRST = "Die Optik ist ein Teilgebiet der Physik."
SECOND = "Ernst Abbe entwickelte in Jena das Lichtmikroskop."


def at(sentence: str, span: str) -> Candidate:
    """Offsets computed, not counted: a hand-written offset is a bug the test would blame on the code."""
    start = sentence.index(span)
    return Candidate(text=span, sentence=sentence, start=start, end=start + len(span))


CANDIDATES = [at(FIRST, "Die Optik"), at(FIRST, "der Physik"), at(SECOND, "Ernst Abbe")]


def models(question: str = "Was ist das?", answer: str = "ein Teilgebiet der Physik") -> QaModels:
    return QaModels(generate_question=lambda marked: question, extract_answer=lambda q, context: answer)


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

    def generate(marked: str) -> str:
        asked.append(marked)
        return f"Frage {len(asked)}?"

    pairs = model_pairs(CANDIDATES, QaModels(generate, lambda q, c: "Antwort"), count=2)
    assert len(pairs) == 2
    assert len(asked) == 2, "the generator is not run for candidates beyond the count"


def test_a_long_answer_is_cut_to_the_bound() -> None:
    pairs = model_pairs(CANDIDATES[:1], models(answer="x" * 400), count=1, max_answer_length=50)
    assert len(pairs[0].answer) == 50 and pairs[0].answer.endswith("…")


def test_a_question_without_a_question_mark_is_no_question() -> None:
    """Measured behaviour of small generators: they sometimes echo a fragment instead of asking."""
    assert model_pairs(CANDIDATES, models(question="Die Optik ist ein Teilgebiet"), count=5) == []


class FakeSpan:
    """The bits of a spaCy span the candidate extraction touches."""

    def __init__(self, text: str, start_char: int, sent: FakeSpan | None = None) -> None:
        self.text, self.start_char = text, start_char
        self._sent = sent

    @property
    def sent(self) -> FakeSpan:
        assert self._sent is not None
        return self._sent


class FakeDoc:
    def __init__(self, noun_chunks: list[FakeSpan]) -> None:
        self.noun_chunks = noun_chunks


def test_candidates_carry_their_place_inside_their_own_sentence() -> None:
    """The offsets are relative to the sentence, not to the document: the generator only sees the sentence."""
    second = FakeSpan(SECOND, start_char=len(FIRST) + 1)
    doc = FakeDoc([FakeSpan("Ernst Abbe", start_char=len(FIRST) + 1, sent=second)])
    candidate = answer_candidates(doc)[0]
    assert candidate.sentence == SECOND
    assert candidate.start == 0 and candidate.end == len("Ernst Abbe")
    assert candidate.sentence[candidate.start : candidate.end] == "Ernst Abbe"
