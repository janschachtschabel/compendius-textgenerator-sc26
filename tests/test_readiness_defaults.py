"""The paths a production server takes and the tests did not (audit 2026-09-27, TE-07).

tests/conftest.py always sets ZIM_REQUIRED to the sample archives, so the default - the profile of the
subscription manifest names the required archives - never ran, nor did the status of a corrupt active.json.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app, resolve_required_ids
from app.sources.zim.active import ACTIVE_FILE
from app.sources.zim.subscriptions import load_manifest
from tests.conftest import make_settings


def test_without_zim_required_the_profile_of_the_manifest_names_the_archives(
    sample_zims: dict[str, Path], tmp_path: Path
) -> None:
    settings = make_settings(sample_zims.values(), tmp_path / "state", zim_required="")
    manifest = load_manifest(settings.zim_manifest_path)
    required = resolve_required_ids(settings, manifest)
    assert required == manifest.required_ids(settings.zim_profile) and required
    explicit = make_settings(sample_zims.values(), tmp_path / "state", zim_required="klexikon_de_sample")
    assert resolve_required_ids(explicit, manifest) == ["klexikon_de_sample"]


def test_ready_waits_for_the_archives_of_the_profile(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    """The sample archives are not the profile's: a server that has only them is not ready, and says which lack."""
    settings = make_settings(sample_zims.values(), tmp_path / "state", zim_required="")
    required = load_manifest(settings.zim_manifest_path).required_ids(settings.zim_profile)
    response = TestClient(create_app(settings)).get("/ready")
    assert response.status_code == 503
    assert sorted(response.json()["components"]["zim"]["missing_required"]) == sorted(required)


def test_the_zim_status_answers_over_a_corrupt_state_file(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    (tmp_path / "zim").mkdir()
    (tmp_path / "zim" / ACTIVE_FILE).write_text("{kaputt", encoding="utf-8")
    settings = make_settings(sample_zims.values(), tmp_path / "state", zim_dir=tmp_path / "zim")
    response = TestClient(create_app(settings)).get("/api/v2/zim/status")
    assert response.status_code == 200
    assert response.json()["active"]["profile"] == settings.zim_profile
    assert response.json()["active"]["archives"] == {}
