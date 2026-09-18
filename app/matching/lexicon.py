"""Heading lexicon (PLAN.md 4.4, stage 1): deterministic heading -> slot classification."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from app.templates.schema import Template


def _compile(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


class HeadingLexicon:
    """Maps section headings to slot keys with regular expressions; no topic knowledge."""

    def __init__(
        self,
        slots: dict[str, list[re.Pattern[str]]],
        exclude: list[re.Pattern[str]],
        relations: list[re.Pattern[str]],
        version: int = 0,
    ) -> None:
        self._slots = slots
        self._exclude = exclude
        self._relations = relations
        self.version = version

    @classmethod
    def load(cls, path: Path) -> HeadingLexicon:
        raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        slots_raw: dict[str, list[str]] = raw.get("slots", {}) or {}
        return cls(
            slots={key: _compile(list(patterns)) for key, patterns in slots_raw.items()},
            exclude=_compile(list(raw.get("exclude", []) or [])),
            relations=_compile(list(raw.get("relations", []) or [])),
            version=int(raw.get("version", 0) or 0),
        )

    @classmethod
    def empty(cls) -> HeadingLexicon:
        return cls(slots={}, exclude=[], relations=[])

    def with_template(self, template: Template) -> HeadingLexicon:
        """Return a copy extended by the template's own heading patterns."""
        slots = {key: list(patterns) for key, patterns in self._slots.items()}
        for slot in template.slots:
            if slot.heading_patterns:
                slots.setdefault(slot.slot, []).extend(_compile(slot.heading_patterns))
        return HeadingLexicon(
            slots=slots, exclude=list(self._exclude), relations=list(self._relations), version=self.version
        )

    @staticmethod
    def _clean(heading: str) -> str:
        return re.sub(r"\s+", " ", heading).strip(" :")

    def classify(self, heading_path: list[str]) -> str | None:
        """Deepest heading first, then parents; first slot whose pattern matches wins."""
        for heading in reversed(heading_path):
            clean = self._clean(heading)
            for key, patterns in self._slots.items():
                if any(p.search(clean) for p in patterns):
                    return key
        return None

    def is_excluded(self, heading_path: list[str]) -> bool:
        return any(p.search(self._clean(h)) for h in heading_path for p in self._exclude)

    def is_relation(self, heading_path: list[str]) -> bool:
        return any(p.search(self._clean(h)) for h in heading_path for p in self._relations)

    @property
    def slot_keys(self) -> list[str]:
        return list(self._slots)
