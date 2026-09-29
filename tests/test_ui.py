"""The review page at /ui (D66): off unless UI_ENABLED is set, static files only, and lists taken from the API.

People without knowledge of the service check its texts there. The page sends the requests from the browser with
the key the reader enters, so it needs no rights of its own; it only has to stay off by default, serve nothing but
its own files, and offer exactly the values the endpoints accept.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, get_args

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.v2.entities_schemas import PROFILE_METHODS as ENTITY_METHODS
from app.api.v2.entities_schemas import EntitiesRequest, LinkCheck
from app.api.v2.entities_schemas import Method as EntityMethod
from app.api.v2.knowledge import KnowledgeRequest
from app.api.v2.qa_schemas import PROFILE_METHODS as QA_METHODS
from app.api.v2.qa_schemas import Method as QaMethod
from app.api.v2.qa_schemas import QaRequest
from app.domain.requests import (
    MATCHERS,
    PRESETS,
    ArticleChoice,
    CurriculumCheck,
    Enrichment,
    Extraction,
    GenerateRequest,
    Generation,
    Part,
)
from app.main import create_app
from app.settings import Settings
from app.ui.routes import STATIC_DIR, ui_router

KEY = "k" * 32
REQUESTS: dict[str, type[BaseModel]] = {
    "compendium": GenerateRequest,
    "knowledge": KnowledgeRequest,
    "entities": EntitiesRequest,
    "qa": QaRequest,
}


@pytest.fixture(scope="module")
def ui(settings: Settings) -> TestClient:
    return TestClient(create_app(settings.model_copy(update={"ui_enabled": True})))


@pytest.fixture(scope="module")
def options(ui: TestClient) -> dict[str, Any]:
    answer = ui.get("/ui/options.json")
    assert answer.status_code == 200
    data: dict[str, Any] = answer.json()
    return data


@pytest.mark.parametrize("path", ["/ui", "/ui/", "/ui/options.json", "/ui/main.mjs", "/ui/ui.css"])
def test_the_page_is_off_unless_the_server_switches_it_on(settings: Settings, path: str) -> None:
    client = TestClient(create_app(settings))

    assert client.get(path, follow_redirects=False).status_code == 404


def test_ui_leads_to_the_page_so_its_relative_links_resolve(ui: TestClient) -> None:
    answer = ui.get("/ui", follow_redirects=False)

    assert answer.status_code in (307, 308)
    assert answer.headers["location"].endswith("ui/")


def test_the_page_comes_with_a_policy_that_allows_only_its_own_files(ui: TestClient) -> None:
    answer = ui.get("/ui/")

    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("text/html")
    policy = answer.headers["content-security-policy"]
    assert "default-src 'none'" in policy
    assert "script-src 'self'" in policy
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy
    assert "frame-ancestors 'none'" in policy
    assert answer.headers["x-content-type-options"] == "nosniff"
    assert answer.headers["referrer-policy"] == "no-referrer"


def test_the_page_holds_no_inline_script_or_style_the_policy_would_block() -> None:
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", page), "a script without src runs inline"
    assert "<style" not in page and " style=" not in page
    assert not re.search(r"\son[a-z]+=", page), "an inline event handler"


@pytest.mark.parametrize("name", sorted(path.name for path in STATIC_DIR.glob("*.mjs")))
def test_every_script_is_served_as_javascript(ui: TestClient, name: str) -> None:
    answer = ui.get(f"/ui/{name}")

    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("text/javascript")
    assert "script-src 'self'" in answer.headers["content-security-policy"]


def test_the_stylesheet_is_served_as_css(ui: TestClient) -> None:
    answer = ui.get("/ui/ui.css")

    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("text/css")


@pytest.mark.parametrize("path", ["/ui/", "/ui/main.mjs", "/ui/ui.css"])
def test_a_file_the_browser_holds_comes_back_as_not_modified(ui: TestClient, path: str) -> None:
    """no-cache makes the browser ask again on every visit; with a tag it gets the 24 files back only when they
    changed (audit 2026-09-29, S13)."""
    first = ui.get(path)
    tag = first.headers["etag"]

    again = ui.get(path, headers={"If-None-Match": tag})
    weak = ui.get(path, headers={"If-None-Match": f'"anders", W/{tag}'})
    other = ui.get(path, headers={"If-None-Match": '"anders"'})

    assert again.status_code == 304 and again.content == b""
    assert again.headers["etag"] == tag
    for name in ("content-security-policy", "x-content-type-options", "referrer-policy", "cache-control"):
        assert again.headers[name] == first.headers[name], name
    assert weak.status_code == 304
    assert other.status_code == 200 and other.content == first.content


def test_the_tag_of_a_file_follows_its_content(tmp_path: Path) -> None:
    static = shutil.copytree(STATIC_DIR, tmp_path / "static")
    before = TestClient(_serving(static)).get("/ui/main.mjs").headers["etag"]
    (static / "main.mjs").write_bytes((static / "main.mjs").read_bytes() + b"\n// changed\n")

    after = TestClient(_serving(static)).get("/ui/main.mjs").headers["etag"]
    page = TestClient(_serving(static)).get("/ui/").headers["etag"]

    assert after != before
    assert page != after, "each file has a tag of its own"


def _serving(static: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(ui_router(static))
    return app


@pytest.mark.parametrize(
    "path",
    [
        "/ui/nothing.mjs",
        "/ui/index.html",  # the page is /ui/, its file is no asset
        "/ui/routes.py",
        "/ui/..%2Froutes.py",
        "/ui/%2e%2e/%2e%2e/settings.py",
        "/ui/..%5C..%5Csettings.py",
    ],
)
def test_nothing_but_the_files_of_the_page_is_served(ui: TestClient, path: str) -> None:
    assert ui.get(path).status_code == 404


def test_every_file_the_page_and_its_scripts_name_is_served(ui: TestClient) -> None:
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    named = set(re.findall(r'(?:src|href)="([a-z_]+\.(?:mjs|css))"', page))
    for script in STATIC_DIR.glob("*.mjs"):
        named |= set(re.findall(r"from\s+'\./([a-z_]+\.mjs)'", script.read_text(encoding="utf-8")))

    assert "main.mjs" in named and "ui.css" in named
    missing = [name for name in sorted(named) if ui.get(f"/ui/{name}").status_code != 200]
    assert not missing


def test_the_ui_routes_stay_out_of_the_api_description(ui: TestClient) -> None:
    paths = ui.get("/openapi.json").json()["paths"]

    assert not [path for path in paths if path.startswith("/ui")]


def test_the_page_opens_without_a_key_but_says_the_endpoints_want_one(settings: Settings) -> None:
    keyed = TestClient(create_app(settings.model_copy(update={"ui_enabled": True, "api_keys": KEY})))

    assert keyed.get("/ui/").status_code == 200
    assert keyed.get("/ui/options.json").json()["keys_required"] is True


def test_the_options_name_the_profiles_and_their_switches_as_the_requests_define_them(
    options: dict[str, Any], settings: Settings
) -> None:
    assert [preset["id"] for preset in options["presets"]] == list(PRESETS)
    assert {preset["id"]: preset["switches"] for preset in options["presets"]} == PRESETS
    assert options["preset_default"] == settings.preset_default
    assert options["keys_required"] is False
    assert options["llm_configured"] is False
    assert options["facets_visible"] is settings.facets_visible


@pytest.mark.parametrize(("template", "note"), [("sc26", False), ("standard", True)])
def test_the_box_for_empty_blocks_starts_as_the_default_template_keeps_them(
    settings: Settings, template: str, note: bool
) -> None:
    served = TestClient(create_app(settings.model_copy(update={"ui_enabled": True, "template_default": template})))

    assert served.get("/ui/options.json").json()["empty_note"] is note


def test_the_options_offer_every_value_of_every_switch(options: dict[str, Any]) -> None:
    assert options["switches"] == {
        "article_choice": list(get_args(ArticleChoice)),
        "matcher": list(MATCHERS),
        "extraction": list(get_args(Extraction)),
        "generation": list(get_args(Generation)),
        "enrichment": list(get_args(Enrichment)),
        "curriculum_check": list(get_args(CurriculumCheck)),
    }
    assert options["parts"] == list(get_args(Part))
    assert options["entities"] == {
        "methods": list(get_args(EntityMethod)),
        "link_checks": list(get_args(LinkCheck)),
        "link_check_default": "rule-based",
        "profiles": ENTITY_METHODS,
    }
    assert options["qa"] == {"methods": list(get_args(QaMethod)), "profiles": QA_METHODS}


def test_the_options_carry_the_bounds_of_the_number_fields(options: dict[str, Any]) -> None:
    length = GenerateRequest.model_fields["target_length"]

    assert options["limits"]["compendium"]["target_length"]["default"] == length.default
    assert options["limits"]["compendium"]["target_length"]["min"] == 2_000
    assert options["limits"]["compendium"]["target_length"]["max"] == 60_000
    assert options["limits"]["qa"]["count"] == {"default": 5, "min": 1, "max": 50}
    assert options["limits"]["entities"]["max_entities"] == {"default": 50, "min": 1, "max": 200}


def test_the_curriculum_search_and_the_topic_fields_are_bounded_as_their_endpoints_are(
    ui: TestClient, options: dict[str, Any]
) -> None:
    search = ui.get("/openapi.json").json()["paths"]["/api/v2/lehrplan/search"]["get"]
    query = {parameter["name"]: parameter["schema"] for parameter in search["parameters"]}

    assert options["lehrplan"] == {"modes": query["mode"]["enum"]}
    limit = query["limit"]
    assert options["limits"]["lehrplan"]["limit"] == {
        "default": limit["default"],
        "min": limit["minimum"],
        "max": limit["maximum"],
    }
    assert options["limits"]["lehrplan"]["q"] == {
        "min_length": query["q"]["minLength"],
        "max_length": query["q"]["maxLength"],
    }
    for mode in ("compendium", "knowledge", "qa"):
        (text,) = [
            kind for kind in REQUESTS[mode].model_json_schema()["properties"]["topic"]["anyOf"] if "maxLength" in kind
        ]
        assert options["limits"][mode]["topic"]["max_length"] == text["maxLength"], mode


def test_the_options_list_the_templates_and_the_school_subjects(options: dict[str, Any]) -> None:
    assert {"sc26", "standard"} <= {template["id"] for template in options["templates"]}
    assert "Physik" in options["subjects"]


@pytest.mark.parametrize("mode", sorted(REQUESTS))
def test_every_example_is_a_request_its_endpoint_takes(options: dict[str, Any], mode: str) -> None:
    examples = options["examples"][mode]

    assert examples
    for example in examples:
        assert example["label"]
        REQUESTS[mode].model_validate(example["values"])  # a stale example raises here, as the endpoint's 422 would
        # The service checks the subject itself (a 422 as well); the page offers the school subjects
        assert example["values"].get("subject", "Physik") in options["subjects"]


def test_every_curriculum_example_is_a_search_the_endpoint_takes(ui: TestClient, options: dict[str, Any]) -> None:
    examples = options["examples"]["lehrplan"]

    assert examples
    for example in examples:
        answer = ui.get("/api/v2/lehrplan/search", params=example["values"])
        assert answer.status_code != 422, (example, answer.json())
        assert example["values"].get("subject", "Physik") in options["subjects"]
