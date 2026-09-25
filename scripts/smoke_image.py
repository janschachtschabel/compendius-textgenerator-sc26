"""Smoke test for a built image: it has to answer, and it has to produce a compendium.

The test suite calls the service in the same process, so it never sees what the image does: the start command,
the worker setup, the paths, the permissions of the unprivileged user. This script starts the image the way an
operator does - two workers, a mounted archive directory - and checks that a compendium comes back. Like an operator
without an LLM it sets PRESET_DEFAULT=llm-free (D53), and it checks that a profile that needs an LLM is refused with a
503 that names LLM_ENABLED instead of quietly running the rules.

It also reports a worker the parent process killed (PLAN.md 10), but it cannot guarantee to provoke that: it
only happens when the machine is busy enough for a worker to stay silent past its healthcheck. The guard
against that bug is the unit test on the start command (tests/test_serve.py); this script is the check that
the packaged service answers at all.

The archives are the small sample ZIMs of the test session, built from the checked-in HTML fixtures, so the
script needs no dumps and no network.

    python scripts/smoke_image.py --image compendious-text-fastapi:local
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.conftest import SAMPLE_META, build_sample_zim

DOCKER = "docker"  # on PATH by intent: the script runs where the image was built
READY_TIMEOUT_S = 90
REQUEST_TIMEOUT_S = 240
MIN_CHARACTERS = 2000  # a compendium of the sample archives is far longer; this only catches an empty answer
# A lead with Greek in it: exactly the case where decoding token ids stops being extractive.
MODEL_TEXT = (
    "Die Optik (von altgriechisch ὀπτικός optikós) ist ein Teilgebiet der Physik "
    "und handelt vom Licht. Der Brechungsindex eines Mediums bestimmt, wie stark Licht gebrochen wird."
)


def run(*args: str) -> str:
    """Run a docker command and return its output; a failure raises with the command's own message."""
    result = subprocess.run([DOCKER, *args], capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise SystemExit(f"docker {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def build_archives(directory: Path) -> None:
    for project, meta in SAMPLE_META.items():
        build_sample_zim(directory / str(meta["file"]), project)


def wait_until_ready(base_url: str, container: str) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base_url}/ready", timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass  # the server is still starting; the deadline decides
        time.sleep(2)
    raise SystemExit(f"/ready stayed red for {READY_TIMEOUT_S} s\n{run('logs', container)}")


def ask_for_a_compendium(base_url: str, container: str) -> dict[str, object]:
    body = {"topic": "Optik", "parts": ["world"], "target_length": 4000}
    try:
        response = httpx.post(f"{base_url}/api/v2/compendium", json=body, timeout=REQUEST_TIMEOUT_S)
    except httpx.HTTPError as exc:
        # This is how the killed worker showed itself: the connection ended without an answer
        raise SystemExit(f"the request got no answer ({exc}):\n{run('logs', container)}") from exc
    if response.status_code != 200:
        raise SystemExit(f"POST /api/v2/compendium answered {response.status_code}: {response.text[:400]}")
    return dict(response.json())


def check_llm_profile_refused(base_url: str, container: str) -> str:
    """A profile that needs an LLM is a 503 on a server without one (D53); return the evidence line."""
    body = {"topic": "Optik", "parts": ["world"], "preset": "balanced"}
    try:
        response = httpx.post(f"{base_url}/api/v2/compendium", json=body, timeout=REQUEST_TIMEOUT_S)
    except httpx.HTTPError as exc:
        raise SystemExit(f"the balanced request got no answer ({exc}):\n{run('logs', container)}") from exc
    if response.status_code != 503 or "LLM_ENABLED" not in response.text:
        raise SystemExit(f"balanced without an LLM answered {response.status_code}: {response.text[:400]}")
    return "balanced without an LLM is a 503 that names LLM_ENABLED"


def ask_for_entities(base_url: str, container: str) -> dict[str, object]:
    """The entity endpoint is the only place the packaged spaCy model is ever executed."""
    body = {"text": "Alexander von Humboldt reiste 1799 nach Südamerika.", "link": False}
    try:
        response = httpx.post(f"{base_url}/api/v2/entities", json=body, timeout=REQUEST_TIMEOUT_S)
    except httpx.HTTPError as exc:
        raise SystemExit(f"the entity request got no answer ({exc}):\n{run('logs', container)}") from exc
    if response.status_code != 200:
        raise SystemExit(f"POST /api/v2/entities answered {response.status_code}: {response.text[:400]}")
    return dict(response.json())


def ask_for_pairs(base_url: str, container: str) -> dict[str, object]:
    """The question templates only check their subjects when the packaged spaCy model really runs."""
    body = {
        "text": (
            "Daneben sind die nichtlineare Optik und die Quantenoptik von Bedeutung. "
            "Die Optik ist ein Teilgebiet der Physik und handelt vom Licht."
        ),
        "method": "rule-based",  # the templates are what checks the subjects; the profile would take the parse
        "count": 5,
    }
    try:
        response = httpx.post(f"{base_url}/api/v2/qa", json=body, timeout=REQUEST_TIMEOUT_S)
    except httpx.HTTPError as exc:
        raise SystemExit(f"the qa request got no answer ({exc}):\n{run('logs', container)}") from exc
    if response.status_code != 200:
        raise SystemExit(f"POST /api/v2/qa answered {response.status_code}: {response.text[:400]}")
    return dict(response.json())


def check_pairs(answer: dict[str, object]) -> str:
    """Return the evidence line, or raise when the subjects went unchecked in the image."""
    if answer.get("note"):
        raise SystemExit(f"the image could not check the question subjects: {answer['note']}")
    pairs = answer.get("pairs")
    questions = [str(pair.get("question", "")) for pair in pairs] if isinstance(pairs, list) else []
    if any("Daneben" in question for question in questions):
        raise SystemExit(f"a sentence-initial adverb became a question: {questions}")
    if "Was versteht man unter Optik?" not in questions:
        raise SystemExit(f"the real subject lost its question: {questions}")
    return f"{len(questions)} pairs, no question about an adverb"


def ask_for_model_pairs(base_url: str, container: str) -> dict[str, object]:
    """The only place the two QA models are ever executed; loading them costs about eight seconds."""
    body = {"text": MODEL_TEXT, "method": "models", "count": 3}
    try:
        response = httpx.post(f"{base_url}/api/v2/qa", json=body, timeout=REQUEST_TIMEOUT_S)
    except httpx.HTTPError as exc:
        raise SystemExit(f"the model request got no answer ({exc}):\n{run('logs', container)}") from exc
    if response.status_code != 200:
        raise SystemExit(f"POST /api/v2/qa (models) answered {response.status_code}: {response.text[:400]}")
    return dict(response.json())


def check_model_pairs(answer: dict[str, object], text: str) -> str:
    """Return the evidence line, or raise when the packaged models did not run.

    The wording of a generated question is not pinned - a small model varies. What has to hold is that the
    stage ran at all, that it asked questions, and that every answer really is a span of the text. That last
    check is here because decoding token ids looks extractive and is not: it silently drops characters the
    model's vocabulary lacks and respaces the rest.
    """
    if answer.get("method") != "models":
        raise SystemExit(f"the image fell back instead of using its models: {answer.get('note')}")
    pairs = answer.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise SystemExit("the models ran but produced no pair")
    for pair in pairs:
        if not str(pair.get("question", "")).endswith("?"):
            raise SystemExit(f"not a question: {pair}")
        span = str(pair.get("answer", "")).strip()
        if not span:
            raise SystemExit(f"empty answer: {pair}")
        cut = span.rstrip("…").rstrip()  # a long answer is shortened, so compare its beginning
        if cut not in text:
            raise SystemExit(f"the answer is no span of the text: {span!r}")
    return f"{len(pairs)} pairs, every answer a span of the text"


def check_entities(answer: dict[str, object]) -> str:
    """Return the evidence line, or raise when the model of the image did not run."""
    methods = answer.get("methods")
    if not isinstance(methods, list) or "ner" not in methods:
        raise SystemExit(f"the image recognised nothing with its model; methods were {methods}")
    entities = answer.get("entities")
    found = len(entities) if isinstance(entities, list) else 0
    if not found:
        raise SystemExit("the model ran but found no entity in a sentence that has two")
    return f"{found} entities, ways: {', '.join(str(m) for m in methods)}"


def check(compendium: dict[str, object], logs: str) -> str:
    """Return the evidence line, or raise with what is wrong."""
    markdown = str(compendium.get("markdown", ""))
    status = compendium.get("parts_status")
    if len(markdown) < MIN_CHARACTERS:
        raise SystemExit(f"the compendium has only {len(markdown)} characters")
    if not isinstance(status, dict) or status.get("world") != "ok":
        raise SystemExit(f"part 1 did not come out: {json.dumps(status, ensure_ascii=False)}")
    if "died" in logs:
        raise SystemExit(f"a worker died while answering:\n{logs}")
    sections = compendium.get("sections")
    blocks = len(sections) if isinstance(sections, list) else 0
    return f"{len(markdown)} characters, {blocks} blocks, no worker died"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="compendious-text-fastapi:local")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--name", default="compendium-smoke")
    args = parser.parse_args()

    base_url = f"http://127.0.0.1:{args.port}"
    with tempfile.TemporaryDirectory(prefix="smoke-zim-") as directory:
        archives = Path(directory)
        # tempfile keeps the directory to its owner (0700); the image runs as an unprivileged user of its own
        archives.chmod(0o755)
        build_archives(archives)
        subprocess.run([DOCKER, "rm", "-f", args.name], capture_output=True, check=False)  # noqa: S603
        container = run(
            "run", "-d", "--name", args.name,
            "-p", f"127.0.0.1:{args.port}:8000",
            "-v", f"{archives.as_posix()}:/data/zim:ro",
            "-e", "ZIM_REQUIRED=wikipedia_de_sample,klexikon_de_sample",
            "-e", "PRESET_DEFAULT=llm-free",
            args.image,
        )  # fmt: skip
        try:
            wait_until_ready(base_url, container)
            compendium = ask_for_a_compendium(base_url, container)
            print(f"the image answers: {check(compendium, run('logs', args.name))}")
            print(f"the image refuses: {check_llm_profile_refused(base_url, container)}")
            print(f"the image recognises: {check_entities(ask_for_entities(base_url, container))}")
            print(f"the image asks: {check_pairs(ask_for_pairs(base_url, container))}")
            model_answer = ask_for_model_pairs(base_url, container)
            print(f"the image asks with models: {check_model_pairs(model_answer, MODEL_TEXT)}")
        finally:
            run("rm", "-f", args.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
