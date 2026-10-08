"""The projects the sources come from and what their licences allow: part 1 passes a text on under CC BY-SA 4.0
only from a free licence, and a licence with NC or ND is still open to read."""

from __future__ import annotations

import re

PROJECT_LABELS = {
    "wikipedia": ("Wikipedia", "Nachschlagewerk", "Wikipedia-Autorinnen und -Autoren", "hoch"),
    "klexikon": ("Klexikon", "Nachschlagewerk (einfache Sprache)", "Klexikon-Autorinnen und -Autoren", "hoch"),
    "wikibooks": ("Wikibooks", "Grundlagenwerk", "Wikibooks-Autorinnen und -Autoren", "mittel"),
    "wikiversity": ("Wikiversity", "Grundlagenwerk (Hochschule)", "Wikiversity-Autorinnen und -Autoren", "mittel"),
    "wlo_material": ("WirLernenOnline", "Sammlung & Archiv", "nicht angegeben", "mittel"),
}


# The licences of texts part 1 may pass on under CC BY-SA 4.0: the public domain, CC BY and CC BY-SA. A knowledge
# collection brings materials of any licence since D70; the block called them all free (audit 2026-10-02, A09)
_FREE_LICENCE = re.compile(r"CC0 1\.0|Public Domain Mark|CC BY(-SA)?( \d(\.\d)?)?")


def is_free(licence: str) -> bool:
    """Whether a licence, as ``Source.license`` names it, lets part 1 pass the text on under CC BY-SA 4.0."""
    return _FREE_LICENCE.fullmatch(licence.strip()) is not None


# Access is not the licence: a CC licence with NC or ND publishes the text openly and restricts its use, and the
# repository says "frei zugänglich (keine OER-Lizenz)" outright (app/sources/wlo/models.py). In the Optik collection
# of the staging 12 of 13 materials without a free licence were one of them, the thirteenth names no licence
# (2026-10-03); only there access is unknown and the lint names the missing facet.
FREELY_ACCESSIBLE = ("CC", "Public Domain Mark", "frei zugänglich")


def freely_accessible(licence: str) -> bool:
    """Whether anyone may read a source with this licence, as ``Source.license`` names it."""
    return licence.strip().startswith(FREELY_ACCESSIBLE)
