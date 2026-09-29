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
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.conftest import SAMPLE_META, build_sample_zim

DOCKER = "docker"  # on PATH by intent: the script runs where the image was built
READY_TIMEOUT_S = 90
REQUEST_TIMEOUT_S = 240
MIN_CHARACTERS = 2000  # a compendium of the sample archives is far longer; this only catches an empty answer
# The files of the review page: what its page links, and what its modules import from one another
LINKED = re.compile(r'(?:src|href)="([a-z_]+\.(?:mjs|css))"')
IMPORTED = re.compile(r"from '\./([a-z_]+\.mjs)'")
# What docker-compose.yml sets for every service (x-hardening): the image must run under it
HARDENING = (
    "--read-only",
    "--tmpfs",
    "/tmp",  # noqa: S108 - the mount point of a tmpfs inside the container, no file here
    "--cap-drop",
    "ALL",
    "--security-opt",
    "no-new-privileges:true",
)
# What it sets for the four sidecars: no capabilities and no new privileges, but a writable file system - SQLite puts
# its sort files in /var/tmp
SIDECAR_HARDENING = ("--cap-drop", "ALL", "--security-opt", "no-new-privileges:true")
# The command of each sidecar, as "status", and the first words of its answer. A broken entry point or a start
# failure under the hardening let them restart endlessly while CI stayed green; on 2026-09-27 they were missing on
# the server unnoticed (audit 2026-09-28, BE-15)
SIDECARS = {
    "zim": "ZIM-Verzeichnis:",
    "lehrplan": "Lehrplan-Cache:",
    "wikidata": "Wikidata-Index:",
    "gnd": "GND-Index:",
}


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
    """The rules ask from the spaCy parse only when the packaged model really runs (D55)."""
    body = {
        "text": (
            "Daneben sind die nichtlineare Optik und die Quantenoptik von Bedeutung. "
            "Die Optik ist ein Teilgebiet der Physik und handelt vom Licht."
        ),
        "method": "rule-based",  # the stage that reads the parse; the templates are left for a missing model
        "count": 2,
    }
    try:
        response = httpx.post(f"{base_url}/api/v2/qa", json=body, timeout=REQUEST_TIMEOUT_S)
    except httpx.HTTPError as exc:
        raise SystemExit(f"the qa request got no answer ({exc}):\n{run('logs', container)}") from exc
    if response.status_code != 200:
        raise SystemExit(f"POST /api/v2/qa answered {response.status_code}: {response.text[:400]}")
    return dict(response.json())


def check_pairs(answer: dict[str, object]) -> str:
    """Return the evidence line, or raise when the rules could not read the parse in the image.

    "Was ist die Optik?" takes the sentence's own article, which only the rules of D55 do; without the spaCy model
    the templates would ask "Was versteht man unter Optik?" and the note would name the missing model.
    """
    if "spaCy" in str(answer.get("note") or ""):
        raise SystemExit(f"the image could not parse: {answer['note']}")
    pairs = answer.get("pairs")
    questions = [str(pair.get("question", "")) for pair in pairs] if isinstance(pairs, list) else []
    if any("Daneben" in question for question in questions):
        raise SystemExit(f"a sentence-initial adverb became a question: {questions}")
    if "Was ist die Optik?" not in questions:
        raise SystemExit(f"the rules did not ask from the parse: {questions}")
    return f"{len(questions)} pairs from the parse, no question about an adverb"


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


def check_revision(base_url: str, expected: str) -> str:
    """Return the evidence line, or raise when the image reports another commit than the one it was built from."""
    reported = httpx.get(f"{base_url}/health", timeout=10).json().get("revision")
    if expected and reported != expected:
        raise SystemExit(f"/health reports revision {reported!r}, the build was {expected!r}")
    return f"revision {reported}"


def check_embeddings(base_url: str) -> str:
    """The image ships its Model2Vec model, and the profiles' matcher must load it. A model the service cannot read
    left it out without a failure: after f167a9f the weights were root's with mode 0600 (found 2026-09-28)."""
    matching = httpx.get(f"{base_url}/health", timeout=10).json()["components"]["matching"]
    if not matching.get("embeddings"):
        raise SystemExit(f"the matcher runs without its Model2Vec model: {matching}")
    return f"{matching['matcher']} with {', '.join(matching['components'])}"


