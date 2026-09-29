"""The GitLab pipeline follows the platform's pattern (29.09.2026): stages build, test, humanitec and deploy, pipelines
for branches, and tags on top so that a release gets its image. The image is pushed under its commit before the tests
finish; a name that moves (main, develop, a version) only ever points to a commit whose tests passed."""

from __future__ import annotations

from typing import Any

import yaml

from tests.conftest import ROOT

PIPELINE: dict[str, Any] = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
CHECKS = ("ruff", "mypy", "dependency-audit", "alert-rules", "pytest", "ui-scripts")


def test_the_pipeline_has_the_stages_of_the_platform_and_runs_for_branches_and_tags() -> None:
    assert PIPELINE["stages"] == ["build", "test", "humanitec", "deploy"]
    assert PIPELINE["workflow"]["rules"] == [{"if": "$CI_COMMIT_BRANCH"}, {"if": "$CI_COMMIT_TAG"}]


def test_every_check_runs_in_the_test_stage_without_waiting_for_the_image() -> None:
    for name in CHECKS:
        assert PIPELINE[name]["stage"] == "test", name
        assert PIPELINE[name]["needs"] == [], name


def test_the_build_pushes_the_commit_and_only_deploy_moves_a_name() -> None:
    build, tag = PIPELINE["docker build"], PIPELINE["docker tag"]
    pushes = [line for line in build["script"] if "push" in line]

    assert build["stage"] == "build" and pushes == ["docker image push $IMAGE_NAME:$CI_COMMIT_SHA"]
    assert tag["stage"] == "deploy" and "docker image push $IMAGE_NAME:$IMAGE_TAG" in tag["script"]
    assert [rule["variables"]["IMAGE_TAG"] for rule in tag["rules"]] == ["$CI_COMMIT_TAG", "$CI_COMMIT_REF_SLUG"]
