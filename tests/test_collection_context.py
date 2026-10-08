"""A collection whose title says nothing ("Grundlagen") gives its topic with its place in the topic tree (M71).

Jan, 2026-10-08: a collection named only "Grundlagen" or alike within its topic tree needs its context - subject, level,
the collections above or below it - and the context must stay selective: nothing that belongs to other collections of
the tree. Measured on 32 collections of the staging repository: the rules resolved "Grundlagen" to "Sprachbau des
Esperanto"; the question N named the whole subject. Heard with the path, its own sub-collections, the titles of its
first materials and its neighbours as not meant, N's choice rose from 1.9 to 3.5-4.0 of 5 (M71).
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.compendium.errors import TopicNotFoundError
from app.domain.requests import GenerateRequest
from app.knowledge import main_article
from app.knowledge.collection_context import (
    clean_title,
    describe,
    is_neutral,
    nearest_informative,
    shown_topic,
    stand_in,
)
from app.knowledge.derived_topic import CollectionTopic
from app.knowledge.main_article import choose_main_article
from app.knowledge.resolution import resolve_topic
from app.knowledge.topic_wording import NEUTRAL_ANSWER
from app.main import create_app
from app.service import CompendiumService
from app.settings import Settings
from app.sources.wlo.cache import TtlCache
from app.sources.wlo.client import EduSharingClient
from app.sources.wlo.part import CollectionBuilder
from app.sources.wlo.tree import TreeContext, read_tree
from app.sources.zim.registry import ZimRegistry
from tests.test_asked_topic import WORDING, users, wording_then
from tests.test_llm_client import FakeBApi
from tests.test_pipeline_llm import answer_with_model_knowledge, make_gateway

BASE = "https://repo.test/edu-sharing/rest"
NODE = "11111111-aaaa-4aaa-8aaa-000000000001"  # Grundlagen
PARENT = "11111111-aaaa-4aaa-8aaa-000000000002"  # Optik
PORTAL = "11111111-aaaa-4aaa-8aaa-000000000003"  # Physik, the subject portal
ROOT = "11111111-aaaa-4aaa-8aaa-000000000004"  # WLO
MATERIAL = "11111111-aaaa-4aaa-8aaa-000000000005"  # a material in "Optik", titled "Grundlagen" as well
PHYSIK = "http://w3id.org/openeduhub/vocabs/discipline/460"


def _collection(node_id: str, title: str, parent: str, subjects: tuple[str, ...] = ("Physik",)) -> dict[str, Any]:
    props: dict[str, list[str]] = {
        "cm:title": [title],
        "ccm:taxonid": [PHYSIK] * len(subjects),
        "ccm:taxonid_DISPLAYNAME": list(subjects),
    }
    if parent:
        props["virtual:primaryparent_nodeid"] = [parent]
    return {"ref": {"id": node_id}, "title": title, "aspects": ["ccm:collection"], "properties": props}


TREE: dict[str, dict[str, Any]] = {
    NODE: _collection(NODE, "Grundlagen", PARENT),
    PARENT: _collection(PARENT, "Optik", PORTAL),
    PORTAL: _collection(PORTAL, "Physik", ROOT),
    ROOT: _collection(ROOT, "WLO", ""),
    MATERIAL: {
        "ref": {"id": MATERIAL},
        "title": "Grundlagen",
        "aspects": [],
        "properties": {"cm:title": ["Grundlagen"], "virtual:primaryparent_nodeid": [PARENT]},
    },
}
CHILDREN = {
    NODE: ["Lichtausbreitung", "Schatten"],
    PARENT: ["Grundlagen", "Linsen", "Optische Geräte"],
}
MATERIALS = {NODE: ["Was ist Licht?", "Schattenbildung im Versuch"]}


class FakeTree:
    """A topic tree of four collections: WLO > Physik > Optik > Grundlagen; records every request."""

    def __init__(self, failing: str = "") -> None:
        self.requests: list[httpx.Request] = []
        self.failing = failing

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if self.failing and self.failing in path:
            return httpx.Response(500, text="boom")
        for node_id, node in TREE.items():
            if path.endswith(f"/nodes/-home-/{node_id}/metadata"):
                return httpx.Response(200, json={"node": node})
            if path.endswith(f"/collections/-home-/{node_id}"):
                return httpx.Response(200, json={"collection": node})
            if path.endswith(f"/collections/-home-/{node_id}/children/collections"):
                subs = [
                    _collection(f"33333333-cccc-4ccc-8ccc-{node_id[-2:]}{n:010d}", t, node_id)
                    for n, t in enumerate(CHILDREN.get(node_id, []))
                ]
                if node_id == PARENT:
                    subs[0] = TREE[NODE]  # the node itself among its parent's sub-collections
                return httpx.Response(200, json={"collections": subs})
            if path.endswith(f"/collections/-home-/{node_id}/children/references"):
                refs = [
                    {"ref": {"id": f"22222222-bbbb-4bbb-8bbb-00000000000{n}"}, "title": title, "properties": {}}
                    for n, title in enumerate(MATERIALS.get(node_id, []))
                ]
                return httpx.Response(200, json={"references": refs, "pagination": {"total": len(refs)}})
        return httpx.Response(404, json={"error": "missing"})


def no_subject(prefix: str) -> bool:
    return False


def _builder(fake: FakeTree) -> CollectionBuilder:
    return CollectionBuilder(client=EduSharingClient(BASE, transport=httpx.MockTransport(fake)), cache=None)


# -- the title and its context ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    ["Grundlagen", "Einführung / Grundlagen", "Grundlagen (erwachsende Lernende)", "1 - Einführung", "Methoden"],
)
def test_a_title_of_words_that_name_no_subject_matter_is_neutral(title: str) -> None:
    assert is_neutral(title)


@pytest.mark.parametrize(
    "title", ["Grundlagen der Prozentrechnung", "Grundlagen Magnetismus", "Kernphysik", "Chemische Grundlagen"]
)
def test_a_title_naming_a_subject_matter_is_not(title: str) -> None:
    assert not is_neutral(title)


def test_the_nearest_informative_collection_above_is_the_rules_topic_cleaned_of_its_additions() -> None:
    assert clean_title("(Unsichtbar) Mediendidaktik") == "Mediendidaktik"
    assert clean_title("Nachhaltigkeit (LTP)") == "Nachhaltigkeit"
    assert nearest_informative(TreeContext(path=("Informatik-Grundkurs", "Grundlagen"))) == "Informatik-Grundkurs"
    assert nearest_informative(TreeContext(path=("Grundlagen",))) is None


def test_a_neutral_title_stands_for_the_nearest_informative_collection_above_it_as_a_topic() -> None:
    tree = TreeContext(path=("Physik-Themen", "Kernphysik"))
    assert stand_in("Grundlagen", tree, is_subject=no_subject) == "Kernphysik"
    assert stand_in("Grundlagen der Prozentrechnung", tree, is_subject=no_subject) is None
    assert stand_in("Grundlagen", TreeContext(), ("Informatik",), is_subject=no_subject) == "Informatik"
    assert stand_in("Grundlagen", None, ("Informatik",), is_subject=no_subject) is None
    # the stand-in is a topic as any other: qualifiers and a subject before a colon come off (review 2026-10-08)
    assert stand_in("Grundlagen", TreeContext(path=("Optik in Klasse 7",)), is_subject=no_subject) == "Optik"
    assert stand_in("Grundlagen", TreeContext(path=("Physik: Optik",)), is_subject="Physik".__eq__) == "Optik"


def test_a_neutral_title_is_shown_with_what_stands_in_for_it() -> None:
    assert shown_topic("Grundlagen", "Kernphysik") == "Grundlagen (Kernphysik)"
    assert shown_topic("Grundlagen (erwachsene Lernende)", "Ökologie") == "Grundlagen (erwachsene Lernende) – Ökologie"
    assert shown_topic("Grundlagen der Prozentrechnung", None) == "Grundlagen der Prozentrechnung"


def test_the_overview_leads_where_the_topic_stands_in_for_a_neutral_title(registry: ZimRegistry) -> None:
    """The rules hit "Optik" by its title; for a stand-in the overview the model named after hearing the whole place
    takes their place, and the rules' article stays visible."""
    led = resolve_topic(registry, "Optik", overview="Geometrische Optik", leading=True)
    assert (led.title, led.method, led.alternatives[0]) == ("Geometrische Optik", "llm", "Optik")
    assert resolve_topic(registry, "Optik", overview="Geometrische Optik").title == "Optik"