def check_sidecars(image: str, archives: Path, state: Path, *, hardened: bool) -> str:
    """The status command of each sidecar in the image, with the volumes and the hardening docker-compose.yml gives it;
    a failing one fails the probe with its own message."""
    for command, first_words in SIDECARS.items():
        answer = run(
            "run", "--rm",
            "-v", f"{archives.as_posix()}:/data/zim:ro",
            "-v", f"{state.as_posix()}:/data/state",
            "-e", "ZIM_DIR=/data/zim",
            "-e", "STATE_DIR=/data/state",
            *(SIDECAR_HARDENING if hardened else ()),
            image, "compendium", command, "status",
        )  # fmt: skip
        if not answer.startswith(first_words):
            raise SystemExit(f"compendium {command} status did not answer as expected: {answer[:300]}")
    return "compendium " + ", ".join(SIDECARS) + " status"


def check_review_page(base_url: str) -> str:
    """The review page is in the image (D66): the wheel has to carry the files of app/ui/static, which only a built
    image shows - the tests read them from the checkout."""
    page = httpx.get(f"{base_url}/ui/", timeout=10)
    if page.status_code != 200 or httpx.get(f"{base_url}/ui/options.json", timeout=10).status_code != 200:
        raise SystemExit(f"/ui/ answered {page.status_code}; the page or its options are missing")
    found, missing = review_page_files(page.text, lambda name: _served(f"{base_url}/ui/{name}"))
    if missing or "main.mjs" not in found:
        raise SystemExit(f"files of the review page missing from the image: {missing or ['main.mjs']}")
    return f"the review page with {len(found)} files"


def review_page_files(index: str, fetch: Callable[[str], str | None]) -> tuple[list[str], list[str]]:
    """The files of the review page - what index.html links and what each module imports, followed from module to
    module, since a module the wheel lacks breaks the page wherever it is imported - and those ``fetch`` does not
    find (None)."""
    found: list[str] = []
    missing: list[str] = []
    waiting = LINKED.findall(index)
    while waiting:
        name = waiting.pop()
        if name in found or name in missing:
            continue
        text = fetch(name)
        if text is None:
            missing.append(name)
        else:
            found.append(name)
            waiting.extend(IMPORTED.findall(text) if name.endswith(".mjs") else [])
    return sorted(found), sorted(missing)


def _served(url: str) -> str | None:
    answer = httpx.get(url, timeout=10)
    return answer.text if answer.status_code == 200 else None


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
    parser.add_argument("--revision", default="", help="the commit the image was built from; /health must name it")
    parser.add_argument(
        "--hardened", action="store_true", help="run as docker-compose.yml does: read-only, no capabilities"
    )
    parser.add_argument(
        "--embeddings",
        action="store_true",
        help="the image was built with its Model2Vec model (the published one is), and the matcher must use it",
    )
    args = parser.parse_args()

    base_url = f"http://127.0.0.1:{args.port}"
    with (
        tempfile.TemporaryDirectory(prefix="smoke-zim-") as directory,
        tempfile.TemporaryDirectory(prefix="smoke-state-") as state_directory,
    ):
        archives, state = Path(directory), Path(state_directory)
        # tempfile keeps the directories to their owner (0700); the image runs as an unprivileged user of its own, and
        # a sidecar writes into its state volume
        archives.chmod(0o755)
        state.chmod(0o777)
        build_archives(archives)
        print(f"the sidecars start: {check_sidecars(args.image, archives, state, hardened=args.hardened)}")
        subprocess.run([DOCKER, "rm", "-f", args.name], capture_output=True, check=False)  # noqa: S603
        container = run(
            "run", "-d", "--name", args.name,
            "-p", f"127.0.0.1:{args.port}:8000",
            "-v", f"{archives.as_posix()}:/data/zim:ro",
            "-e", "ZIM_REQUIRED=wikipedia_de_sample,klexikon_de_sample",
            "-e", "PRESET_DEFAULT=llm-free",
            "-e", "UI_ENABLED=true",
            *(HARDENING if args.hardened else ()),
            args.image,
        )  # fmt: skip
        try:
            wait_until_ready(base_url, container)
            print(f"the image is: {check_revision(base_url, args.revision)}")
            if args.embeddings:
                print(f"the image matches: {check_embeddings(base_url)}")
            compendium = ask_for_a_compendium(base_url, container)
            print(f"the image answers: {check(compendium, run('logs', args.name))}")
            print(f"the image refuses: {check_llm_profile_refused(base_url, container)}")
            print(f"the image recognises: {check_entities(ask_for_entities(base_url, container))}")
            print(f"the image asks: {check_pairs(ask_for_pairs(base_url, container))}")
            print(f"the image shows: {check_review_page(base_url)}")
        finally:
            run("rm", "-f", args.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
