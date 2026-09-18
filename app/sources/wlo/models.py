"""Records read from edu-sharing collections (PLAN.md 6.1) and the licence policy for verbatim reuse (6.3).

Field names follow what the WLO repository returned on 2026-09-17 (``tests/fixtures/wlo``): vocabulary
values come as URIs with a ``*_DISPLAYNAME`` twin, the material link sits in ``ccm:wwwurl`` or, for
uploaded files, in the render URL, and a collection member is a reference node with ``originalId``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# ccm:commonlicense_key values that allow verbatim (extractive) reuse in the compendium (PLAN.md 6.3).
# COPYRIGHT_FREE means "freely accessible", not "free to reuse", and stays out.
EXTRACTIVE_LICENSES = frozenset({"CC_0", "PDM", "CC_BY", "CC_BY_SA"})

LICENSE_LABELS = {
    "CC_0": "CC0 1.0",
    "PDM": "Public Domain Mark",
    "CC_BY": "CC BY 4.0",
    "CC_BY_SA": "CC BY-SA 4.0",
    "CC_BY_ND": "CC BY-ND 4.0",
    "CC_BY_NC": "CC BY-NC 4.0",
    "CC_BY_NC_SA": "CC BY-NC-SA 4.0",
    "CC_BY_NC_ND": "CC BY-NC-ND 4.0",
    "COPYRIGHT_FREE": "frei zugänglich (keine OER-Lizenz)",
    "COPYRIGHT_LICENSE": "urheberrechtlich geschützt",
    "CUSTOM": "eigene Lizenzbedingungen",
    "SCHULFUNK": "Schulfunk (§ 47 UrhG)",
    "UNTERRICHTS_UND_LEHRMEDIEN": "Unterrichts- und Lehrmedien (§ 60b UrhG)",
    "": "ohne Lizenzangabe",
}


def is_extractive(license_key: str) -> bool:
    return license_key in EXTRACTIVE_LICENSES


def license_label(license_key: str) -> str:
    return LICENSE_LABELS.get(license_key, license_key)


@dataclass(frozen=True)
class SubCollection:
    id: str
    title: str
    description: str


@dataclass(frozen=True)
class MaterialRef:
    """One member of a collection: the reference node with the metadata it inherits from the original."""

    id: str
    title: str
    description: str
    url: str
    original_id: str | None
    license_key: str
    mimetype: str | None
    keywords: tuple[str, ...]
    resource_types: tuple[str, ...]
    educational_contexts: tuple[str, ...]
    subjects: tuple[str, ...]
    subject_uris: tuple[str, ...]


@dataclass(frozen=True)
class CollectionInfo:
    id: str
    title: str
    description: str
    keywords: tuple[str, ...]
    subject_uris: tuple[str, ...]
    subject_labels: tuple[str, ...]
    educational_contexts: tuple[str, ...]
    collection_type: str
    modified_at: str
    is_topic_page: bool


def _values(props: Mapping[str, Any], key: str) -> list[str]:
    value = props.get(key)
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if value in (None, ""):
        return []
    return [str(value)]


def _first(props: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        values = _values(props, key)
        if values:
            return values[0].strip()
    return ""


def _labels(props: Mapping[str, Any], key: str) -> tuple[str, ...]:
    """Display names where the repository resolves them, else the last URI segment."""
    display = _values(props, f"{key}_DISPLAYNAME")
    if display:
        return tuple(display)
    return tuple(uri.rstrip("/").rsplit("/", 1)[-1] for uri in _values(props, key))


def _title(node: Mapping[str, Any], props: Mapping[str, Any]) -> str:
    title = str(node.get("title") or "").strip()
    return title or _first(props, "cclom:title", "cm:title") or str(node.get("name") or "")


def parse_collection(payload: Mapping[str, Any]) -> CollectionInfo:
    node = payload.get("collection", payload)
    props: Mapping[str, Any] = node.get("properties") or {}
    return CollectionInfo(
        id=str((node.get("ref") or {}).get("id") or ""),
        title=_title(node, props),
        description=_first(props, "cm:description", "cclom:general_description"),
        keywords=tuple(_values(props, "cclom:general_keyword")),
        subject_uris=tuple(_values(props, "ccm:taxonid")),
        subject_labels=_labels(props, "ccm:taxonid"),
        educational_contexts=_labels(props, "ccm:educationalcontext"),
        collection_type=_first(props, "ccm:collectiontype"),
        modified_at=str(node.get("modifiedAt") or ""),
        is_topic_page=bool(_values(props, "ccm:page_config_ref")),
    )


def parse_reference(node: Mapping[str, Any]) -> MaterialRef:
    props: Mapping[str, Any] = node.get("properties") or {}
    url = _first(props, "ccm:wwwurl") or str((node.get("content") or {}).get("url") or "")
    return MaterialRef(
        id=str((node.get("ref") or {}).get("id") or ""),
        title=_title(node, props),
        description=_first(props, "cclom:general_description", "cm:description"),
        url=url,
        original_id=node.get("originalId") or None,
        license_key=_first(props, "ccm:commonlicense_key"),
        mimetype=node.get("mimetype") or None,
        keywords=tuple(_values(props, "cclom:general_keyword")),
        resource_types=_labels(props, "ccm:oeh_lrt"),
        educational_contexts=_labels(props, "ccm:educationalcontext"),
        subjects=_labels(props, "ccm:taxonid"),
        subject_uris=tuple(_values(props, "ccm:taxonid")),
    )


def parse_subcollection(node: Mapping[str, Any]) -> SubCollection:
    props: Mapping[str, Any] = node.get("properties") or {}
    return SubCollection(
        id=str((node.get("ref") or {}).get("id") or ""),
        title=_title(node, props),
        description=_first(props, "cm:description", "cclom:general_description"),
    )