def test_the_context_names_the_path_what_is_inside_and_the_neighbours_as_not_meant() -> None:
    tree = TreeContext(path=("Optik",), children=("Schatten",), materials=("Was ist Licht?",), neighbours=("Linsen",))
    assert describe(tree, ("Physik",)) == (
        "Sammlung im Themenbaum unter: Optik; ihre Untersammlungen: Schatten; Materialien darin: Was ist Licht?; "
        "nicht gemeint sind die Nachbarsammlungen: Linsen"
    )
    assert describe(TreeContext(), ("Informatik",)) == "Sammlung im Fachportal Informatik"
    assert describe(TreeContext(path=("Physik-Themen", "Kernphysik"))) == (
        "Sammlung im Themenbaum unter: Physik-Themen › Kernphysik"
    )


def test_a_path_the_repository_did_not_give_is_no_place_at_the_top() -> None:
    """With the read above it failed, the collection was said to stand right under its subject portal, which pushed
    the article to the whole subject, the failure M71 fixed (review of 2026-10-08)."""
    assert describe(TreeContext(missing=("path",)), ("Physik",)) == "Sammlung zum Fach Physik"
    assert describe(TreeContext(missing=("path",))) == "Sammlung"


# -- reading the tree -------------------------------------------------------------------------------------------------


