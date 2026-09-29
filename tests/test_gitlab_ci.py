"""The GitLab pipeline follows the platform's pattern (29.09.2026) and does what the GitHub CI does.

Stages build, test, humanitec and deploy, pipelines for branches, and tags on top so that a release gets its image.
The image is built, probed like scripts/smoke_image.py probes it on GitHub, and pushed under its commit; a name that
moves (main, latest, develop, a version) only ever points to a commit whose checks passed. A weekly scheduled pipeline
runs the dependency audit alone, as dependency-audit.yml does on GitHub.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

import pytest
import yaml

from tests.conftest import ROOT

PIPELINE: dict[str, Any] = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
CHECKS = ("ruff", "mypy", "alert-rules", "pytest", "ui-scripts")
IMAGE_JOBS = ("sample archives", "docker build", "docker tag")
NOT_ON_SCHEDULE = {"if": '$CI_PIPELINE_SOURCE == "schedule"', "when": "never"}
SH = shutil.which("sh")


def job(name: str) -> dict[str, Any]:
    """A job with what the templates it extends give it; the job's own keys win (GitLab merges hashes deeper, which
    none of these checks needs)."""
    own = PIPELINE[name]
    extends = own.get("extends", [])
    merged: dict[str, Any] = {}
    for template in [extends] if isinstance(extends, str) else extends:
        merged.update(job(template))
    merged.update({key: value for key, value in own.items() if key != "extends"})
    return merged


def test_the_pipeline_has_the_stages_of_the_platform_and_runs_for_branches_and_tags() -> None:
    assert PIPELINE["stages"] == ["build", "test", "humanitec", "deploy"]
    assert PIPELINE["workflow"]["rules"] == [{"if": "$CI_COMMIT_BRANCH"}, {"if": "$CI_COMMIT_TAG"}]


def test_every_check_runs_in_the_test_stage_without_waiting_for_the_image() -> None:
    for name in CHECKS:
        assert job(name)["stage"] == "test", name
        assert job(name)["needs"] == [], name
        assert job(name)["rules"][0] == NOT_ON_SCHEDULE, name


def test_the_weekly_pipeline_runs_the_dependency_audit_alone() -> None:
    audit = job("dependency-audit")

    assert audit["stage"] == "test" and audit["needs"] == [] and "rules" not in audit
    for name in (*CHECKS, *IMAGE_JOBS):
        assert job(name)["rules"][0] == NOT_ON_SCHEDULE, name


def test_the_build_probes_the_image_like_github_before_it_pushes_the_commit() -> None:
    build = job("docker build")
    script = " ".join(build["script"])
    pushes = [line for line in build["script"] if "push" in line]

    assert build["stage"] == "build" and build["needs"] == ["sample archives"]
    assert "smoke_image.py --write-archives smoke-zim" in " ".join(job("sample archives")["script"])
    assert "smoke_image.py --archives smoke-zim --host docker" in script
    assert "--hardened --embeddings" in script
    assert pushes == ["docker image push $IMAGE_NAME:$CI_COMMIT_SHA"]
    assert script.index("smoke_image.py") < script.index("docker image push")


def test_only_the_tagging_finishes_once_started_and_one_at_a_time() -> None:
    tag = job("docker tag")

    assert PIPELINE["default"]["interruptible"] is True
    assert tag["stage"] == "deploy" and tag["interruptible"] is False
    assert tag["resource_group"] == "image-tags-$CI_COMMIT_REF_SLUG"


@pytest.mark.skipif(SH is None, reason="the tags are computed by the shell of the job")
@pytest.mark.parametrize(
    ("ref", "tags"),
    [
        ({"CI_COMMIT_TAG": "v2.5.0"}, "2.5.0 2.5"),
        ({"CI_COMMIT_TAG": "v2.6.0-rc.1"}, "2.6.0-rc.1"),
        ({"CI_COMMIT_BRANCH": "main"}, "main latest"),
        ({"CI_COMMIT_BRANCH": "develop", "CI_COMMIT_REF_SLUG": "develop"}, "develop"),
    ],
)
def test_the_names_are_those_the_github_ci_gives(ref: dict[str, str], tags: str) -> None:
    """GitHub publishes :latest and :main for main and :2.5.0 and :2.5 for v2.5.0 (docker/metadata-action)."""
    assert SH is not None
    names = job("docker tag")["script"][0]
    environment = {**os.environ, "CI_COMMIT_TAG": "", "CI_COMMIT_BRANCH": "", "CI_COMMIT_REF_SLUG": "", **ref}
    done = subprocess.run(  # noqa: S603 - the shell of the pipeline on its own snippet
        [SH, "-c", f'{names}\necho "$tags"'], env=environment, capture_output=True, text=True, check=True
    )

    assert done.stdout.strip() == tags
    assert "for tag in $tags" in job("docker tag")["script"][-1]
