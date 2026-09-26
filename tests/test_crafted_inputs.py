"""Whatever a caller sends is read in linear time (reviews of D60).

/qa reads its text with the rules before it picks a method, /compendium parses an earlier compendium sent along, and
neither asks for a login. The inputs come from tests/qa_texts.py and are read in a process of their own that a deadline
stops: a pattern that backtracks holds the interpreter lock, and in this process a test would hang for hours instead of
failing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.api.v2.qa_schemas import MAX_TEXT_CHARS
from tests.qa_texts import MARKDOWN_CHARS, crafted_markdown, crafted_texts

ROOT = Path(__file__).resolve().parents[1]
DEADLINE_S = 120
# Linear work over the longest input takes milliseconds for a /qa text and a fraction of a second for 2,000,000
# characters of markdown; the patterns the reviews found took seconds to hours
BUDGET_S = {"qa": 1.0, "compendium": 5.0}
CASES = [("qa", name) for name in crafted_texts()] + [("compendium", name) for name in crafted_markdown()]


@pytest.fixture(scope="module")
def readings() -> tuple[dict[tuple[str, str], float], str]:
    """Seconds per input as the child process printed them, and what it said on stderr."""
    try:
        done = subprocess.run(
            [sys.executable, "-m", "tests.qa_texts"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=DEADLINE_S,
            check=False,
        )
        output, errors = done.stdout, done.stderr
    except subprocess.TimeoutExpired as expired:
        output = expired.stdout.decode() if isinstance(expired.stdout, bytes) else expired.stdout or ""
        errors = f"stopped after {DEADLINE_S} s"
    seconds = {}
    for line in output.splitlines():
        where, name, took = line.split("\t")
        seconds[(where, name)] = float(took)
    return seconds, errors


def test_the_crafted_inputs_are_as_long_as_a_request_allows() -> None:
    assert all(len(text) <= MAX_TEXT_CHARS for text in crafted_texts().values())
    assert all(len(text) <= MARKDOWN_CHARS for text in crafted_markdown().values())


@pytest.mark.parametrize(("where", "name"), CASES)
def test_a_crafted_input_is_read_in_linear_time(
    readings: tuple[dict[tuple[str, str], float], str], where: str, name: str
) -> None:
    seconds, errors = readings
    assert (where, name) in seconds, f"{name} did not finish: {errors[-500:]}"
    assert seconds[(where, name)] < BUDGET_S[where]
