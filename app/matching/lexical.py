"""Lexical rankers: Okapi BM25 and character n-gram TF-IDF (compound-word friendly).

Scores are normalised over the whole run (all slot-chunk pairs), so a strong match for one
slot stays distinguishable from a weak best match for another slot.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.domain.models import Chunk, ScoredChunk
from app.matching.base import chunk_representation, slot_representation, tokenize
from app.templates.schema import TemplateSlot

CANDIDATES_PER_SLOT = 15

Candidates = dict[str, list[tuple[float, Chunk, str]]]


def normalise_candidates(raw: Candidates, name: str, limit: int = CANDIDATES_PER_SLOT) -> dict[str, list[ScoredChunk]]:
    """Divide by the global maximum, keep the top candidates per slot."""
    maximum = max((score for items in raw.values() for score, _, _ in items), default=0.0)
    results: dict[str, list[ScoredChunk]] = {}
    for slot_id, items in raw.items():
        items.sort(key=lambda item: item[0], reverse=True)
        results[slot_id] = [
            ScoredChunk(chunk=chunk, score=round(score / maximum, 4), matcher=name, reasons=[reason])
            for score, chunk, reason in items[:limit]
            if score > 0 and maximum > 0
        ]
    return results


class BM25Matcher:
    name = "bm25"
    weight = 1.0

    def __init__(self, k1: float = 1.5, b: float = 0.75, candidates: int = CANDIDATES_PER_SLOT) -> None:
        self.k1 = k1
        self.b = b
        self.candidates = candidates

    def score(self, slots: Sequence[TemplateSlot], chunks: Sequence[Chunk]) -> dict[str, list[ScoredChunk]]:
        raw: Candidates = {s.id: [] for s in slots}
        if not chunks:
            return {s.id: [] for s in slots}
        docs = [tokenize(chunk_representation(c)) for c in chunks]
        n = len(docs)
        avgdl = sum(len(d) for d in docs) / max(n, 1)
        df: Counter[str] = Counter()
        for doc in docs:
            df.update(set(doc))
        idf = {term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()}
        tf_maps = [Counter(doc) for doc in docs]

        for slot in slots:
            if slot.is_generated:
                continue
            query = tokenize(slot_representation(slot))
            for chunk, doc, tf in zip(chunks, docs, tf_maps, strict=True):
                score = 0.0
                matched: list[str] = []
                doc_len = len(doc)
                for term in query:
                    freq = tf.get(term)
                    if not freq:
                        continue
                    numerator = idf.get(term, 0.0) * freq * (self.k1 + 1)
                    denominator = freq + self.k1 * (1 - self.b + self.b * doc_len / max(avgdl, 1.0))
                    score += numerator / max(denominator, 1e-6)
                    matched.append(term)
                if score > 0:
                    raw[slot.id].append((score, chunk, "BM25: " + ", ".join(dict.fromkeys(matched))[:60]))
        return normalise_candidates(raw, self.name, self.candidates)


class CharTfidfMatcher:
    name = "char_tfidf"
    weight = 0.7  # recall oriented; character n-grams also match unrelated compounds

    def __init__(self, ngram_range: tuple[int, int] = (3, 5), candidates: int = CANDIDATES_PER_SLOT) -> None:
        self.ngram_range = ngram_range
        self.candidates = candidates

    def score(self, slots: Sequence[TemplateSlot], chunks: Sequence[Chunk]) -> dict[str, list[ScoredChunk]]:
        raw: Candidates = {s.id: [] for s in slots}
        content_slots = [s for s in slots if not s.is_generated]
        if not chunks or not content_slots:
            return {s.id: [] for s in slots}
        chunk_texts = [chunk_representation(c) for c in chunks]
        slot_texts = [slot_representation(s) for s in content_slots]
        vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=self.ngram_range, sublinear_tf=True, min_df=1)
        matrix = vectorizer.fit_transform(chunk_texts + slot_texts)
        sims = np.asarray(cosine_similarity(matrix[len(chunk_texts) :], matrix[: len(chunk_texts)]))
        for row, slot in zip(sims, content_slots, strict=True):
            for value, chunk in zip(row, chunks, strict=True):
                similarity = float(value)
                if similarity > 0.02:
                    raw[slot.id].append((similarity, chunk, f"Char-TF-IDF: {similarity:.2f}"))
        return normalise_candidates(raw, self.name, self.candidates)
