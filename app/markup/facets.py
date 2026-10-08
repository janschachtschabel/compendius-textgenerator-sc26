"""The facets as the text writes them: the marker of a block, its visible short form, the values of a level.

``format_marker`` and ``parse_marker`` write and read the inside of ``<!-- f: … -->``; parts 2 and 3 close their blocks
with ``END_MARKER``. Which facets a block gets is the synthesis' (app/synthesis/facets.py).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from app.markup.safe_markdown import plain_label


def format_visible(facets: Mapping[str, Sequence[str]]) -> str:
    """Visible short form used only when FACETS_VISIBLE is enabled; a name or value from a template or a source shows
    as typed."""
    return " ".join(
        f"[{plain_label(name)}: {', '.join(plain_label(value) for value in values)}]"
        for name, values in facets.items()
        if values
    )


# The marker's own syntax as a name or value holds it: pair, name and value separators, the ends of its HTML comment
# and the quotes of the attribute a block marker holds it in. "%" is encoded as well, so that every escape reads back
# as the sign it stands for: "A;B" and "A%3BB" wrote the same marker, and a quote hid the whole block from a
# regeneration (audit 2026-09-29, A01, A12). A marker written before holds "%" as typed; read back, only the seven
# escapes below turn into their sign, so such a value changes only where it held one of them itself.
_MARKER_ESCAPES = {"%": "%25", ";": "%3B", "=": "%3D", "|": "%7C", "<": "%3C", ">": "%3E", '"': "%22"}
_MARKER_ESCAPE = str.maketrans(_MARKER_ESCAPES)
_MARKER_SIGNS = {code: sign for sign, code in _MARKER_ESCAPES.items()}
_MARKER_CODE = re.compile("|".join(_MARKER_SIGNS))


def _marker_text(text: str) -> str:
    return " ".join(text.split()).translate(_MARKER_ESCAPE)


def _marker_read(text: str) -> str:
    return _MARKER_CODE.sub(lambda code: _MARKER_SIGNS[code.group(0)], text)


def format_marker(facets: Mapping[str, Sequence[str]]) -> str:
    """The inside of a facet marker, ``name=value|value; name=value``, on one line whatever a name or value holds.
    Values come from sources editors type into, names from templates: a line break would end the marker early, and
    ``;``, ``=``, ``|``, ``<``, ``>`` and ``"`` would add a pair, split a value, end the comment or the attribute, so
    they are percent-encoded, as is ``%`` itself (``parse_marker`` reads it back)."""
    return "; ".join(
        f"{_marker_text(name)}=" + "|".join(_marker_text(value) for value in values)
        for name, values in facets.items()
        if values
    )


def parse_marker(marker: str) -> dict[str, list[str]]:
    """The facets of a marker as ``format_marker`` wrote them (``Name=Wert|Wert; Name=Wert``)."""
    facets: dict[str, list[str]] = {}
    for part in marker.split("; "):
        name, _, values = part.partition("=")
        if name.strip() and values:
            facets[_marker_read(name.strip())] = [_marker_read(value) for value in values.split("|") if value]
    return facets


# Closes a facet block in parts 2 and 3 (``<!-- f: … -->`` … ``<!-- /f -->``), so blocks can be parsed out
END_MARKER = "<!-- /f -->"

_BILDUNGSSTUFE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"elementar|kita|vorschul", re.I), "Elementar"),
    (re.compile(r"primar|grundschul", re.I), "Primar"),
    (re.compile(r"sek(undar)?(bereich|stufe)?\s*(ii|2)\b|oberstufe", re.I), "Sek II"),
    (re.compile(r"sek(undar)?(bereich|stufe)?\s*(i|1)\b", re.I), "Sek I"),
    (re.compile(r"hochschul|universit", re.I), "Hochschule"),
    (re.compile(r"beruf", re.I), "Berufliche Bildung"),
    (re.compile(r"erwachsen|fortbildung|weiterbildung", re.I), "Erwachsenenbildung"),
)


def bildungsstufe_facet(label: str) -> str | None:
    """The facet value (config/facets.yaml) for a level as MEM, edu-sharing or OpenEduHub name it.

    The OpenEduHub vocabulary names a level three ways - prefLabel, altLabel and the concept URI
    (``.../educationalContext/sekundarstufe_1``). The labels read as they are; the URI does not,
    because its underscore is no whitespace, so the last path segment is unpacked first.
    """
    if "/" in label:
        label = label.rstrip("/").rsplit("/", 1)[-1]
    label = label.replace("_", " ")
    for pattern, value in _BILDUNGSSTUFE_RULES:
        if pattern.search(label):
            return value
    return None
