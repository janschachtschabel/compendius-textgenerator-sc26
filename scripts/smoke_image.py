"""Smoke test for a built image: it has to answer, and it has to produce a compendium.

The test suite calls the service in the same process, so it never sees what the image does: the start command,
the worker setup, the paths, the permissions of the unprivileged user. This script starts the image the way an
operator does - two workers, a mounted archive directory - and checks that a compendium comes back.

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
            args.image,
        )  # fmt: skip
        try:
            wait_until_ready(base_url, container)
            compendium = ask_for_a_compendium(base_url, container)
            print(f"the image answers: {check(compendium, run('logs', args.name))}")
        finally:
            run("rm", "-f", args.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
