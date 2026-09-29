"""POST /api/v2/entities (docs/umbau.md, U3): the two layers answer even when the other one is missing.

The point of the split: a service without the Wikipedia archive still returns names, and a service without the
spaCy model still returns the terms that have an article. Neither silence is acceptable, and the answer says
which way produced what.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v2.entities import _link
from app.knowledge.recognise import Mention
from app.main import create_app
from app.settings import Settings
from app.sources.gnd.index import build_gnd_index
from app.sources.local_index import RECHECK_S
from app.sources.wikidata.index import WikidataIndex, build_index
from app.sources.zim.registry import ZimRegistry
from tests.conftest import make_settings
from tests.test_gnd_index import write_gnd
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway
from tests.test_wikidata_index import write_dumps, write_langlinks

TEXT = "Ernst Abbe entwickelte in Jena das Lichtmikroskop und die Geometrische Optik."


@dataclass
class FakeEnt:
    text: str
    start_char: int
    end_char: int
    label_: str


@dataclass
class FakeDoc:
    ents: list[FakeEnt]


def fake_nlp(text: str) -> FakeDoc:
    return FakeDoc(ents=[FakeEnt("Ernst Abbe", 0, 10, "PER"), FakeEnt("Jena", 26, 30, "LOC")])


@pytest.fixture(scope="module")
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture(scope="module")
def without_archives(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    """A service that has no archive at all: only the model can say anything."""
    settings = make_settings([], tmp_path_factory.mktemp("leer") / "state")
    return TestClient(create_app(settings))


def with_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.v2.entities.load_spacy", lambda path: fake_nlp)


def test_without_a_model_the_terms_of_the_archives_still_come(client: TestClient) -> None:
    body = client.post("/api/v2/entities", json={"text": TEXT}).json()
    assert body["methods"] == ["dictionary"], "no spaCy model is configured in the tests"
    assert {entity["text"] for entity in body["entities"]} >= {"Lichtmikroskop", "Geometrische Optik"}
    assert all(entity["source"] == "dictionary" for entity in body["entities"])


def test_without_archives_the_names_still_come(without_archives: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    with_model(monkeypatch)
    body = without_archives.post("/api/v2/entities", json={"text": TEXT}).json()
    assert body["archives"] == []
    assert [entity["text"] for entity in body["entities"]] == ["Ernst Abbe", "Jena"]
    assert all(entity["linked"] is False and entity["article"] is None for entity in body["entities"])


def test_both_ways_together_and_the_article_behind_a_name(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    with_model(monkeypatch)
    body = client.post("/api/v2/entities", json={"text": TEXT}).json()
    assert body["methods"] == ["ner", "dictionary"]
    by_text = {entity["text"]: entity for entity in body["entities"]}
    assert by_text["Ernst Abbe"]["source"] == "ner" and by_text["Ernst Abbe"]["kind"] == "PER"
    abbe = by_text["Ernst Abbe"]["article"]
    assert abbe["title"] == "Ernst Abbe" and abbe["archive"] and abbe["url"].startswith("http")
    assert abbe["kind"] == "Person", "the kind comes from the lead of the article"
    assert by_text["Jena"]["linked"] is False, "no article, so nothing to link"
    assert by_text["Lichtmikroskop"]["source"] == "dictionary"


def test_linking_can_be_turned_off(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    with_model(monkeypatch)
    body = client.post("/api/v2/entities", json={"text": TEXT, "link": False}).json()
    assert body["entities"] and all(entity["article"] is None for entity in body["entities"])


def test_one_way_can_be_asked_alone(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    with_model(monkeypatch)
    body = client.post("/api/v2/entities", json={"text": TEXT, "methods": ["ner"]}).json()
    assert body["methods"] == ["ner"]
    assert all(entity["source"] == "ner" for entity in body["entities"])


@pytest.mark.parametrize(
    ("archives", "methods", "lacking"),
    [
        (True, ["ner"], "für ner fehlt das spaCy-Modell"),
        (False, ["dictionary"], "für dictionary fehlen die Archive"),
        (False, ["ner", "dictionary"], "für ner fehlt das spaCy-Modell, für dictionary fehlen die Archive"),
    ],
)
def test_without_a_way_the_503_names_what_the_asked_ways_lack(
    client: TestClient, without_archives: TestClient, archives: bool, methods: list[str], lacking: str
) -> None:
    """The 503 blamed the archives for dictionary and llm whatever was asked and whatever was there: ner alone, on a
    server with archives, was told the archives were missing (audit 2026-09-29, S11)."""
    service = client if archives else without_archives
    response = service.post("/api/v2/entities", json={"text": TEXT, "methods": methods, "preset": "llm-free"})
    assert response.status_code == 503
    assert response.json()["detail"] == f"Kein Verfahren verfügbar: {lacking}"


def test_llm_without_archives_lacks_them_as_the_rules_that_stand_in_for_it(
    without_archives: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(without_archives.app.state.service, "llm", make_gateway(FakeBApi()))  # type: ignore[attr-defined]
    response = without_archives.post("/api/v2/entities", json={"text": TEXT, "methods": ["llm"], "preset": "balanced"})
    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Kein Verfahren verfügbar: für ner fehlt das spaCy-Modell, für dictionary und llm fehlen die Archive"
    )


def test_an_unknown_archive_is_refused(client: TestClient) -> None:
    response = client.post("/api/v2/entities", json={"text": TEXT, "archives": ["gibt_es_nicht"]})
    assert response.status_code == 404
    assert "gibt_es_nicht" in str(response.json()["detail"])


def test_a_text_beyond_the_bound_is_refused(client: TestClient) -> None:
    assert client.post("/api/v2/entities", json={"text": "x" * 50_001}).status_code == 422
    assert client.post("/api/v2/entities", json={"text": ""}).status_code == 422


def test_the_number_of_entities_is_capped(client: TestClient) -> None:
    body = client.post("/api/v2/entities", json={"text": TEXT, "max_entities": 1}).json()
    assert len(body["entities"]) == 1


def test_health_says_whether_the_model_and_the_wikidata_index_are_there(
    client: TestClient, sample_zims: dict[str, Path]
) -> None:
    entities = client.get("/health").json()["components"]["entities"]
    assert entities == {
        "ner": False,
        "model": "",
        "wikidata": {"available": False, "articles": None, "dump": None},
        "gnd": {"available": False, "records": None, "release": None},
    }


DISAMBIGUATION_TEXT = "Die Brechung des Lichts erklärt das Lichtmikroskop und die Geometrische Optik."


def test_a_dictionary_term_whose_entry_is_a_disambiguation_page_is_left_out(client: TestClient) -> None:
    """The dictionary promises terms that have an article; a disambiguation page is not one (docs/umbau.md U3b)."""
    body = client.post("/api/v2/entities", json={"text": DISAMBIGUATION_TEXT}).json()
    found = {entity["text"] for entity in body["entities"]}
    assert "Brechung" not in found, "its entry is a disambiguation page, so it proves nothing"
    assert {"Lichtmikroskop", "Geometrische Optik"} <= found, "the real terms stay"
    assert all(entity["linked"] for entity in body["entities"] if entity["source"] == "dictionary")


def test_the_model_keeps_its_entity_even_behind_a_disambiguation_page(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recognition does not depend on the archives; only the dictionary makes a promise about articles."""

    def nlp(text: str) -> FakeDoc:
        return FakeDoc(ents=[FakeEnt("Brechung", 4, 12, "MISC")])

    monkeypatch.setattr("app.api.v2.entities.load_spacy", lambda path: nlp)
    body = client.post("/api/v2/entities", json={"text": DISAMBIGUATION_TEXT}).json()
    brechung = next(entity for entity in body["entities"] if entity["text"] == "Brechung")
    assert brechung["source"] == "ner" and brechung["linked"] is False and brechung["article"] is None


