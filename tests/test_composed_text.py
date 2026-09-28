"""Decomposed umlauts and invisible signs do not hide a name (audit 2026-09-28, KO-28).

Text from macOS file names or PDF copies carries umlauts decomposed (NFD): tokenize split "Wärme" into "rme", and
find_titles found "Wa" and "Gro" instead of "Wärmeleitung" and "Größe"; no article was found for such a topic. A soft
hyphen or a zero-width space inside a name hid it the same way.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.v2.qa_schemas import QaRequest
from app.domain.requests import GenerateRequest
from app.main import create_app
from app.settings import Settings
from app.sources.wlo.knowledge import paragraphs_from_text
from app.sources.wlo.models import parse_node
from app.templates.schema import TemplateSlot
from tests.conftest import make_settings
from tests.test_lehrplan_api import write_cache

SOFT_HYPHEN, ZERO_WIDTH = chr(0xAD), chr(0x200B)
TITLE = "Deutsche Gesellschaft für angewandte Optik"  # an article of the sample Wikipedia with an umlaut


def nfd(text: str) -> str:
    return unicodedata.normalize("NFD", text)


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def test_the_request_takes_what_a_caller_sends_composed() -> None:
    assert GenerateRequest(topic=nfd("Wärmeleitung")).topic == "Wärmeleitung"
    assert GenerateRequest(topic="Wärme" + SOFT_HYPHEN + "leitung").topic == "Wärmeleitung"
    assert GenerateRequest(topic="Optik", subject="Bio" + ZERO_WIDTH + "logie").subject == "Biologie"
    assert (
        QaRequest(text="Die " + nfd("Wärmeleitung") + " ist ein Vorgang.").text == "Die Wärmeleitung ist ein Vorgang."
    )
    # an earlier compendium keeps its reviewed blocks word for word
    assert GenerateRequest(topic="Optik", existing_markdown=nfd("# Wärme")).existing_markdown == nfd("# Wärme")


def test_a_node_reads_composed() -> None:
    payload = {
        "node": {
            "ref": {"id": "00000000-0000-4000-8000-000000000000"},
            "title": nfd("Größe") + SOFT_HYPHEN,
            "properties": {"cclom:general_keyword": [nfd("Wärme")], "cclom:general_description": [nfd("Über Maße")]},
        }
    }

    node = parse_node(payload)

    assert (node.title, node.keywords, node.description) == ("Größe", ("Wärme",), "Über Maße")


def test_a_decomposed_topic_finds_its_article(client: TestClient) -> None:
    answer = client.post("/api/v2/knowledge", json={"topic": nfd(TITLE), "preset": "llm-free"})

    assert answer.status_code == 200, answer.text[:300]
    body = answer.json()
    # decomposed, the title was not found as such: only the unsure suggestion of the archive led to the article
    assert (body["topic"], body["resolution"]["method"], body["resolution"]["confident"]) == (TITLE, "title", True)
    assert body["articles"][0]["title"] == TITLE


def test_a_name_split_by_an_invisible_sign_is_found(client: TestClient) -> None:
    text = "Ernst Abbe baute das Lichtmikro" + SOFT_HYPHEN + "skop."

    body = client.post("/api/v2/entities", json={"text": text, "preset": "llm-free"}).json()

    assert "Lichtmikroskop" in {entity["text"] for entity in body["entities"]}


def test_offsets_count_in_the_text_the_answer_names(client: TestClient) -> None:
    """start and end count in the composed text; the answer names it whenever it is not the one the request sent."""
    sent = "Die " + nfd(TITLE) + " tagt jedes Jahr in Jena."

    body = client.post("/api/v2/entities", json={"text": sent, "preset": "llm-free"}).json()

    assert body["text"] == unicodedata.normalize("NFC", sent)
    assert all(body["text"][entity["start"] : entity["end"]] == entity["text"] for entity in body["entities"])
    as_sent = client.post("/api/v2/entities", json={"text": body["text"], "preset": "llm-free"}).json()
    assert as_sent["text"] is None


def test_a_value_of_invisible_signs_only_is_refused(client: TestClient) -> None:
    answer = client.post("/api/v2/knowledge", json={"topic": SOFT_HYPHEN + ZERO_WIDTH, "preset": "llm-free"})

    assert answer.status_code == 422
    assert "Formatzeichen" in answer.text


def test_the_curriculum_search_reads_the_words_a_reader_sees(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    write_cache(tmp_path / "state")
    with TestClient(create_app(make_settings(sample_zims.values(), tmp_path / "state"))) as client:
        body = client.get(
            "/api/v2/lehrplan/search", params={"q": "Lin" + SOFT_HYPHEN + "sen", "subject": "Phy" + ZERO_WIDTH + "sik"}
        ).json()

    assert body["keywords"] == ["Linsen"]
    assert [match["label"] for match in body["matches"]] == ["Lichtbrechung an Linsen"]


def test_a_template_and_a_material_text_read_composed() -> None:
    slot = TemplateSlot(id="groesse", slot="groesse", title=nfd("Größe"), search_queries=[nfd("Maße") + SOFT_HYPHEN])
    line = "Die " + nfd("Wärme") + SOFT_HYPHEN + "leitung ist der Transport von Energie in einem Stoff."

    assert (slot.title, slot.search_queries) == ("Größe", ["Maße"])
    assert paragraphs_from_text(line, 10_000) == ["Die Wärmeleitung ist der Transport von Energie in einem Stoff."]
