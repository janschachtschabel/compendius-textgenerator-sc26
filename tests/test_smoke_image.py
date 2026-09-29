"""The smoke probe of the image sees a worker the parent process killed (audit 2026-09-29, O1).

uvicorn reports it as "Child process [n] died" through its logger uvicorn.error, which writes to stderr, and
``docker logs`` passes the container's stdout and stderr on apart. The probe read stdout only: its check for a died
worker could never fire, and the log it printed with a failure lacked uvicorn's own lines.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import smoke_image
from tests.conftest import ROOT, SAMPLE_META

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


def test_the_checks_need_no_test_helpers_so_a_bare_python_can_run_them() -> None:
    """GitLab runs the probe in its Docker-in-Docker job, with Alpine's Python and httpx only; the helpers that build the
    sample archives (tests/conftest.py, libzim) run in a job of their own (--write-archives)."""
    code = "import sys; import scripts.smoke_image; print('tests.conftest' in sys.modules)"
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)  # noqa: S603

    assert done.stdout.strip() == "False"


@pytest.mark.parametrize(
    ("host", "bind"),
    [("127.0.0.1", "127.0.0.1"), ("localhost", "127.0.0.1"), ("docker", "0.0.0.0")],  # noqa: S104 - an expected value
)
def test_the_port_is_published_where_the_probe_reaches_it(host: str, bind: str) -> None:
    """Locally the port stays on the loopback; with Docker-in-Docker the container runs in the network of the daemon,
    which the job reaches under the name of the service (GitLab: docker)."""
    assert smoke_image.publish_address(host) == bind


def test_the_archives_reach_the_container_through_a_volume(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A bind mount names a directory of the machine the daemon runs on: with Docker-in-Docker that is not the job's,
    and the service would see an empty /data/zim. The probe copies the archives into a named volume instead."""
    (tmp_path / "a.zim").write_bytes(b"zim")
    (tmp_path / "a.zim_title.idx").write_bytes(b"what the creator of the archive leaves beside it")
    calls: list[tuple[str, ...]] = []

    def docker(*args: str, **_: object) -> str:
        calls.append(args)
        return ""

    monkeypatch.setattr(smoke_image, "run", docker)

    smoke_image.fill_volume("image:tag", "smoke-zim", tmp_path, "smoke")

    assert calls[0] == ("volume", "create", "smoke-zim")
    assert ("create", "--name", "smoke-copy", "-v", "smoke-zim:/data/zim", "image:tag") in calls
    assert [call for call in calls if call[0] == "cp"] == [
        ("cp", str(tmp_path / "a.zim"), "smoke-copy:/data/zim/a.zim")
    ]
    assert calls[-1] == ("rm", "-f", "smoke-copy")


def test_write_archives_builds_the_samples_and_stops(tmp_path: Path) -> None:
    target = tmp_path / "zim"
    done = subprocess.run(  # noqa: S603 - this repository's own script
        [sys.executable, "scripts/smoke_image.py", "--write-archives", str(target)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert done.returncode == 0, done.stderr
    assert {str(meta["file"]) for meta in SAMPLE_META.values()} <= {path.name for path in target.iterdir()}
