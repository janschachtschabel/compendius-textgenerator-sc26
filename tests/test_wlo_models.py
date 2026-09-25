"""edu-sharing payloads (frozen from the WLO repository, 2026-09-17) become collection, material and sub-collection records."""

import json
from pathlib import Path

from app.sources.wlo.models import (
    is_extractive,
    license_label,
    parse_collection,
    parse_node,
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


UNIVERSITY = "http://w3id.org/openeduhub/vocabs/hochschulfaechersystematik/"
PHYSIK = "http://w3id.org/openeduhub/vocabs/discipline/460"


def test_subjects_take_the_university_field_too() -> None:
    """ccm:taxonid holds school and university subjects; ccm:oeh_taxonid_university repeats the university ones and may
    name one of its own (Jan, 2026-09-25). Every subject counts once; the labels stay the repository's display names."""
    payload = _load("collection_optik.json")
    payload.get("collection", payload)["properties"]["ccm:oeh_taxonid_university"] = [UNIVERSITY + "n5", PHYSIK]
    info = parse_collection(payload)
    assert info.subject_uris == (PHYSIK, UNIVERSITY + "n5") and info.subject_labels == ("Physik",)
    props = {
        "ccm:taxonid": [UNIVERSITY + "n5"],
        "ccm:taxonid_DISPLAYNAME": ["Humanmedizin/Gesundheitswissenschaften"],
        "ccm:oeh_taxonid_university": [UNIVERSITY + "n5", UNIVERSITY + "n9"],
    }
    node = parse_node({"node": {"ref": {"id": "x"}, "properties": props}})
    assert node.subject_uris == (UNIVERSITY + "n5", UNIVERSITY + "n9")
    assert node.subject_labels == ("Humanmedizin/Gesundheitswissenschaften",)


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
    assert license_label("CC_BY_SA", "3.0") == "CC BY-SA 3.0" and license_label("CC_0") == "CC0 1.0"
    assert license_label("CC_BY_SA") == "CC BY-SA"  # no version recorded, none invented
    assert license_label("COPYRIGHT_FREE") == "frei zugänglich (keine OER-Lizenz)"
    assert license_label("SOMETHING_NEW") == "SOMETHING_NEW"


def test_reference_carries_licence_version_and_authors() -> None:
    node = {
        "ref": {"id": "11111111-1111-4111-8111-111111111111"},
        "properties": {
            "ccm:commonlicense_key": ["CC_BY_SA"],
            "ccm:commonlicense_cc_version": ["3.0"],
            "ccm:lifecyclecontributer_authorFN": ["Dieter Welz", ""],
            "ccm:author_freetext": ["Dieter Welz", "Schulphysik Ulm"],
        },
    }
    ref = parse_reference(node)
    assert ref.license_version == "3.0"
    assert ref.authors == ("Dieter Welz",)  # the structured author wins; the free text only repeats it here
    freetext_only = {**node, "properties": {"ccm:author_freetext": ["Schulphysik Ulm", "Schulphysik Ulm", ""]}}
    assert parse_reference(freetext_only).authors == ("Schulphysik Ulm",)
    assert parse_reference({"ref": {"id": "x"}, "properties": {}}).authors == ()


def test_author_names_are_one_line_each() -> None:
    # A line break in a name would break the TULLU line of the sources block
    node = {"ref": {"id": "x"}, "properties": {"ccm:author_freetext": ["Dieter\nWelz,\r\n  Ulm", "Dieter Welz, Ulm"]}}
    assert parse_reference(node).authors == ("Dieter Welz, Ulm",)


def test_titles_are_one_line() -> None:
    # A line break in a title would break the TULLU line of part 1 and the lists and headings of part 3
    node = {"ref": {"id": "x"}, "title": "Licht\nund  Schatten\r\n", "properties": {}}
    assert parse_reference(node).title == "Licht und Schatten"
    collection = {"ref": {"id": "y"}, "title": "", "properties": {"cclom:title": ["Optik\n  Klasse 7"]}}
    assert parse_collection({"collection": collection}).title == "Optik Klasse 7"


def test_the_node_id_of_a_material_is_the_original_not_the_reference() -> None:
    """A collection member is a reference node; the material itself lives under ``originalId``. The repository
    resolves the original to the real material (its preview knows the type), so that is the id to publish."""
    node = _load("references_optik_page1.json")["references"][0]
    ref = parse_reference(node)
    assert ref.id == "f1f89a13-37de-4a8f-94a2-603bf431b99b"
    assert ref.node_id == "4bfa7693-0764-4dca-9720-c5fb0b8892d6" == ref.original_id


def test_a_reference_without_an_original_falls_back_to_its_own_id() -> None:
    node = _load("references_optik_page1.json")["references"][0]
    node.pop("originalId")
    ref = parse_reference(node)
    assert ref.original_id is None and ref.node_id == ref.id
