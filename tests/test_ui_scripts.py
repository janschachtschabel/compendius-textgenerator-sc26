"""The scripts of the review page pass their own tests (D66).

The page parses the markdown of the service, tells where each paragraph comes from and builds the requests in
JavaScript modules; tests/ui/*.test.mjs test them with Node's own test runner, which needs no package. The runner of
GitHub has Node, so CI runs them; without Node this test is skipped and says so.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS = sorted((ROOT / "tests" / "ui").glob("*.test.mjs"))
NODE = shutil.which("node")


def test_every_module_of_the_page_with_logic_has_its_tests() -> None:
    tested = {path.name.removesuffix(".test.mjs") for path in TESTS}

    assert {"markdown", "provenance", "forms", "stats"} <= tested


@pytest.mark.skipif(NODE is None, reason="Node is not installed; tests/ui needs its test runner")
def test_the_scripts_of_the_page_pass_their_tests() -> None:
    done = subprocess.run(  # noqa: S603 - the runner of Node on the test files of this repository
        [str(NODE), "--test", *map(str, TESTS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )

    assert done.returncode == 0, done.stdout[-4000:] + done.stderr[-2000:]
