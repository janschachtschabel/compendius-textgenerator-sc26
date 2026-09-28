"""One spelling for the same text (audit 2026-09-28, KO-28).

Text from macOS file names or PDF copies carries umlauts decomposed (NFD: a letter and a combining diaeresis): the
tokenizer split "Wärme" into "rme", the title finder found "Wa" and "Gro" instead of "Wärmeleitung" and "Größe", and a
topic spelled so reached its article only by the archive's unsure suggestion. A soft hyphen or a zero-width space from
a copied page split a name the same way. Text is therefore composed (NFC) and loses the invisible format signs
(Unicode category Cf) where it enters: the fields of a request and the metadata and text of a repository node. The
archives are composed already.
"""

from __future__ import annotations

import unicodedata
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationInfo, ValidatorFunctionWrapHandler, field_validator


def readable(text: str) -> str:
    """``text`` composed (NFC) and without invisible format signs: soft hyphen, zero-width space and joiners, direction
    marks. The signs go first, so that a letter and the accent they kept apart compose."""
    if text.isascii():  # no format sign is ASCII, and ASCII is composed
        return text
    return unicodedata.normalize("NFC", "".join(char for char in text if unicodedata.category(char) != "Cf"))


def readable_value(value: Any) -> Any:
    """A caller's value in one spelling when it is text, anything else as it came: for query parameters, whose length
    is bounded before the request reaches the service."""
    return readable(value) if isinstance(value, str) else value


class OneSpelling(BaseModel):
    """A model whose text fields hold what a reader sees, in one spelling (see ``readable``).

    Every string field and every string in a list field is read so, except the ``VERBATIM_FIELDS`` of a model. A value
    of invisible signs only is refused rather than read as empty.
    """

    VERBATIM_FIELDS: ClassVar[frozenset[str]] = frozenset()

    @field_validator("*", mode="wrap")
    @classmethod
    def _readable_text(cls, value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo) -> Any:
        if info.field_name in cls.VERBATIM_FIELDS:
            return handler(value)
        # Composed before the bounds, so they count what the service reads; normalize runs in C. The format signs go
        # after the bounds, from a value of bounded length: that loop runs in Python.
        checked = handler(unicodedata.normalize("NFC", value) if isinstance(value, str) else value)
        if isinstance(checked, str):
            plain = readable(checked)
            if checked and not plain:
                raise ValueError("besteht nur aus unsichtbaren Formatzeichen")
            return plain
        if isinstance(checked, list):
            return [readable(item) if isinstance(item, str) else item for item in checked]
        return checked
