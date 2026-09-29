"""Which tags the publish job of the GitHub workflow moves (audit 2026-09-29, O3).

Every push to main runs its own publish job, one at a time per ref, and a run whose checks took longer publishes
after the run of a newer commit. ``:latest`` went only to the commit main points to, but ``:main`` went to every
run: pushed after a newer commit's run, it jumped back to the older commit.
"""

from __future__ import annotations

import yaml

from tests.conftest import ROOT

# The step "tip" sets it true only in a run of main whose commit main still points to
TIP = "enable=${{ steps.tip.outputs.latest }}"


def publish_tags() -> list[str]:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    [meta] = [step for step in workflow["jobs"]["publish"]["steps"] if step.get("id") == "meta"]
    return [line.strip() for line in meta["with"]["tags"].splitlines() if line.strip()]


def test_every_tag_that_moves_with_main_goes_only_to_its_newest_commit() -> None:
    tags = publish_tags()
    # The commit's own tag never moves, and a version tag's run is no run of main
    moving = [tag for tag in tags if not tag.startswith(("type=sha,", "type=semver,"))]

    assert moving and all(TIP in tag.split(",") for tag in moving), tags
