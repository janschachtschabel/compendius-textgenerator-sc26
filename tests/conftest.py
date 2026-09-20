"""Offline test fixtures: sample ZIM archives built from committed article HTML."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import pytest
from libzim.writer import Creator, Hint, Item, StringProvider

from app.main import build_service
from app.service import CompendiumService
from app.settings import Settings
from app.sources.zim.registry import ZimRegistry
from app.templates.manager import TemplateManager

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "zim_html"
MANIFEST: dict[str, Any] = json.loads((FIXTURES / "MANIFEST.json").read_text(encoding="utf-8"))

SAMPLE_META = {
    "wikipedia": {
        "file": "wikipedia_de_sample_2026-01.zim",
        "Name": "wikipedia_de_sample",
        "Title": "Wikipedia",
        "Creator": "Wikipedia",
        "Publisher": "openZIM",
        "Date": "2026-01-15",
        "Description": "Sample of the German Wikipedia for offline tests",
        "Language": "deu",
        "Flavour": "nopic",
        "Tags": "wikipedia;_category:wikipedia;_pictures:no;_ftindex:yes",
        "redirects": [
            ("Lichtlehre", "Lichtlehre", "Optik"),
            ("Strahlenoptik", "Strahlenoptik", "Geometrische_Optik"),
            # A plain word whose entry is a disambiguation page, as "Brechung" really is in the German
            # Wikipedia: the title lookup finds it, the article behind it proves nothing (docs/umbau.md U3b)
            ("Brechung", "Brechung", "Optik_(Begriffsklärung)"),
        ],
    },
    "klexikon": {
        "file": "klexikon_de_sample_2026-08.zim",
        "Name": "klexikon_de_sample",
        "Title": "Klexikon – das Kinderlexikon",
        "Creator": "Klexikon",
        "Publisher": "openZIM",
        "Date": "2026-08-07",
        "Description": "Sample of Klexikon for offline tests",
        "Language": "deu",
        "Flavour": "maxi",
        "Tags": "zum;_ftindex:yes",
        "redirects": [],
    },
}


def pytest_configure(config: pytest.Config) -> None:
    """Tests never see the developer's shell configuration or a local ``.env``.

    ``Settings`` reads the environment case-insensitively; a B_API_KEY, LLM_ENABLED, MODEL2VEC_PATH or POLICY_* from
    the shell would otherwise reach the real b-api or change calibrated results. The same goes for a ``.env`` in the
    working directory, which ``get_settings()`` reads for the CLI commands. Tests that need a variable set it with
    ``monkeypatch.setenv``.
    """
    fields = {name.lower() for name in Settings.model_fields}
    for key in [key for key in os.environ if key.lower() in fields]:
        del os.environ[key]
    Settings.model_config["env_file"] = None


def strings_in(value: Any) -> Iterator[str]:
    """Every string of a JSON answer, keys included.

    Path checks look at these instead of ``str(answer)``: the repr of a dict doubles the backslashes of Windows
    paths, so a leaked path would never match.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from strings_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings_in(item)


class HtmlItem(Item):
    def __init__(self, path: str, title: str, html: str) -> None:
        super().__init__()
        self._path = path
        self._title = title
        self._html = html

    def get_path(self) -> str:
        return self._path

    def get_title(self) -> str:
        return self._title

    def get_mimetype(self) -> str:
        return "text/html"

    def get_contentprovider(self) -> StringProvider:
        return StringProvider(self._html)

    def get_hints(self) -> dict[Hint, int]:
        return {Hint.FRONT_ARTICLE: True}


def fixture_entries(project: str) -> list[dict[str, str]]:
    return [e for e in MANIFEST["entries"] if e["project"] == project]


def build_sample_zim(out: Path, project: str) -> Path:
    meta = SAMPLE_META[project]
    entries = fixture_entries(project)
    creator = Creator(str(out)).config_indexing(True, "deu")
    with creator:
        creator.set_mainpath(entries[0]["path"])
        for key in ("Name", "Title", "Creator", "Publisher", "Date", "Description", "Language", "Flavour", "Tags"):
            creator.add_metadata(key, str(meta[key]))
        for entry in entries:
            html = (FIXTURES / entry["file"]).read_text(encoding="utf-8")
            creator.add_item(HtmlItem(entry["path"], entry["title"], html))
        for path, title, target in meta["redirects"]:
            creator.add_redirection(path, title, target, {Hint.FRONT_ARTICLE: True})
    return out


@pytest.fixture(scope="session")
def sample_zims(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    directory = tmp_path_factory.mktemp("zim")
    return {project: build_sample_zim(directory / meta["file"], project) for project, meta in SAMPLE_META.items()}


def make_settings(paths: Iterable[Path], state_dir: Path, **overrides: Any) -> Settings:
    # Offline by default: LLM_ENABLED and B_API_KEY from the shell must never reach the real b-api in tests.
    overrides.setdefault("llm_enabled", False)
    overrides.setdefault("rate_limit", 0)  # tests opt in to the limit (tests/test_rate_limit.py)
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        zim_paths=",".join(str(p) for p in paths),
        zim_required="wikipedia_de_sample,klexikon_de_sample",
        config_dir=ROOT / "config",
        state_dir=state_dir,
        **overrides,
    )


@pytest.fixture(scope="session")
def settings(sample_zims: dict[str, Path], tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return make_settings(sample_zims.values(), tmp_path_factory.mktemp("state"))


@pytest.fixture(scope="session")
def registry(settings: Settings) -> ZimRegistry:
    return ZimRegistry(settings.zim_path_list)


@pytest.fixture(scope="session")
def service(settings: Settings, registry: ZimRegistry) -> CompendiumService:
    templates = TemplateManager(custom_dir=settings.state_dir / "templates")
    return build_service(settings, registry, templates)


@pytest.fixture
def optik_html() -> str:
    return (FIXTURES / "wikipedia" / "Optik.html").read_text(encoding="utf-8")
