"""The model stage of POST /api/v2/qa (docs/umbau.md U5b): two small German models, no generative LLM.

The pipeline has three steps, and the middle one is why it looks the way it does. ``dehio/german-qg-t5-quad``
is *answer-aware*: it does not read a text and think of questions, it is given a sentence with the intended
answer marked by ``<hl>`` and writes the question for that answer. So the answers have to be chosen first.
They come from the noun phrases spaCy finds - what a comprehension question asks about is almost always a
noun phrase. ``deepset/gelectra-base-germanquad`` then marks the place in the text that answers the generated
question; it is *extractive*, so every answer is a span of the source and nothing is invented.

A candidate whose question the answer model cannot answer from the text is dropped rather than guessed at.
Both models are an external boundary here: ``QaModels`` holds them as two callables, which keeps this module
testable without torch and keeps the loading in one place (``load_qa_models``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.knowledge.segmentation import split_sentences
from app.synthesis.qa import QaPair, cut

log = logging.getLogger(__name__)

TASK_PREFIX = "generate question: "
HIGHLIGHT = "<hl>"
MIN_ANSWER_CHARS = 2


@dataclass(frozen=True)
class Candidate:
    """One possible answer: the span, the sentence it stands in, and where it stands inside that sentence."""

    text: str
    sentence: str
    start: int
    end: int


@dataclass(frozen=True)
class QaModels:
    """The two models as plain callables, so everything around them can be tested without torch."""

    generate_question: Callable[[str], str]  # a highlighted sentence -> a question
    extract_answer: Callable[[str, str], str]  # question, context -> the answering span, or empty


def highlighted(candidate: Candidate) -> str:
    """The sentence with the answer between two ``<hl>`` markers, behind the task prefix the model was trained on."""
    sentence = candidate.sentence
    marked = f"{sentence[: candidate.start]}{HIGHLIGHT} {candidate.text} {HIGHLIGHT}{sentence[candidate.end :]}"
    return TASK_PREFIX + marked


def answer_candidates(doc: Any, text: str) -> list[Candidate]:
    """The noun phrases of a spaCy document, each with the sentence it stands in and its place inside it.

    The phrases come from the model, the sentences do not. Measured on the real Wikipedia on 2026-09-20,
    spaCy cuts German leads at abbreviations and dates: "Die Optik (von altgriechisch ὀπτικός" was a sentence
    of its own, and "Ernst Karl Abbe [ˈabə] (* 23. Januar 1840 in Eisenach;" another. A question generated
    from a fragment can only be answered with a fragment. ``split_sentences`` is the project's own splitter,
    tuned on this corpus (abbreviations, initials, ordinals), and kept all five checked leads whole.

    ``text`` has to be the string the document was built from; a chunk outside every sentence is left out.
    """
    bounds: list[tuple[int, int, str]] = []
    position = 0
    for sentence in split_sentences(text):
        start = text.find(sentence, position)
        if start < 0:  # split_sentences normalises whitespace; a caller that did not is no reason to fail
            continue
        bounds.append((start, start + len(sentence), sentence))
        position = start + len(sentence)

    candidates: list[Candidate] = []
    for chunk in doc.noun_chunks:
        found = next((b for b in bounds if b[0] <= chunk.start_char < b[1]), None)
        if found is None:
            continue
        start = chunk.start_char - found[0]
        candidates.append(Candidate(text=chunk.text, sentence=found[2], start=start, end=start + len(chunk.text)))
    return candidates


def model_pairs(
    candidates: Iterable[Candidate], models: QaModels, *, count: int, max_answer_length: int = 300
) -> list[QaPair]:
    """One pair per candidate the models can both ask and answer, up to ``count``.

    The answer is extracted from the candidate's own sentence, not from the whole text. Measured in the
    image on 2026-09-20: the question was generated from that one sentence, so offering the whole text only
    invites the model to answer from somewhere else - it turned "Was ist das beste Medium, um Licht zu
    brechen?" from "Der Brechungsindex eines Mediums" into "Die Optik". The sentence is also faster
    (6.8 s against 9.3 s for five pairs). The tokenizer bounds the length at 512 tokens.
    """
    pairs: list[QaPair] = []
    asked: set[str] = set()
    for candidate in candidates:
        if len(pairs) >= count:
            break
        question = models.generate_question(highlighted(candidate)).strip()
        if not question.endswith("?") or question in asked:
            continue  # small generators sometimes echo a fragment instead of asking
        answer = models.extract_answer(question, candidate.sentence).strip()
        if len(answer) < MIN_ANSWER_CHARS:
            continue  # the text does not answer it; inventing an answer would break the promise of this stage
        asked.add(question)
        pairs.append(QaPair(question=question, answer=cut(answer, max_answer_length)))
    return pairs


def answer_span(
    context: str,
    offsets: Sequence[tuple[int, int]],
    start_scores: Sequence[float],
    end_scores: Sequence[float],
    is_context: Sequence[bool],
) -> str:
    """The best span of ``context`` the model points at, sliced out of the source verbatim.

    Decoding the token ids instead looks equivalent and is not: it drops every character the model's
    vocabulary does not know and re-joins the rest with its own spacing. Measured in the image on 2026-09-20,
    a lead came back as "Die Optik ( von altgriechisch optikós ..." - the Greek word gone, brackets left
    behind, "(von" turned into "( von". This stage promises spans of the source, so it has to cut them out.

    ``is_context`` keeps the question out of the answer; an empty span means the text does not answer.
    """
    usable = [index for index, ok in enumerate(is_context) if ok]
    if not usable:
        return ""
    start = max(usable, key=lambda index: start_scores[index])
    end = max(usable, key=lambda index: end_scores[index])
    if end < start:
        return ""
    return context[offsets[start][0] : offsets[end][1]]


@lru_cache(maxsize=1)
def load_qa_models(qg_path: str, qa_path: str) -> QaModels | None:
    """Load both models once per process; anything missing means: this stage cannot run.

    Loading costs about 1.3 GB of memory, so it happens on the first request that asks for it rather than at
    start-up - a service that never asks for ``models`` should not pay for it in every worker.
    """
    if not qg_path or not qa_path or not Path(qg_path).is_dir() or not Path(qa_path).is_dir():
        return None
    try:
        import torch  # optional extra "qa-models"; the service runs without it
        from transformers import AutoModelForQuestionAnswering, AutoModelForSeq2SeqLM, AutoTokenizer

        qg_tokenizer = AutoTokenizer.from_pretrained(qg_path)
        qg_model = AutoModelForSeq2SeqLM.from_pretrained(qg_path)
        qa_tokenizer = AutoTokenizer.from_pretrained(qa_path)
        qa_model = AutoModelForQuestionAnswering.from_pretrained(qa_path)
    except Exception as exc:  # a missing package or a broken directory must not take the endpoint down
        log.error("QA models not usable (%s, %s): %s", qg_path, qa_path, exc)
        return None

    def generate(marked: str) -> str:
        encoded = qg_tokenizer(marked, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            output = qg_model.generate(**encoded, max_new_tokens=48, num_beams=4)
        return str(qg_tokenizer.decode(output[0], skip_special_tokens=True))

    def extract(question: str, context: str) -> str:
        encoded = qa_tokenizer(
            question,
            context,
            return_tensors="pt",
            truncation="only_second",  # the question is short and must survive whole
            max_length=512,
            return_offsets_mapping=True,
        )
        offsets = [tuple(pair) for pair in encoded.pop("offset_mapping")[0].tolist()]
        in_context = [
            sequence == 1 and offset != (0, 0)
            for sequence, offset in zip(encoded.sequence_ids(0), offsets, strict=True)
        ]
        with torch.no_grad():
            output = qa_model(**encoded)
        return answer_span(context, offsets, output.start_logits[0].tolist(), output.end_logits[0].tolist(), in_context)

    log.info("QA models loaded: %s, %s", qg_path, qa_path)
    return QaModels(generate_question=generate, extract_answer=extract)


def describe(qg_path: str, qa_path: str) -> dict[str, Any]:
    """What ``/health`` reports: which models are configured and whether their files are in the image.

    Deliberately no load - a probe must not pull 1.3 GB into memory.
    """
    return {
        "question_generator": qg_path,
        "answer_model": qa_path,
        "present": bool(qg_path and qa_path and Path(qg_path).is_dir() and Path(qa_path).is_dir()),
    }
