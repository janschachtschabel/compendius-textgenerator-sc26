"""Subscription manifest: profiles, required archives, validation."""

import pytest

from app.sources.zim.subscriptions import Subscription, SubscriptionManifest, load_manifest
from tests.conftest import ROOT

MANIFEST = ROOT / "config" / "zim_subscriptions.yaml"


def test_builtin_manifest_profiles() -> None:
    manifest = load_manifest(MANIFEST)
    ids = {s.id for s in manifest.subscriptions}
    assert {"wikipedia_de_all_nopic", "wikipedia_de_top_nopic", "klexikon_de_all_maxi"} <= ids
    assert [s.id for s in manifest.for_profile("compact")] == ["wikipedia_de_top_nopic", "klexikon_de_all_maxi"]
    assert manifest.required_ids("standard") == ["wikipedia_de_all_nopic", "klexikon_de_all_maxi"]
    extended = {s.id for s in manifest.for_profile("extended")}
    assert {"wikibooks_de_all_nopic", "wikiversity_de_all_nopic"} <= extended
    assert manifest.required_ids("extended") == ["wikipedia_de_all_nopic", "klexikon_de_all_maxi"]
    assert set(manifest.profiles) == {"compact", "standard", "extended"}


def test_unknown_profile_raises() -> None:
    manifest = load_manifest(MANIFEST)
    with pytest.raises(KeyError):
        manifest.for_profile("huge")


def test_by_id_and_file_matching() -> None:
    manifest = load_manifest(MANIFEST)
    sub = manifest.by_id("klexikon_de_all_maxi")
    assert sub is not None
    assert sub.file_prefix == "klexikon_de_all_maxi_"
    assert sub.matches_file("klexikon_de_all_maxi_2026-08.zim")
    assert not sub.matches_file("klexikon_de_all_nopic_2026-08.zim")
    assert manifest.by_id("nope") is None


def test_id_must_match_name_and_flavour() -> None:
    with pytest.raises(ValueError, match="id"):
        Subscription(id="klexikon_de_all", name="klexikon_de_all", flavour="maxi", project="klexikon", profiles=["a"])
    plain = Subscription(id="freecodecamp_de_all", name="freecodecamp_de_all", project="other", profiles=["a"])
    assert plain.file_prefix == "freecodecamp_de_all_"


def test_manifest_rejects_unknown_profile_and_duplicates() -> None:
    sub = Subscription(id="x_de_all", name="x_de_all", project="other", profiles=["standard"])
    with pytest.raises(ValueError, match="profile"):
        SubscriptionManifest(profiles={"compact": ""}, subscriptions=[sub])
    dup = Subscription(id="x_de_all", name="x_de_all", project="other", profiles=["compact"])
    with pytest.raises(ValueError, match="duplicate"):
        SubscriptionManifest(profiles={"compact": ""}, subscriptions=[dup, dup])