def test_the_tree_is_read_up_to_the_subject_portal_with_children_materials_and_neighbours() -> None:
    tree = read_tree(_builder(FakeTree()), NODE, PARENT, ("Physik",))

    assert tree == TreeContext(
        path=("Optik",),
        children=("Lichtausbreitung", "Schatten"),
        materials=("Was ist Licht?", "Schattenbildung im Versuch"),
        neighbours=("Linsen", "Optische Geräte"),
    )


def test_a_repository_that_fails_on_a_part_leaves_that_part_empty() -> None:
    tree = read_tree(_builder(FakeTree(failing="children/references")), NODE, PARENT, ("Physik",))
    assert tree.path == ("Optik",) and tree.materials == ()


def test_a_spent_time_budget_reads_nothing_and_names_every_part_missing() -> None:
    fake = FakeTree()

    tree = read_tree(_builder(fake), NODE, PARENT, ("Physik",), remaining=lambda: 0.0)

    assert fake.requests == [] and set(tree.missing) == {"path", "children", "materials", "neighbours"}


def test_the_path_stops_after_max_path_collections(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.sources.wlo.tree.MAX_PATH", 1)

    tree = read_tree(_builder(FakeTree()), NODE, PARENT, (), content=False)  # without a subject: up to the root

    assert tree.path == ("Optik",)


# -- in the compendium ------------------------------------------------------------------------------------------------


@pytest.fixture
def in_tree(service: CompendiumService, monkeypatch: pytest.MonkeyPatch) -> FakeTree:
    fake = FakeTree()
    monkeypatch.setattr(service, "collections", _builder(fake))
    return fake


def test_without_an_llm_a_neutral_collection_resolves_the_collection_above_it(
    service: CompendiumService, in_tree: FakeTree
) -> None:
    prepared = service.prepare(GenerateRequest(node_id=NODE, parts=["world"], preset="llm-free"))

    assert prepared.resolution.title == "Optik"
    assert prepared.asked_topic == "Grundlagen (Optik)"


def test_the_question_n_hears_the_place_of_the_collection_in_its_tree(
    service: CompendiumService, in_tree: FakeTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(lambda body: json.dumps({"uebersicht": "Optik", "artikel": ["Geometrische Optik"]}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=200_000))

    service.generate(GenerateRequest(node_id=NODE, parts=["world"], preset="balanced"))

    asked = [b["messages"][1]["content"] for b in fake.bodies if "Übersichtsartikel" in b["messages"][1]["content"]]
    assert asked and asked[0].startswith(
        "Thema: Grundlagen – Sammlung im Themenbaum unter: Optik; ihre Untersammlungen: Lichtausbreitung, Schatten; "
        "Materialien darin: Was ist Licht?, Schattenbildung im Versuch; nicht gemeint sind die Nachbarsammlungen: "
        "Linsen, Optische Geräte (Fach: Physik)"
    )


def test_a_topic_sent_along_reads_no_tree(service: CompendiumService, in_tree: FakeTree) -> None:
    """A topic sent along leads (D45), even one that reads as neutral: nothing of the tree is read."""
    with contextlib.suppress(TopicNotFoundError):
        service.prepare(GenerateRequest(topic="Grundlagen", node_id=NODE, parts=["world"], preset="llm-free"))
    assert not any(PARENT in str(request.url) or "children" in str(request.url) for request in in_tree.requests)


def test_with_an_llm_the_overview_n_names_leads_for_a_neutral_title(
    service: CompendiumService, in_tree: FakeTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rules hit "Optik", the collection above; the model heard the whole place, and its overview takes theirs
    (M71: the measured choice of N)."""
    fake = FakeBApi(lambda body: json.dumps({"uebersicht": "Geometrische Optik", "artikel": []}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=200_000))

    result = service.generate(GenerateRequest(node_id=NODE, parts=["world"], preset="balanced"))

    assert (result.resolution.title, result.resolution.method) == ("Geometrische Optik", "llm")
    assert result.resolution.alternatives[0] == "Optik", "the rules' article stays visible"
    assert result.topic == "Grundlagen (Optik)"


def test_a_title_naming_its_subject_matter_keeps_the_article_of_the_rules(
    service: CompendiumService, in_tree: FakeTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBApi(lambda body: json.dumps({"uebersicht": "Geometrische Optik", "artikel": []}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=200_000))

    result = service.generate(GenerateRequest(node_id=PARENT, parts=["world"], preset="balanced"))

    assert (result.resolution.title, result.resolution.method) == ("Optik", "title")
    assert result.topic == "Optik"


def test_without_an_llm_only_the_path_is_read(service: CompendiumService, in_tree: FakeTree) -> None:
    service.prepare(GenerateRequest(node_id=NODE, parts=["world"], preset="llm-free"))
    assert not any("children" in str(request.url) for request in in_tree.requests)


def test_the_first_materials_come_from_one_short_page_or_the_cached_listing(tmp_path: Path) -> None:
    fake = FakeTree()
    builder = CollectionBuilder(
        client=EduSharingClient(BASE, transport=httpx.MockTransport(fake)), cache=TtlCache(tmp_path / "cache.db")
    )

    assert builder.first_materials(NODE, 1) == ("Was ist Licht?",)
    asked = [r for r in fake.requests if "children/references" in str(r.url)]
    assert len(asked) == 1 and asked[0].url.params["maxItems"] == "1"
    assert builder.first_materials(NODE, 1) == ("Was ist Licht?",) and len(fake.requests) == 1, "kept for the hour"

    builder.listing(NODE)  # the whole listing, cached
    fake.requests.clear()
    assert builder.first_materials(NODE, 2) == ("Was ist Licht?", "Schattenbildung im Versuch")
    assert fake.requests == []


def test_the_node_preview_shows_the_collection_the_rules_resolve(settings: Settings) -> None:
    app = create_app(settings)
    app.state.collections = app.state.service.collections = _builder(FakeTree())

    body = TestClient(app).get(f"/api/v2/nodes/{NODE}").json()

    assert body["title"] == "Grundlagen" and body["topic"] == "Optik"


def test_the_node_preview_reads_within_the_time_of_a_request(settings: Settings) -> None:
    """The preview read the node and, for a neutral collection, the collections above it with the client's whole
    timeout each, whatever REQUEST_TIMEOUT_S allows a request (review of 2026-10-08)."""
    app = create_app(settings.model_copy(update={"request_timeout_s": 5}))
    fake = FakeTree()
    app.state.collections = app.state.service.collections = _builder(fake)

    assert TestClient(app).get(f"/api/v2/nodes/{NODE}").json()["topic"] == "Optik"

    assert len(fake.requests) > 1 and max(request.extensions["timeout"]["read"] for request in fake.requests) <= 5


def test_a_collection_as_collection_id_gives_its_topic_with_its_place_as_well(
    service: CompendiumService, in_tree: FakeTree
) -> None:
    prepared = service.prepare(GenerateRequest(collection_id=NODE, parts=["world"], preset="llm-free"))
    assert (prepared.resolution.title, prepared.asked_topic) == ("Optik", "Grundlagen (Optik)")


def test_a_material_reads_no_tree(service: CompendiumService, in_tree: FakeTree) -> None:
    with contextlib.suppress(TopicNotFoundError):
        service.prepare(GenerateRequest(node_id=MATERIAL, parts=["world"], preset="llm-free"))
    assert not any(PARENT in str(request.url) for request in in_tree.requests)


def test_a_part_the_repository_does_not_give_is_named_in_the_audit(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The path above fails: "Grundlagen" stands for its subject, and the audit says the path is missing - it does not
    look like a collection at the top of its tree."""
    monkeypatch.setattr(service, "collections", _builder(FakeTree(failing=f"/collections/-home-/{PARENT}")))
    fake = FakeBApi(lambda body: json.dumps({"uebersicht": "Optik", "artikel": []}))
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=200_000))

    result = service.generate(GenerateRequest(node_id=NODE, parts=["world"], preset="balanced"))

    tree = result.audit.topic_tree
    assert tree is not None and tree["missing"] == ["path", "neighbours"] and tree["stand_in"] == "Physik"
    assert tree["path"] == [] and tree["children"] == ["Lichtausbreitung", "Schatten"]
    assert result.topic == "Grundlagen (Physik)" and result.resolution.title == "Optik"


def test_a_neutral_title_lets_the_overview_lead_without_a_stand_in(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No collection above it and no subject: nothing stands in for "Grundlagen", and still the overview leads, as the
    rules' article for a neutral word is no topic's (review 2026-10-08)."""
    asked: list[bool] = []
    real = resolve_topic

    def spy(*args: Any, **kwargs: Any) -> Any:
        asked.append(kwargs.get("leading", False))
        return real(*args, **kwargs)

    monkeypatch.setattr(main_article, "resolve_topic", spy)
    chosen = choose_main_article(
        service.registry,
        service.subjects,
        None,
        [CollectionTopic("Grundlagen", [], [])],
        place=lambda whole: TreeContext(),
    )
    assert chosen.tree == TreeContext() and chosen.stand_in is None and asked[0] is True


def test_the_tree_of_a_node_is_read_without_credentials(
    service: CompendiumService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The node is read as the public sees it (D45, A02), and so is its tree: with an account the title of a
    collection the public may not see would go into the topic and to the model."""
    fake = FakeTree()
    client = EduSharingClient(BASE, user="redaktion", password="geheim", transport=httpx.MockTransport(fake))
    monkeypatch.setattr(service, "collections", CollectionBuilder(client=client, cache=None))
    monkeypatch.setattr(service, "repository_transport", httpx.MockTransport(fake))
    monkeypatch.setattr(service, "_foreign", {})

    service.prepare(GenerateRequest(node_id=NODE, parts=["world"], preset="llm-free"))

    read = [request for request in fake.requests if PARENT in str(request.url)]
    assert read and not any("authorization" in request.headers for request in read)


def test_a_writing_profile_words_the_topic_with_the_place_of_the_collection(
    service: CompendiumService, in_tree: FakeTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M71: heard after the metadata, the place made the wording fit better - 3.8 instead of 3.4-3.5 of 5 for neutral
    titles, 4.7 instead of 4.4 for titles naming their subject matter."""
    fake = wording_then(answer_with_model_knowledge, "Lichtausbreitung und Schatten")
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=400_000))

    result = service.generate(GenerateRequest(node_id=NODE, parts=["world"], preset="best-quality-generated"))

    assert (
        "\nLage im Themenbaum: Sammlung im Themenbaum unter: Optik; ihre Untersammlungen: Lichtausbreitung, "
        "Schatten; Materialien darin: Was ist Licht?, Schattenbildung im Versuch; nicht gemeint sind die "
        "Nachbarsammlungen: Linsen, Optische Geräte"
    ) in users(fake, WORDING)[0]
    assert result.topic == "Lichtausbreitung und Schatten"


def test_a_wording_that_names_no_subject_matter_leaves_the_topic_of_before(
    service: CompendiumService, in_tree: FakeTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M71: worded with its place, "Anwendungen" came back as "Anwendungen" - the one wording judged to say nothing;
    the heading with its stand-in said more."""
    fake = wording_then(answer_with_model_knowledge, "Grundlagen")
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=400_000))

    result = service.generate(GenerateRequest(node_id=NODE, parts=["world"], preset="best-quality-generated"))

    assert result.topic == "Grundlagen (Optik)"
    assert result.audit.llm is not None and result.audit.llm["topic_wording"]["fallback"] == NEUTRAL_ANSWER


def test_a_wording_that_names_its_subject_matter_in_brackets_is_taken(
    service: CompendiumService, in_tree: FakeTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check took the brackets off before it judged: "Grundlagen (Lichtausbreitung)" counted as naming nothing,
    fell back to "Grundlagen (Optik)" and named the wrong reason (review of 2026-10-08)."""
    fake = wording_then(answer_with_model_knowledge, "Grundlagen (Lichtausbreitung)")
    monkeypatch.setattr(service, "llm", make_gateway(fake, per_request=400_000))

    result = service.generate(GenerateRequest(node_id=NODE, parts=["world"], preset="best-quality-generated"))

    assert result.topic == "Grundlagen (Lichtausbreitung)"
