"""Model2Vec ranker with an injected static model: the production default path without the real model."""

from typing import Any

import numpy as np
import pytest

from app.matching import embeddings
from app.matching.embeddings import Model2VecMatcher
from app.matching.registry import HybridLightMatcher
from app.templates.schema import TemplateSlot
from tests.test_matching import _chunk

VOCABULARY = ("beruf", "ausbildung", "licht", "linse")


class BagOfWords:
    """Static model stand-in: one dimension per known word, so texts sharing words point the same way."""

    def encode(self, texts: list[str]) -> Any:
        return np.asarray([[float(text.lower().count(word)) for word in VOCABULARY] for text in texts])


SLOTS = [
    TemplateSlot(id="s_beruf", slot="beruf", title="Beruf und Ausbildung"),
    TemplateSlot(id="s_licht", slot="licht", title="Licht und Linse"),
    TemplateSlot(id="s_quellen", slot="quellen", title="Quellen", generator="sources"),
]
CHUNKS = [
    _chunk("c_beruf", "Ausbildung", "Der Beruf verlangt eine dreijährige Ausbildung."),
    _chunk("c_licht", "Linsen", "Licht wird an der Linse gebrochen."),
    _chunk("c_fremd", "Musik", "Eine Sinfonie hat meist vier Sätze."),
    # mostly light, one mention of a job: cosine 0.035 with the job block, below the 0.1 floor
    _chunk("c_nebenbei", "Lampen", "Licht " * 20 + "und ein Beruf."),
]


@pytest.fixture
def static_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embeddings, "_load_model", lambda _path: BagOfWords())


@pytest.mark.usefixtures("static_model")
def test_chunks_are_ranked_by_cosine_and_unrelated_ones_dropped() -> None:
    scores = Model2VecMatcher("modell").score(SLOTS, CHUNKS)
    assert [item.chunk.chunk_id for item in scores["s_beruf"]] == ["c_beruf"]
    assert [item.chunk.chunk_id for item in scores["s_licht"]] == ["c_licht", "c_nebenbei"]
    assert scores["s_quellen"] == []  # generated blocks are never matched
    assert scores["s_beruf"][0].score == 1.0 and scores["s_beruf"][0].matcher == "model2vec"
    assert not any(item.chunk.chunk_id == "c_fremd" for items in scores.values() for item in items)


@pytest.mark.usefixtures("static_model")
def test_hybrid_light_adds_the_model_when_one_is_configured() -> None:
    matcher = HybridLightMatcher("modell")
    assert [component.name for component in matcher.components] == ["bm25", "char_tfidf", "model2vec"]
    fused = matcher.score(SLOTS, CHUNKS)
    assert any(reason.startswith("model2vec") for reason in fused["s_licht"][0].reasons)


def test_a_model_that_cannot_be_loaded_leaves_the_lexical_rankers(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def missing(path: str) -> Any:
        raise OSError(f"no model at {path}")

    monkeypatch.setattr(embeddings, "_load_model", missing)
    with caplog.at_level("WARNING"):
        matcher = HybridLightMatcher("fehlt")
    assert [component.name for component in matcher.components] == ["bm25", "char_tfidf"]
    assert "no model at fehlt" in caplog.text
    assert Model2VecMatcher("fehlt").score(SLOTS, CHUNKS) == {slot.id: [] for slot in SLOTS}
