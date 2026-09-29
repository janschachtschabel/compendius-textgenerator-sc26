"""Versions that several files pin move together (audit 2026-09-28, AB-06 and BE-16).

uv stood at 0.7.13 in the Dockerfile, both CI pipelines and the audit workflow, and Dependabot ignored it for good:
nothing could move it, and moving it in one place only would build the image with another uv than the one that
checked the lockfile. Dependabot now proposes a new uv minor for the Dockerfile; this test keeps that change red
until every other pin follows. The GitLab pipeline pinned its Prometheus image apart from docker-compose.yml, and a
Dependabot update of the compose file left it behind.
"""

from __future__ import annotations

import re

import yaml

from tests.conftest import ROOT

WORKFLOWS = ("ci.yml", "dependency-audit.yml")


def uv_pins() -> dict[str, list[str]]:
    """Every uv version a build or a pipeline pins, by file."""
    pins = {
        "Dockerfile": re.findall(
            r"^FROM ghcr\.io/astral-sh/uv:([\d.]+)@", (ROOT / "Dockerfile").read_text(encoding="utf-8"), re.M
        )
    }
    for workflow in WORKFLOWS:
        text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        pins[workflow] = re.findall(r"astral-sh/setup-uv@\S+.*\n\s+with:\n\s+version: \"([\d.]+)\"", text)
    gitlab = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    pins[".gitlab-ci.yml"] = re.findall(r"^ghcr\.io/astral-sh/uv:([\d.]+)-", gitlab["default"]["image"])
    return pins


def test_every_build_and_pipeline_runs_the_same_uv() -> None:
    pins = uv_pins()

    assert all(pins.values()), pins  # every file still pins one; a moved pin must not drop out of the check
    assert len({version for found in pins.values() for version in found}) == 1, (
        f"uv steht nicht überall auf derselben Version: {pins}. Alle Stellen gemeinsam heben (.github/dependabot.yml)"
    )


def test_every_image_a_pipeline_pulls_is_pinned_by_digest() -> None:
    gitlab = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    images = {
        name: job["image"] if isinstance(job["image"], str) else job["image"]["name"]
        for name, job in gitlab.items()
        if isinstance(job, dict) and "image" in job
    }

    # an image given by a variable ($DIND_IMAGE) is the runner's to pin
    assert not [name for name, image in images.items() if not image.startswith("$") and "@sha256:" not in image], images
    assert gitlab["alert-rules"]["image"]["name"] == compose["services"]["prometheus"]["image"]
