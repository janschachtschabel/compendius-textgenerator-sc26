"""Lehrplan endpoints: public status and search from the local cache, admin harvest request."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.main import create_app
from app.sources.lehrplan.harvest import TRIGGER_FILE
from app.sources.lehrplan.store import SCHEMA_VERSION, LehrplanRecord, LehrplanWriter
from app.sources.lehrplan.tree import HarvestedNode
from tests.conftest import make_settings, strings_in
from tests.test_article_choice import rating
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import make_gateway

AUTH = {"X-Admin-Token": "s3cret"}
PHYSIK = LehrplanRecord(
    iri="https://lp-sachsen.org/resource/522",
    label="Gymnasium Physik",
    bundesland_code="SN",
    bundesland="Sachsen",
    schularten=["Gymnasium"],
    schulfaecher=["Physik"],
    schulstufen=["Sekundarbereich I"],
)


def write_cache(state_dir: Path) -> None:
    writer = LehrplanWriter(state_dir / "lehrplan.db")
    writer.add_lehrplan(PHYSIK)
    node = HarvestedNode(
        iri="https://lp-sachsen.org/resource/7053",
        label="Lichtbrechung an Linsen",
        types=(),
        rollen=["kompetenz"],
        jahrgangsstufen=["Klassenstufe 7"],
        position=None,
    )
    node.parent_label = "Lernbereich 2: Optik"
    writer.add_nodes(PHYSIK.iri, [node])
    writer.set_meta(
        {"harvested_at": "2026-09-17T12:00:00+00:00", "counts": '{"SN": 1}', "endpoint": "https://sparql.test/"}
    )
    writer.commit()


def write_broken_cache(state_dir: Path) -> None:
    """A file that passes the schema check but lacks the node tables, as after an interrupted copy."""
    state_dir.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(state_dir / "lehrplan.db")) as connection:
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO meta VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        connection.commit()


def _client(sample_zims: dict[str, Path], tmp_path: Path, **overrides: Any) -> TestClient:
    settings = make_settings(sample_zims.values(), tmp_path / "state", **overrides)
    return TestClient(create_app(settings))


def test_status_reports_a_missing_cache_and_then_its_meta(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with _client(sample_zims, tmp_path) as client:
        body = client.get("/api/v2/lehrplan/status").json()
        assert body["available"] is False
        assert body["counts"] == {"lehrplaene": {}, "nodes": 0}
        write_cache(tmp_path / "state")
        body = client.get("/api/v2/lehrplan/status").json()
        assert body["available"] is True
        assert body["meta"]["harvested_at"].startswith("2026-09-17")
        assert body["counts"]["lehrplaene"] == {"SN": 1}
        assert body["coverage"]["states"] == ["Sachsen"]


def test_search_reads_the_cache_and_applies_the_subject(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    write_cache(tmp_path / "state")
    with _client(sample_zims, tmp_path) as client:
        body = client.get("/api/v2/lehrplan/search", params={"q": "Optik"}).json()
        assert body["keywords"] == ["Optik"] and body["matches"][0]["label"] == "Lichtbrechung an Linsen"
        first = body["matches"][0]
        assert first["bundesland"] == "Sachsen" and first["schulstufe"] == "Sekundarstufe I"
        assert first["klassenstufe"] == "Klassenstufe 7" and first["lehrplan"] == "Gymnasium Physik"
        narrowed = client.get("/api/v2/lehrplan/search", params={"q": "Optik", "subject": "Chemie"}).json()
        assert narrowed["matches"] == [] and narrowed["subject_terms"] == [
            "chemie",
            "natur und technik",
            "naturwissenschaften",
        ]
        assert client.get("/api/v2/lehrplan/search", params={"q": "Op"}).status_code == 422


def test_the_topic_mode_searches_as_part_2_of_a_compendium_does(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    """The search takes the words as sent; mode=topic resolves them as part 2 does, to the article of the topic,
    its aliases and the sub-topics of its corpus (decision paper, point 8)."""
    write_cache(tmp_path / "state")
    with _client(sample_zims, tmp_path) as client:
        words = client.get("/api/v2/lehrplan/search", params={"q": "Lichtlehre"}).json()
        topic = client.get("/api/v2/lehrplan/search", params={"q": "Lichtlehre", "mode": "topic"}).json()
        compendium = client.post("/api/v2/compendium", json={"topic": "Lichtlehre", "parts": ["curricula"]})
    part_2 = compendium.json()["curricula"]
    assert words["mode"] == "keyword" and words["matches"] == [], "no element names the redirect Lichtlehre"
    assert topic["mode"] == "topic" and topic["topic"] == "Optik"
    assert topic["keywords"] == part_2["keywords"] and topic["subject_terms"] == part_2["subject_terms"]
    assert [match["label"] for match in topic["matches"]] == ["Lichtbrechung an Linsen"]


def test_the_topic_mode_answers_404_for_a_topic_the_archives_do_not_have(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    write_cache(tmp_path / "state")
    with _client(sample_zims, tmp_path) as client:
        response = client.get("/api/v2/lehrplan/search", params={"q": "Xylophonquartett", "mode": "topic"})
        unknown_mode = client.get("/api/v2/lehrplan/search", params={"q": "Optik", "mode": "thema"})
    assert response.status_code == 404
    assert unknown_mode.status_code == 422


SEARCH = "/api/v2/lehrplan/search"


def test_best_quality_lets_the_llm_judge_what_the_rules_found(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    """D58, D59: the search takes the profiles as part 2 does; best-quality drops what the model rates 0, and it
    spends from a budget of its own - the one of the other profiles is far too small here."""
    write_cache(tmp_path / "state")
    with _client(sample_zims, tmp_path) as client:
        fake = FakeBApi(lambda body: json.dumps({"e1": 0}))
        client.app.state.service.llm = make_gateway(fake, per_request=100)  # type: ignore[attr-defined]
        best = client.get(SEARCH, params={"q": "Optik", "preset": "best-quality"}).json()
        tight = client.get(SEARCH, params={"q": "Optik", "preset": "balanced", "curriculum_check": "llm"}).json()
    assert best["preset"] == "best-quality" and best["matches"] == []
    assert best["llm"]["curriculum_check"] == {
        "requested": "llm",
        "used": "llm",
        "rated": 1,
        "answered": 1,
        "dropped": 1,
        "fallbacks": {},
        "fallback": None,
    }
    assert best["llm_tokens"]["calls"] == 1
    assert [match["note"] for match in tight["matches"]] == [None], "the rules decide what the budget left unrated"
    assert any("Token-Budget der Anfrage" in reason for reason in tight["llm"]["curriculum_check"]["fallbacks"])


def test_an_element_the_llm_rates_fitting_comes_back_with_its_note(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    write_cache(tmp_path / "state")
    with _client(sample_zims, tmp_path) as client:
        fake = FakeBApi(lambda body: json.dumps({"e1": 2}))
        client.app.state.service.llm = make_gateway(fake)  # type: ignore[attr-defined]
        body = client.get(SEARCH, params={"q": "Optik", "preset": "best-quality-generated", "limit": 5}).json()
    assert [(match["label"], match["matched_in"], match["note"]) for match in body["matches"]] == [
        ("Lichtbrechung an Linsen", "parent", 2)
    ]


def test_a_profile_that_needs_an_llm_is_a_503_on_a_server_without_one(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    """As a compendium (D53): refused instead of quietly running the rules. The words alone need no article, so
    balanced searches them without an LLM."""
    write_cache(tmp_path / "state")
    with _client(sample_zims, tmp_path) as client:
        free = client.get(SEARCH, params={"q": "Optik"})
        best = client.get(SEARCH, params={"q": "Optik", "preset": "best-quality"})
        checked = client.get(SEARCH, params={"q": "Optik", "curriculum_check": "llm"})
        topic = client.get(SEARCH, params={"q": "Optik", "mode": "topic", "preset": "balanced"})
        words = client.get(SEARCH, params={"q": "Optik", "preset": "balanced"})
    assert free.status_code == 200 and free.json()["preset"] == "llm-free" and free.json()["llm"] is None
    assert best.status_code == 503 and "curriculum_check=llm" in best.json()["detail"]
    assert checked.status_code == 503 and "curriculum_check=llm" in checked.json()["detail"]
    assert topic.status_code == 503 and "article_choice=llm" in topic.json()["detail"]
    assert words.status_code == 200 and words.json()["preset"] == "balanced"


def test_the_topic_mode_chooses_the_article_as_part_2_of_the_profile_does(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    """In balanced the LLM checks the side articles of the topic, as in a balanced compendium, so both search for
    the same sub-topics."""
    write_cache(tmp_path / "state")
    with _client(sample_zims, tmp_path) as client:
        client.app.state.service.llm = make_gateway(  # type: ignore[attr-defined]
            FakeBApi(rating({"Augenoptiker": 0})), per_request=100_000
        )
        body = client.get(SEARCH, params={"q": "Optik", "mode": "topic", "preset": "balanced"}).json()
        compendium = client.post(
            "/api/v2/compendium", json={"topic": "Optik", "parts": ["curricula"], "preset": "balanced"}
        )
    choice = body["llm"]["article_choice"]
    assert choice["requested"] == "llm" and choice["hits_dropped"] == ["Augenoptiker"]
    assert body["keywords"] == compendium.json()["curricula"]["keywords"]
    assert body["llm"]["curriculum_check"]["requested"] == "rule-based"


def test_an_unknown_subject_is_a_422_that_names_the_known_ones(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    """ "Pysik" used to search every subject without saying so (decision paper, point 8)."""
    write_cache(tmp_path / "state")
    with _client(sample_zims, tmp_path) as client:
        for mode in ("keyword", "topic"):
            response = client.get("/api/v2/lehrplan/search", params={"q": "Optik", "subject": "Pysik", "mode": mode})
            assert response.status_code == 422, mode
            assert "Pysik" in response.json()["detail"] and "Physik" in response.json()["detail"]
        assert client.get("/api/v2/lehrplan/search", params={"q": "Optik", "subject": "Physik"}).status_code == 200


def test_a_subject_without_curriculum_words_narrows_nothing_and_says_so(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    """Every subject of the two vocabularies is taken (D51), but only the 37 of config/subjects.yaml have curriculum
    words; any other one searches every subject, which the answer shows by an empty subject_terms and /docs says."""
    write_cache(tmp_path / "state")
    with _client(sample_zims, tmp_path) as client:
        body = client.get("/api/v2/lehrplan/search", params={"q": "Optik", "subject": "Agrarwirtschaft"}).json()
        spec = client.get("/openapi.json").json()
    assert body["subject_terms"] == [] and body["matches"][0]["label"] == "Lichtbrechung an Linsen"
    parameters = spec["paths"]["/api/v2/lehrplan/search"]["get"]["parameters"]
    subject = next(parameter for parameter in parameters if parameter["name"] == "subject")
    assert "subject_terms" in subject["description"] and "vocabularies" in subject["description"]


def test_harvest_request_is_admin_only_and_writes_the_trigger_file(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    with _client(sample_zims, tmp_path) as client:
        assert client.post("/api/v2/lehrplan/harvest").status_code == 404
    with _client(sample_zims, tmp_path, admin_token="s3cret") as client:
        assert client.post("/api/v2/lehrplan/harvest").status_code == 403
        assert client.post("/api/v2/lehrplan/harvest", headers=AUTH).status_code == 202
        assert (tmp_path / "state" / TRIGGER_FILE).exists()


def test_broken_cache_is_reported_as_unavailable_not_as_a_server_error(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    write_broken_cache(tmp_path / "state")
    with _client(sample_zims, tmp_path) as client:
        search = client.get("/api/v2/lehrplan/search", params={"q": "Optik"})
        assert search.status_code == 200 and search.json()["available"] is False
        status = client.get("/api/v2/lehrplan/status")
        assert status.status_code == 200 and status.json()["counts"] == {"lehrplaene": {}, "nodes": 0}


def test_public_answers_do_not_reveal_server_paths(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with _client(sample_zims, tmp_path) as client:
        status = client.get("/api/v2/lehrplan/status").json()
        compendium = client.post("/api/v2/compendium", json={"topic": "Optik", "parts": ["curricula"]}).json()
    # Every string, not str(status): the repr doubles the backslashes of a Windows path, so it would never match
    assert "db_path" not in status and not any(str(tmp_path) in text for text in strings_in(status))
    assert compendium["curricula"]["summary"] == {"reason": "cache_missing"}


def test_the_public_status_leaves_the_error_text_of_the_harvest_to_the_log(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    state = tmp_path / "state"
    state.mkdir()
    error = f"OperationalError: unable to open database file: {state / 'lehrplan.db.tmp'}"
    status = {"state": "error", "updated_at": "2026-09-18T04:00:00+00:00", "started_at": "2026-09-18T03:40:00+00:00"}
    (state / "lehrplan_status.json").write_text(json.dumps({**status, "error": error}), encoding="utf-8")
    with _client(sample_zims, tmp_path) as client:
        harvest = client.get("/api/v2/lehrplan/status").json()["harvest"]
    assert harvest["state"] == "error" and harvest["error"]  # that it failed stays visible
    assert not any(str(tmp_path) in text or "OperationalError" in text for text in strings_in(harvest))
