"""Subscription manifest (PLAN.md 4.1): which archives a profile keeps current.

The manifest lives in ``config/zim_subscriptions.yaml``; nothing about concrete archives is
curated in code. A subscription id is ``name_flavour`` and equals the archive file name without
its date, so it matches ``archive_id()`` of local files and the catalog's ``name``/``flavour``.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from app.sources.zim.archive import archive_id


class Subscription(BaseModel):
    """One archive to keep current, and the profiles that include it."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    name: str = Field(min_length=1, description="Catalog name, e.g. wikipedia_de_all")
    flavour: str = Field("", description="Catalog flavour, e.g. nopic; empty when the archive has none")
    project: str = Field(min_length=1, description="wikipedia, klexikon, wikibooks, ... (see archive.py)")
    required: bool = Field(False, description="Readiness of the service depends on this archive")
    profiles: list[str] = Field(min_length=1)
    description: str = ""

    @model_validator(mode="after")
    def _id_matches_name_and_flavour(self) -> Subscription:
        expected = f"{self.name}_{self.flavour}" if self.flavour else self.name
        if self.id != expected:
            raise ValueError(f"id {self.id!r} must be name_flavour, i.e. {expected!r}")
        return self

    @property
    def file_prefix(self) -> str:
        return f"{self.id}_"

    def matches_file(self, file_name: str) -> bool:
        return archive_id(file_name) == self.id


class SubscriptionManifest(BaseModel):
    version: int = 1
    profiles: dict[str, str] = Field(description="profile name -> description")
    subscriptions: list[Subscription]

    @model_validator(mode="after")
    def _ids_unique_and_profiles_known(self) -> SubscriptionManifest:
        seen: set[str] = set()
        for sub in self.subscriptions:
            if sub.id in seen:
                raise ValueError(f"duplicate subscription id {sub.id!r}")
            seen.add(sub.id)
            unknown = [p for p in sub.profiles if p not in self.profiles]
            if unknown:
                raise ValueError(f"subscription {sub.id!r} references unknown profile(s) {unknown}")
        return self

    def for_profile(self, profile: str) -> list[Subscription]:
        """Subscriptions of a profile in manifest order; unknown profiles raise ``KeyError``."""
        if profile not in self.profiles:
            raise KeyError(profile)
        return [s for s in self.subscriptions if profile in s.profiles]

    def required_ids(self, profile: str) -> list[str]:
        return [s.id for s in self.for_profile(profile) if s.required]

    def by_id(self, subscription_id: str) -> Subscription | None:
        return next((s for s in self.subscriptions if s.id == subscription_id), None)


def load_manifest(path: Path) -> SubscriptionManifest:
    """Read and validate a manifest file; raises ``ValueError`` on structural errors."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return SubscriptionManifest.model_validate(data)
