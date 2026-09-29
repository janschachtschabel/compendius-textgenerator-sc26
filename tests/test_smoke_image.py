"""The smoke probe of the image sees a worker the parent process killed (audit 2026-09-29, O1).

uvicorn reports it as "Child process [n] died" through its logger uvicorn.error, which writes to stderr, and
``docker logs`` passes the container's stdout and stderr on apart. The probe read stdout only: its check for a died
worker could never fire, and the log it printed with a failure lacked uvicorn's own lines.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

from scripts import smoke_image

COMPENDIUM: dict[str, object] = {
    "markdown": "x" * smoke_image.MIN_CHARACTERS,
    "parts_status": {"world": "ok"},
    "sections": [],
}
ACCESS = 'INFO:     127.0.0.1:50000 - "POST /api/v2/compendium HTTP/1.1" 200 OK'
DIED = "INFO:     Child process [7] died"


def fake_docker(monkeypatch: pytest.MonkeyPatch, *, stdout: str, stderr: str, code: int = 0) -> None:
    """``docker logs`` as the CLI answers it: the container's stdout on stdout, its stderr on stderr."""
    script = f"import sys; print({stdout!r}, flush=True); print({stderr!r}, file=sys.stderr); sys.exit({code})"
    run = subprocess.run

    def docker(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        assert command[:2] == [smoke_image.DOCKER, "logs"]
        return run([sys.executable, "-c", script], **options)

    monkeypatch.setattr(subprocess, "run", docker)


def test_a_worker_the_parent_killed_fails_the_probe() -> None:
    with pytest.raises(SystemExit, match="a worker died"):
        smoke_image.check(COMPENDIUM, f"{ACCESS}\n{DIED}")


def test_the_log_holds_what_uvicorn_wrote_to_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_docker(monkeypatch, stdout=ACCESS, stderr=DIED)
    log = smoke_image.logs("compendium-smoke")
    assert ACCESS in log and DIED in log


def test_a_failing_docker_logs_names_its_own_error(monkeypatch: pytest.MonkeyPatch) -> None:
    missing = "Error response from daemon: No such container: compendium-smoke"
    fake_docker(monkeypatch, stdout="", stderr=missing, code=1)
    with pytest.raises(SystemExit, match="No such container"):
        smoke_image.logs("compendium-smoke")
