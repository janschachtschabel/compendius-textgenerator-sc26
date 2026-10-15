"""The internal port (D110): probes, metrics and status answer on INTERNAL_PORT only, the API on its public port.

Team 6, 2026-10-14: "Port 1 ist die öffentliche API und wird über den Ingress freigegeben; Port 2 ist intern und liefert
/health, /ready und /metrics." Jan, 2026-10-15: Prometheus and the status endpoints run over the internal port.
"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send

from app import serve
from app.api.internal_port import INTERNAL_PATHS, InternalOnly
from app.main import create_app
from app.settings import Settings, get_settings
from tests.conftest import ROOT, make_settings

INTERNAL = 9000


def app_with_port(sample_zims: dict[str, Path], tmp_path: Path, port: int = INTERNAL) -> Any:
    return create_app(make_settings(sample_zims.values(), tmp_path / "state", internal_port=port))


def test_the_internal_paths_answer_on_the_internal_port_only(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    app = app_with_port(sample_zims, tmp_path)
    with (
        TestClient(app, base_url="http://testserver:8000") as public,
        TestClient(app, base_url=f"http://testserver:{INTERNAL}") as internal,
    ):
        for path in sorted(INTERNAL_PATHS):
            assert public.get(path).status_code == 404, path
            assert internal.get(path).status_code in (200, 503), path  # /ready may be 503 on a fresh state
        assert public.get("/api/v2/templates").status_code == 200
        assert internal.get("/api/v2/templates").status_code == 200, "the cluster may ask everything on its port"


@pytest.mark.parametrize("path", sorted(INTERNAL_PATHS))
def test_a_root_path_does_not_open_the_internal_paths_on_the_public_port(path: str) -> None:
    """Behind a proxy with a prefix uvicorn puts the root path in front of the path, as UVICORN_ROOT_PATH asks; the
    router takes it off and serves /health, so the check looks at the same path (review of D110). The scope is
    uvicorn's: TestClient leaves the root path out of the path."""
    passed: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        passed.append(scope["path"])

    sent: list[MutableMapping[str, Any]] = []

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request"}

    def scope(port: int) -> dict[str, Any]:
        return {
            "type": "http", "method": "GET", "path": "/kompendium" + path, "root_path": "/kompendium",
            "server": ("10.0.0.5", port), "headers": [], "query_string": b"",
        }  # fmt: skip

    asyncio.run(InternalOnly(app, INTERNAL)(scope(8000), receive, send))
    asyncio.run(InternalOnly(app, INTERNAL)(scope(INTERNAL), receive, send))

    assert sent[0]["status"] == 404 and passed == ["/kompendium" + path]


def test_the_paths_answer_as_before_while_the_port_is_off(sample_zims: dict[str, Path], tmp_path: Path) -> None:
    with TestClient(app_with_port(sample_zims, tmp_path, port=0), base_url="http://testserver:8000") as client:
        assert client.get("/health").status_code == 200 and client.get("/metrics").status_code == 200


def test_the_internal_paths_are_the_probes_metrics_and_status() -> None:
    assert INTERNAL_PATHS == {"/health", "/ready", "/metrics", "/api/v2/zim/status", "/api/v2/lehrplan/status"}


def test_the_port_is_on_by_default_and_never_the_public_one() -> None:
    assert Settings(_env_file=None).internal_port == INTERNAL
    with pytest.raises(ValueError, match="INTERNAL_PORT"):
        Settings(_env_file=None, internal_port=8000)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_the_workers_listen_on_both_ports(monkeypatch: pytest.MonkeyPatch) -> None:
    """uvicorn's command line binds one socket; the start binds the internal one beside it and hands both to the
    workers, as uvicorn does with its own (supervisors.Multiprocess)."""
    public, internal = free_port(), free_port()
    handed: list[list[int]] = []

    class Supervisor:
        def __init__(self, config: Any, sockets: list[socket.socket]) -> None:
            assert config.workers == 2 and config.factory and config.access_log is False
            handed.append([sock.getsockname()[1] for sock in sockets])
            for sock in sockets:
                sock.close()

        def run(self) -> None:
            pass

    monkeypatch.setattr(serve, "Multiprocess", Supervisor)
    command = [*serve.uvicorn_command(300), "--workers", "2"]
    command[command.index("--port") + 1] = str(public)
    command[command.index("--host") + 1] = "127.0.0.1"

    serve.serve_on_two_ports(command, internal)

    assert handed == [[public, internal]]


def test_the_start_reads_uvicorn_s_variables_as_its_command_line_does(monkeypatch: pytest.MonkeyPatch) -> None:
    """UVICORN_* settings - UVICORN_HTTP, UVICORN_LIMIT_CONCURRENCY - keep working with two ports."""
    monkeypatch.setenv("UVICORN_LIMIT_CONCURRENCY", "37")
    monkeypatch.setenv("UVICORN_HTTP", "h11")
    seen: list[Any] = []

    class Supervisor:
        def __init__(self, config: Any, sockets: list[socket.socket]) -> None:
            seen.append(config)
            for sock in sockets:
                sock.close()

        def run(self) -> None:
            pass

    monkeypatch.setattr(serve, "Multiprocess", Supervisor)
    command = [*serve.uvicorn_command(300), "--workers", "2"]
    command[command.index("--port") + 1] = str(free_port())
    command[command.index("--host") + 1] = "127.0.0.1"

    serve.serve_on_two_ports(command, free_port())

    assert seen[0].limit_concurrency == 37 and seen[0].http == "h11"


def test_with_the_internal_port_the_start_serves_both_ports_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No exec then: this process binds both sockets and supervises uvicorn's workers, with the variables uvicorn
    reads set as the one-port start hands them over."""
    # The start writes these into this process; monkeypatch puts back only what it saw, and an absent variable it
    # deletes without a trace: set first, then delete, so each is removed again afterwards (a leaked
    # PROMETHEUS_MULTIPROC_DIR turned the metrics of every later test to the multiprocess collector)
    for name in ("PROMETHEUS_MULTIPROC_DIR", "UVICORN_HTTP", "FORWARDED_ALLOW_IPS"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    monkeypatch.setattr(serve, "DEFAULT_DIR", str(tmp_path / "metrics"))
    monkeypatch.setenv("INTERNAL_PORT", "9123")
    monkeypatch.setenv("WEB_CONCURRENCY", "")
    monkeypatch.setattr(os, "execvpe", lambda *args: pytest.fail("no exec with the internal port"))
    started: list[tuple[list[str], int]] = []
    monkeypatch.setattr(serve, "serve_on_two_ports", lambda command, port: started.append((command, port)))
    get_settings.cache_clear()
    try:
        serve.main()
    finally:
        get_settings.cache_clear()

    [(command, port)] = started
    assert port == 9123 and command[1:3] == ["app.main:create_app", "--factory"]
    assert os.environ["WEB_CONCURRENCY"] == "2" and os.environ["PROMETHEUS_MULTIPROC_DIR"] == str(tmp_path / "metrics")


def test_the_operations_page_lists_the_internal_port_s_paths_as_the_code_has_them() -> None:
    """docs/betrieb.md, Erreichbarkeit, is where operators read which path answers on which port."""
    text = (ROOT / "docs" / "betrieb.md").read_text(encoding="utf-8")
    table = text[text.index("**Intern am Port 9000**") : text.index("**Intern am Port 8000**")]
    listed = {line.split("`")[1].split(" ", 1)[1] for line in table.splitlines() if line.startswith("| `GET ")}
    assert listed == INTERNAL_PATHS
