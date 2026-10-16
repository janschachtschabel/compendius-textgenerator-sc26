"""Stufe 1 of scaling (D113): with INDEX_COPY_DIR the API reads the sidecars' SQLite files from a local copy, and with
TEMPLATES_DIR its own templates from a directory of their own, say a ConfigMap; then it needs the shared volumes for
reading only."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.sources.lehrplan.store import LehrplanWriter
from app.sources.wikidata.index import build_index
from app.wiring import build_curricula
from tests.conftest import ROOT, make_settings
from tests.test_wikidata_index import write_dumps


def test_the_indexes_are_read_from_the_copy_directory(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    state, local = tmp_path / "state", tmp_path / "local"
    build_index(*write_dumps(tmp_path / "dumps"), state / "wikidata.db")
    writer = LehrplanWriter(state / "lehrplan.db")
    writer.set_meta({"harvested_at": "2026-10-16T10:00:00+00:00", "endpoint": "https://sparql.test/"})
    writer.commit()
    settings = make_settings(sample_zims.values(), state, index_copy_dir=local)

    store = build_curricula(settings).store

    with TestClient(create_app(settings)) as client:  # the shutdown closes the index
        wikidata = client.app.state.wikidata  # type: ignore[attr-defined]
        assert wikidata.qid("Ernst Abbe") == "Q999001" and wikidata.path.parent == local
    assert store.exists and store.path.parent == local


def test_without_a_copy_directory_the_indexes_are_read_in_place(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    """The default: Compose on one host reads the volume as before."""
    state = tmp_path / "state"
    build_index(*write_dumps(tmp_path / "dumps"), state / "wikidata.db")

    with TestClient(create_app(make_settings(sample_zims.values(), state))) as client:
        assert client.app.state.wikidata.path == state / "wikidata.db"  # type: ignore[attr-defined]


def test_the_templates_come_from_their_own_directory(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    """A ConfigMap mounted at TEMPLATES_DIR brings the custom templates; the state volume can stay read-only."""
    templates = tmp_path / "configmap"
    templates.mkdir()
    own = json.loads((ROOT / "app" / "templates" / "builtin" / "sc26.json").read_text(encoding="utf-8"))
    own |= {"id": "eigenes", "name": "Eigenes Template", "builtin": False}
    (templates / "eigenes.json").write_text(json.dumps(own), encoding="utf-8")

    with TestClient(
        create_app(make_settings(sample_zims.values(), tmp_path / "state", templates_dir=templates))
    ) as client:
        ids = [template["id"] for template in client.get("/api/v2/templates").json()]

    assert "eigenes" in ids
