"""edu-sharing payloads (frozen from the WLO repository, 2026-09-17) become collection, material and sub-collection records."""

import json
from pathlib import Path

from app.sources.wlo.models import (
    is_extractive,
    license_label,
    parse_collection,
    parse_reference,
    parse_subcollection,
)

FIX = Path(__file__).parent / "fixtures" / "wlo"


def _load(name: str) -> dict:  # type: ignore[type-arg]
    data: dict = json.loads((FIX / name).read_text(encoding="utf-8"))  # type: ignore[type-arg]
    return data


def test_collection_info_from_the_repository_payload() -> None:
    info = parse_collection(_load("collection_optik.json"))
    assert info.id == "9e7ae956-e9df-430f-bace-f3db4b910013" and info.title == "Optik"
    assert info.description.startswith("Die Physik des Lichts")
    assert info.subject_uris == ("http://w3id.org/openeduhub/vocabs/discipline/460",)
    assert info.subject_labels == ("Physik",) and info.educational_contexts == ("Sekundarstufe I",)
    assert "Wellenoptik" in info.keywords
    assert info.collection_type == "EDITORIAL" and not info.is_topic_page
    assert info.modified_at.startswith("2026-03-04")


def test_reference_parsing_prefers_display_names_and_the_material_url() -> None:
    ref = parse_reference(_load("references_optik_page1.json")["references"][0])
    assert ref.title == "Optik" and ref.original_id is not None and ref.original_id.startswith("4bfa7693")
    assert ref.resource_types == ("Fachliche News",)
    assert ref.educational_contexts == ("Sekundarstufe I",) and ref.subjects == ("Physik",)
    assert ref.license_key == "CC_BY_NC_SA" and ref.url == "https://www.geogebra.org/m/PzBHcpNG"
    assert ref.description == "Faszinierende Phänomene aus der Optik" and "Spiegel" in ref.keywords


def test_reference_without_www_url_falls_back_to_the_render_url() -> None:
    node = _load("references_optik_page1.json")["references"][0]
    node["properties"].pop("ccm:wwwurl")
    assert parse_reference(node).url.startswith("https://redaktion.openeduhub.net/edu-sharing/components/render/")


def test_subcollections_from_the_payload() -> None:
    subs = [parse_subcollection(node) for node in _load("subcollections_optik.json")["collections"]]
    assert [sub.title for sub in subs] == ["Geometrische Optik", "Farben", "Wellenoptik", "Menschliches Auge"]
    assert all(len(sub.id) == 36 for sub in subs)


def test_license_policy_allows_only_verbatim_reuse_licenses() -> None:
    assert is_extractive("CC_0") and is_extractive("PDM") and is_extractive("CC_BY") and is_extractive("CC_BY_SA")
    assert not is_extractive("CC_BY_NC_SA") and not is_extractive("COPYRIGHT_FREE") and not is_extractive("")
    assert license_label("CC_BY_SA") == "CC BY-SA 4.0" and license_label("CC_0") == "CC0 1.0"
    assert license_label("COPYRIGHT_FREE") == "frei zugänglich (keine OER-Lizenz)"
    assert license_label("SOMETHING_NEW") == "SOMETHING_NEW"