def test_without_linking_the_dictionary_cannot_check_and_says_so(client: TestClient) -> None:
    """link=false means: do not look anything up - so the check that needs a lookup does not run."""
    body = client.post("/api/v2/entities", json={"text": DISAMBIGUATION_TEXT, "link": False}).json()
    assert "Brechung" in {entity["text"] for entity in body["entities"]}
    assert body["note"] and "link" in body["note"]


@pytest.fixture(scope="module")
def with_wikidata(sample_zims: dict[str, Path], tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    """A service whose state directory holds a Wikidata index built from two small dumps; its shutdown closes it."""
    base = tmp_path_factory.mktemp("mit_wikidata")
    settings = make_settings(sample_zims.values(), base / "state")
    build_index(*write_dumps(base / "dumps"), settings.wikidata_db_path)
    with TestClient(create_app(settings)) as client:
        yield client


def by_text(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entity["text"]: entity for entity in body["entities"]}


def test_a_linked_wikipedia_article_names_its_authority_record(client: TestClient) -> None:
    """GND and VIAF come from the Normdaten block the archive keeps; DBpedia is built from the title (D43)."""
    found = by_text(client.post("/api/v2/entities", json={"text": TEXT}).json())
    abbe = found["Ernst Abbe"]["article"]["ids"]
    assert abbe["gnd"] == "118646419" and abbe["gnd_kind"] == "Person" and abbe["viaf"] == "19744386"
    assert abbe["dbpedia"] == "http://de.dbpedia.org/resource/Ernst_Abbe"
    assert abbe["wikidata"] is None, "this state directory holds no Wikidata index"
    assert abbe["same_as"] == [
        "https://d-nb.info/gnd/118646419",
        "https://viaf.org/viaf/19744386",
        "http://de.dbpedia.org/resource/Ernst_Abbe",
    ]
    mikroskop = found["Lichtmikroskop"]["article"]["ids"]
    assert mikroskop["gnd"] == "4039237-5" and mikroskop["gnd_kind"] == "Sachbegriff" and mikroskop["viaf"] is None


def test_the_wikidata_number_comes_from_the_local_index(with_wikidata: TestClient) -> None:
    found = by_text(with_wikidata.post("/api/v2/entities", json={"text": TEXT}).json())
    abbe = found["Ernst Abbe"]["article"]["ids"]
    assert abbe["wikidata"] == "Q999001"
    assert abbe["same_as"] == [
        "https://d-nb.info/gnd/118646419",
        "https://viaf.org/viaf/19744386",
        "http://www.wikidata.org/entity/Q999001",
        "http://de.dbpedia.org/resource/Ernst_Abbe",
    ], "GND, VIAF, Wikidata, DBpedia - the order the schema promises"
    assert found["Lichtmikroskop"]["article"]["ids"]["wikidata"] is None, "not in the small index"
    wikidata = with_wikidata.get("/health").json()["components"]["entities"]["wikidata"]
    assert wikidata == {"available": True, "articles": 5, "dump": "2026-09-07"}


def test_an_article_outside_wikipedia_carries_no_ids(client: TestClient) -> None:
    """The identifiers belong to Wikipedia articles; a Klexikon article has no Normdaten and no Wikidata item."""
    body = client.post(
        "/api/v2/entities", json={"text": "Ein Regenbogen entsteht im Licht.", "archives": ["klexikon_de_sample"]}
    ).json()
    regenbogen = by_text(body)["Regenbogen"]["article"]
    assert regenbogen["project"] == "klexikon" and regenbogen["ids"] is None


def test_a_name_in_the_genitive_links_its_article(client: TestClient) -> None:
    """The dictionary finds "Ernst Abbes" through "Ernst Abbe"; the entity keeps the words of the text."""
    body = client.post(
        "/api/v2/entities", json={"text": "Die Mikroskope Ernst Abbes waren genau.", "methods": ["dictionary"]}
    )
    abbe = by_text(body.json())["Ernst Abbes"]
    assert abbe["article"]["title"] == "Ernst Abbe" and abbe["article"]["ids"]["gnd"] == "118646419"


def test_a_name_the_model_gives_in_the_genitive_links_its_article(registry: ZimRegistry) -> None:
    mention = Mention(text="Ernst Abbes", start=0, end=11, kind="PER", source="ner")
    article = _link(registry.archives, mention)
    assert article is not None and article.title == "Ernst Abbe"


def test_an_index_the_sync_builds_while_the_service_runs_is_used_without_a_restart(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    """A new installation starts without the index; the sidecar builds it minutes later (D64)."""
    settings = make_settings(sample_zims.values(), tmp_path / "state")
    app = create_app(settings)
    now = [0.0]
    app.state.wikidata = WikidataIndex(settings.wikidata_db_path, clock=lambda: now[0])
    with TestClient(app) as client:  # the shutdown closes the index it opens
        assert client.get("/health").json()["components"]["entities"]["wikidata"]["available"] is False
        build_index(*write_dumps(tmp_path / "dumps"), settings.wikidata_db_path)
        now[0] = RECHECK_S + 1
        wikidata = client.get("/health").json()["components"]["entities"]["wikidata"]
        found = by_text(client.post("/api/v2/entities", json={"text": TEXT}).json())
    assert wikidata == {"available": True, "articles": 5, "dump": "2026-09-07"}
    assert found["Ernst Abbe"]["article"]["ids"]["wikidata"] == "Q999001"


def test_the_dbpedia_uri_names_the_resource_of_the_english_article(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    """de.dbpedia.org no longer answers (M42): an article with an English one gets DBpedia's live resource (D65)."""
    settings = make_settings(sample_zims.values(), tmp_path / "state")
    dumps = tmp_path / "dumps"
    build_index(*write_dumps(dumps), settings.wikidata_db_path, langlinks=write_langlinks(dumps))
    with TestClient(create_app(settings)) as client:
        found = by_text(client.post("/api/v2/entities", json={"text": TEXT}).json())
    abbe = found["Ernst Abbe"]["article"]["ids"]
    assert abbe["dbpedia"] == "http://dbpedia.org/resource/Ernst_Abbe"
    assert abbe["same_as"][-1] == "http://dbpedia.org/resource/Ernst_Abbe"
    mikroskop = found["Lichtmikroskop"]["article"]["ids"]
    assert mikroskop["dbpedia"] == "http://de.dbpedia.org/resource/Lichtmikroskop", "no English title in this index"


def test_an_article_without_normdaten_gets_its_gnd_from_the_local_gnd_index(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    """The DNB's dumps close the GND gap in every profile (D65); gnd_source says where a number comes from."""
    settings = make_settings(sample_zims.values(), tmp_path / "state")
    record = {"gnd": "4180001-2", "type": "SubjectHeadingSensoStricto", "names": ["Schutz vor optischer Strahlung"]}
    dump = write_gnd(tmp_path / "authorities-gnd-sachbegriff_lds_20260217.ttl.gz", [record])
    build_gnd_index([(dump, "Sachbegriff")], settings.gnd_db_path)
    text = "Der Schutz vor optischer Strahlung beschäftigte Ernst Abbe."
    with TestClient(create_app(settings)) as client:
        found = by_text(client.post("/api/v2/entities", json={"text": text}).json())
        gnd = client.get("/health").json()["components"]["entities"]["gnd"]
    schutz = found["Schutz vor optischer Strahlung"]["article"]["ids"]
    assert (schutz["gnd"], schutz["gnd_kind"], schutz["gnd_source"]) == ("4180001-2", "Sachbegriff", "name")
    abbe = found["Ernst Abbe"]["article"]["ids"]
    assert (abbe["gnd"], abbe["gnd_source"]) == ("118646419", "normdaten"), "the Normdaten block goes first"
    assert gnd == {"available": True, "records": 1, "release": "2026-02-17"}


def test_a_dictionary_that_stops_early_says_how_far_it_read(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PE-01: the answer names the character the dictionary stopped at, so a caller knows the rest went unchecked."""
    monkeypatch.setattr("app.knowledge.recognise.MAX_TITLES", 2)
    body = client.post("/api/v2/entities", json={"text": TEXT, "methods": ["dictionary"]}).json()
    assert "dictionary" in body["methods"]
    assert "dictionary las den Text bis Zeichen" in (body["note"] or "")
