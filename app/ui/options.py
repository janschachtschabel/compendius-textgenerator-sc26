"""What the review page offers (D66): the values of every switch, the bounds of the number fields, and examples.

The lists come from the models of the endpoints, so the page never offers a value they refuse. The examples are
requests on the archives every installation has and on the WLO staging repository; tests/test_ui.py checks each one
against the model of its endpoint.
"""

from __future__ import annotations

from typing import Any, get_args

from pydantic import BaseModel

from app.api.v2.entities_schemas import PROFILE_METHODS as ENTITY_METHODS
from app.api.v2.entities_schemas import EntitiesRequest, LinkCheck
from app.api.v2.entities_schemas import Method as EntityMethod
from app.api.v2.knowledge import KnowledgeRequest
from app.api.v2.nodes import STAGING_COLLECTION, STAGING_MATERIAL, STAGING_REPOSITORY
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
from app.settings import Settings
from app.sources.lehrplan.subjects import SubjectCatalog
from app.templates.manager import TemplateManager

# The steps of a compendium in the order they run, each with the values a request may set
SWITCHES: dict[str, list[str]] = {
    "article_choice": list(get_args(ArticleChoice)),
    "matcher": list(MATCHERS),
    "extraction": list(get_args(Extraction)),
    "generation": list(get_args(Generation)),
    "enrichment": list(get_args(Enrichment)),
    "curriculum_check": list(get_args(CurriculumCheck)),
}
_STAGING_NODE = {"repository": STAGING_REPOSITORY}
EXAMPLES: dict[str, list[dict[str, Any]]] = {
    "compendium": [
        {"label": "Optik – ein Thema", "values": {"topic": "Optik", "parts": ["world", "curricula"]}},
        {"label": "Linse – ein Wort mit mehreren Bedeutungen", "values": {"topic": "Linse", "subject": "Physik"}},
        {"label": "Klimawandel mit Fach Geografie", "values": {"topic": "Klimawandel", "subject": "Geografie"}},
        {"label": "Sammelthema: deutsche Dichter", "values": {"topic": "deutsche Dichter", "parts": ["world"]}},
        {
            "label": "Optik mit ihrer Sammlung (Staging, alle drei Teile)",
            "values": {
                "topic": "Optik",
                "collection_id": STAGING_COLLECTION,
                "parts": ["world", "curricula", "collection"],
            },
        },
        {
            "label": "Optik mit der Sammlung als Quelle (Staging)",
            "values": {"topic": "Optik", "knowledge_collection_id": STAGING_COLLECTION, "parts": ["world"]},
        },
        {
            "label": "Ein Material als Eingang (Staging)",
            "values": {"node_id": STAGING_MATERIAL, **_STAGING_NODE, "parts": ["world", "curricula"]},
        },
    ],
    "knowledge": [
        {"label": "Optik", "values": {"topic": "Optik"}},
        {
            "label": "Französische Revolution, höchstens fünf Artikel",
            "values": {"topic": "Französische Revolution", "max_articles": 5},
        },
        {"label": "Thema aus der Sammlung Optik (Staging)", "values": {"node_id": STAGING_COLLECTION, **_STAGING_NODE}},
    ],
    "lehrplan": [
        {
            "label": "Optik in Physik – wie Teil 2 eines Kompendiums",
            "values": {"q": "Optik", "subject": "Physik", "mode": "topic"},
        },
        {"label": "Stichwort Bruchrechnung", "values": {"q": "Bruchrechnung", "mode": "keyword"}},
        {
            "label": "Stichwort Demokratie in Politik",
            "values": {"q": "Demokratie", "subject": "Politik", "mode": "keyword"},
        },
    ],
    "entities": [
        {
            "label": "Ein Satz mit Namen und Orten",
            "values": {"text": "Alexander von Humboldt reiste 1799 nach Südamerika und bestieg den Chimborazo."},
        },
        {
            "label": "Titel und Beschreibung eines Materials (Staging)",
            "values": {"node_id": STAGING_MATERIAL, **_STAGING_NODE},
        },
    ],
    "qa": [
        {"label": "Optik, fünf Paare", "values": {"topic": "Optik", "count": 5}},
        {"label": "Albert Einstein, zehn Paare", "values": {"topic": "Albert Einstein", "count": 10}},
        {
            "label": "Thema aus der Sammlung Optik (Staging)",
            "values": {"node_id": STAGING_COLLECTION, **_STAGING_NODE, "count": 5},
        },
        {
            "label": "Ein eigener kurzer Text",
            "values": {
                "text": "Die Sonne erwärmt das Wasser der Meere, Seen und Flüsse. Es verdunstet und steigt als "
                "Wasserdampf auf. In der Höhe kühlt der Dampf ab, bildet Wolken und fällt als Regen oder Schnee zurück "
                "auf die Erde.",
                "count": 3,
            },
        },
    ],
}


def _bounds(model: type[BaseModel], name: str) -> dict[str, Any]:
    """Default, lowest and highest value of a number field, as its model declares them (Field ge and le)."""
    field = model.model_fields[name]
    bounds: dict[str, Any] = {"default": field.default}
    for rule in field.metadata:
        if getattr(rule, "ge", None) is not None:
            bounds["min"] = rule.ge
        if getattr(rule, "le", None) is not None:
            bounds["max"] = rule.le
    return bounds


LIMITS = {
    "compendium": {name: _bounds(GenerateRequest, name) for name in ("target_length", "max_articles")},
    "knowledge": {name: _bounds(KnowledgeRequest, name) for name in ("max_articles", "max_chars")},
    "entities": {"max_entities": _bounds(EntitiesRequest, "max_entities")},
    "qa": {name: _bounds(QaRequest, name) for name in ("count", "max_answer_length")},
}


def ui_options(
    settings: Settings, templates: TemplateManager, subjects: SubjectCatalog, *, llm: bool
) -> dict[str, Any]:
    """Everything the page needs to know of this server: the profiles and switches, what the server has, examples."""
    return {
        "preset_default": settings.preset_default,
        "keys_required": bool(settings.api_key_list),
        "llm_configured": llm,  # without an LLM every profile but llm-free is a 503 (D53)
        "facets_visible": settings.facets_visible,
        "presets": [{"id": preset, "switches": switches} for preset, switches in PRESETS.items()],
        "switches": SWITCHES,
        "parts": list(get_args(Part)),
        "templates": [{"id": t.id, "name": t.name, "slots": len(t.slots)} for t in templates.list()],
        "subjects": subjects.school_subjects(),
        "entities": {
            "methods": list(get_args(EntityMethod)),
            "link_checks": list(get_args(LinkCheck)),
            "profiles": ENTITY_METHODS,
        },
        "qa": {"methods": list(get_args(QaMethod)), "profiles": QA_METHODS},
        "limits": LIMITS,
        "examples": EXAMPLES,
    }
