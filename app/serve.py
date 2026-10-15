"""Start command of the API image: prepare the metrics directory of the workers, then hand over to uvicorn.

The uvicorn workers keep their Prometheus values in files in ``PROMETHEUS_MULTIPROC_DIR`` and /metrics sums them.
Files of an earlier run would be counted again, so the start removes them, and only them: the directory is
operator configuration, and a mistaken value such as the state volume must not cost the curriculum cache or the
indexes. The variable is set here for uvicorn only; the sidecars never load the metrics.

uvicorn parses with h11 unless ``UVICORN_HTTP`` names another parser (audit 2026-09-28, SE-19): httptools, uvicorn's
choice where it is installed, bounds neither the URL nor the headers, and uvicorn collected a long URL piece by piece
in quadratic time. h11 answers 400 to a request line with headers over 16 KB.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import tempfile
from pathlib import Path

from uvicorn import Config, Server
from uvicorn.config import STARTUP_FAILURE
from uvicorn.main import main as uvicorn_cli
from uvicorn.supervisors import Multiprocess

from app.logging import uvicorn_log_config
from app.settings import DEFAULT_PUBLIC_PORT, get_settings

DEFAULT_DIR = "/tmp/prometheus"  # noqa: S108  # container-local, emptied at every start
METRIC_FILES = ("counter_*.db", "gauge_*.db", "histogram_*.db", "summary_*.db")  # prometheus_client's file names
# All interfaces inside the container; compose publishes the port on API_BIND, all interfaces unless set otherwise
UVICORN = ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0"]  # noqa: S104
# A worker busy with one compendium answers the parent process late or not at all: the work happens in C code
# (ZIM reads, matching) that holds the interpreter lock, measured at 26 seconds without a break for one request.
# The parent kills a worker that stays silent longer than its healthcheck timeout - uvicorn allows five seconds -
# and the caller sees a broken connection instead of an answer. So the grace has to outlast a whole request.
HEALTHCHECK_MARGIN_S = 60
# After SIGTERM uvicorn lets the requests in flight finish for their budget plus this; Docker killed them after 10 s
# (audit 2026-09-27, BE-06), and docker-compose.yml waits 630 s (API_STOP_GRACE_PERIOD), longer than this with
# the longest budget of a provider, academiccloud's 600 s (D94)
GRACEFUL_MARGIN_S = 15
# Variables uvicorn reads itself, with the service's defaults. A value the operator sets wins; an empty entry, as a
# panel writes one left blank, counts as none - uvicorn read WEB_CONCURRENCY= with int() and stopped (BE-13)
UVICORN_DEFAULTS = {"UVICORN_HTTP": "h11", "WEB_CONCURRENCY": "2", "FORWARDED_ALLOW_IPS": "127.0.0.1,::1"}
# In the temporary directory of the container, which compose leaves writable
LOG_CONFIG_FILE = "kompendium-logging.json"


def clear_metric_files(directory: Path) -> None:
    """Create ``directory`` and delete the metric files of an earlier run in it; nothing else is touched."""
    directory.mkdir(parents=True, exist_ok=True)
    for pattern in METRIC_FILES:
        for path in directory.glob(pattern):
            path.unlink(missing_ok=True)


def write_log_config(level: str, format_: str) -> Path:
    """The service's logging for uvicorn's own process and its workers, as the file ``--log-config`` reads."""
    path = Path(tempfile.gettempdir()) / LOG_CONFIG_FILE
    path.write_text(json.dumps(uvicorn_log_config(level, format_)), encoding="utf-8")
    return path


def uvicorn_command(
    request_timeout_s: int, log_config: Path | None = None, port: int = DEFAULT_PUBLIC_PORT
) -> list[str]:
    """The uvicorn call on ``port`` (PUBLIC_PORT); a worker keeps its healthcheck grace until well past the request
    budget, and a stop waits for the requests in flight."""
    return [
        *UVICORN,
        "--port",
        str(port),
        "--timeout-worker-healthcheck",
        str(request_timeout_s + HEALTHCHECK_MARGIN_S),
        "--timeout-graceful-shutdown",
        str(request_timeout_s + GRACEFUL_MARGIN_S),
        # The service logs each request itself, with duration and request id (app/api/request_log.py)
        "--no-access-log",
        *(["--log-config", str(log_config)] if log_config is not None else []),
    ]


def serve_on_two_ports(command: list[str], internal_port: int) -> None:
    """uvicorn as its command line would run ``command``, its workers listening on the internal port as well (D110).

    The command line binds one socket, so the start reads the command through uvicorn's own parser - the UVICORN_*
    variables included, as ``uvicorn`` reads them - binds the public socket the way uvicorn does and the internal one
    beside it, and hands both to the workers, as uvicorn does with its one. This process stays the container's main
    process and passes the signals on through uvicorn's supervisor.
    """
    params = dict(uvicorn_cli.make_context("uvicorn", command[1:]).params)
    app = params.pop("app")
    sys.path.insert(0, params.pop("app_dir"))
    params["headers"] = [header.split(":", 1) for header in params["headers"]]
    config = Config(app, **params)
    sockets = [config.bind_socket(), _bind(config.host, internal_port)]
    if config.workers > 1:
        Multiprocess(config, sockets=sockets).run()
        return
    server = Server(config)
    try:
        server.run(sockets=sockets)
    except KeyboardInterrupt:  # as uvicorn.main.run: Ctrl+C with one worker ends without a traceback
        pass
    if not server.started:
        raise SystemExit(STARTUP_FAILURE)


def _bind(host: str, port: int) -> socket.socket:
    """A listening socket on ``port`` as uvicorn binds its own (Config.bind_socket), inherited by the workers."""
    sock = socket.socket(family=socket.AF_INET6 if ":" in host else socket.AF_INET)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError as error:  # as Config.bind_socket: a port in use is a failed start, not a traceback
        logging.getLogger("uvicorn.error").error("Internal port %d: %s", port, error)
        raise SystemExit(STARTUP_FAILURE) from error
    sock.set_inheritable(True)
    logging.getLogger("uvicorn.error").info("Internal port %d: /health, /ready, /metrics and the status (D110)", port)
    return sock


def main() -> None:
    directory = os.environ.get("PROMETHEUS_MULTIPROC_DIR") or DEFAULT_DIR
    clear_metric_files(Path(directory))
    settings = get_settings()
    log_config = write_log_config(settings.log_level, settings.log_format)
    command = uvicorn_command(settings.request_time_limit_s, log_config, port=settings.public_port)
    defaults = {name: value for name, value in UVICORN_DEFAULTS.items() if not os.environ.get(name, "").strip()}
    environment = {**defaults, "PROMETHEUS_MULTIPROC_DIR": directory}
    if settings.internal_port:
        os.environ.update(environment)  # the workers inherit it, uvicorn's parser reads it
        serve_on_two_ports(command, settings.internal_port)
        return
    # exec: uvicorn takes over the process and receives the container's signals (clean shutdown)
    os.execvpe(command[0], command, {**os.environ, **environment})  # noqa: S606


if __name__ == "__main__":
    main()
