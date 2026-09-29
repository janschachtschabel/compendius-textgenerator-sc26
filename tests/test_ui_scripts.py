"""The scripts of the review page pass their own tests (D66).

The page parses the markdown of the service, tells where each paragraph comes from and builds the requests in
JavaScript modules; tests/ui/*.test.mjs test them with Node's own test runner, which needs no package. The runner of
GitHub has Node, so there a missing one fails this test instead of skipping it. The uv image of the GitLab pipeline
has none: it runs the scripts in a job of its own (ui-scripts), and pytest skips them there and on a machine without
Node, saying so.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TESTS = sorted((ROOT / "tests" / "ui").glob("*.test.mjs"))
NODE = shutil.which("node")
ON_GITHUB = os.environ.get("GITHUB_ACTIONS") == "true"


def test_every_module_of_the_page_with_logic_has_its_tests() -> None:
    tested = {path.name.removesuffix(".test.mjs") for path in TESTS}

    modules = {"markdown", "provenance", "forms", "fields", "stats", "steps", "api", "main"}
    views = {"info_compendium", "view_lehrplan", "views"}
    assert modules | views | {"answers"} <= tested, "answers: every view with the answers of tests/test_ui_answers.py"


def test_gitlab_runs_the_scripts_of_the_page_in_a_job_of_its_own() -> None:
    gitlab = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    job = gitlab["ui-scripts"]

    assert job["image"].startswith("node:"), job["image"]
    assert "node --test tests/ui/*.test.mjs" in job["script"]
    assert (job.get("rules"), job.get("needs")) == (gitlab["pytest"].get("rules"), gitlab["pytest"].get("needs"))


@pytest.mark.skipif(NODE is None and not ON_GITHUB, reason="Node is not installed; tests/ui needs its test runner")
def test_the_scripts_of_the_page_pass_their_tests() -> None:
    assert NODE is not None, "the runner of GitHub has Node; without it the scripts of the page went untested"
    done = subprocess.run(  # noqa: S603 - the runner of Node on the test files of this repository
        [str(NODE), "--test", *map(str, TESTS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )

    assert done.returncode == 0, done.stdout[-4000:] + done.stderr[-2000:]
