"""The path the router matches, with the root path of a proxy taken off as Starlette does (audit 2026-10-16)."""

from __future__ import annotations

import pytest

from app.api.paths import route_path


@pytest.mark.parametrize(
    ("path", "root", "expected"),
    [
        ("/kompendium/health", "/kompendium", "/health"),
        ("/kompendium", "/kompendium", "/"),
        ("/health", "", "/health"),
        ("/other/health", "/kompendium", "/other/health"),
        # a path that merely starts with the root's letters is no path below it: Starlette routes it whole
        ("/kompendiumhealth", "/kompendium", "/kompendiumhealth"),
    ],
)
def test_the_root_path_comes_off_only_before_a_slash(path: str, root: str, expected: str) -> None:
    assert route_path({"type": "http", "path": path, "root_path": root}) == expected
