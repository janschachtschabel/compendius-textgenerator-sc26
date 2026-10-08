"""Start command of the image: only the metric files of an earlier run are removed, then uvicorn takes over."""

import os
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from app import serve
from app.settings import Settings
from tests.conftest import ROOT


def test_only_the_metric_files_of_an_earlier_run_are_removed(tmp_path: Path) -> None:
    metric_files = ["counter_7.db", "gauge_all_7.db", "gauge_livesum_8.db", "histogram_7.db", "summary_9.db"]
    # A mistaken PROMETHEUS_MULTIPROC_DIR such as the state volume must not cost the caches and the budget counter
    kept = ["lehrplan.db", "llm_budget.db", "notes.txt", "wlo_cache.db"]
    for name in metric_files + kept:
        (tmp_path / name).write_text("x", encoding="utf-8")
    serve.clear_metric_files(tmp_path)
    assert sorted(path.name for path in tmp_path.iterdir()) == kept


def test_a_missing_directory_is_created(tmp_path: Path) -> None:
    serve.clear_metric_files(tmp_path / "prometheus")
    assert (tmp_path / "prometheus").is_dir()


@pytest.mark.parametrize("configured", [True, False])
def test_the_start_prepares_the_directory_and_hands_over_to_uvicorn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configured: bool
) -> None:
    directory = tmp_path / "metrics"
    if configured:
        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(directory))
    else:
        monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
        monkeypatch.setattr(serve, "DEFAULT_DIR", str(directory))
    directory.mkdir()
    (directory / "counter_1.db").write_text("x", encoding="utf-8")
    calls: list[tuple[str, list[str], dict[str, str]]] = []

    def execvpe(file: str, args: list[str], env: dict[str, Any]) -> None:
        calls.append((file, args, env))

    monkeypatch.setattr(os, "execvpe", execvpe)
    serve.main()
    [(file, args, env)] = calls
    assert (file, args[:3]) == ("uvicorn", ["uvicorn", "app.main:create_app", "--factory"])
    assert env["PROMETHEUS_MULTIPROC_DIR"] == str(directory) and not (directory / "counter_1.db").exists()
    assert "PROMETHEUS_MULTIPROC_DIR" not in os.environ or configured  # the test process itself stays unchanged


@pytest.mark.parametrize("budget", [120, 300])
def test_a_worker_outlives_the_longest_request_it_may_serve(budget: int) -> None:
    """The parent kills a worker that stays silent; one compendium holds the interpreter lock far past 5 seconds."""
    command = serve.uvicorn_command(budget)
    timeout = int(command[command.index("--timeout-worker-healthcheck") + 1])
    assert timeout > budget


@pytest.mark.parametrize("budget", [120, 300])
def test_a_stop_lets_the_requests_in_flight_finish(budget: int) -> None:
    """Docker killed every running compendium 10 s after the SIGTERM of an update, while a request may take its whole
    budget (audit 2026-09-27, BE-06): uvicorn now waits for the requests in flight."""
    command = serve.uvicorn_command(budget)
    grace = int(command[command.index("--timeout-graceful-shutdown") + 1])
    assert grace > budget


def test_compose_waits_longer_for_the_api_than_uvicorn_waits_for_its_requests() -> None:
    """With the shipped REQUEST_TIMEOUT_S of OpenAI, the provider shipped (M75: 300 s). An operator who raises it, or
    runs academiccloud (600 s), raises the grace period with it, and can: the panel takes docker-compose.yml from main
    at every update, so a fixed 150 s let Docker kill the requests of a REQUEST_TIMEOUT_S of 300 half way (audit
    2026-09-28, BE-17)."""
    command = serve.uvicorn_command(Settings(_env_file=None).request_time_limit_s)
    grace = int(command[command.index("--timeout-graceful-shutdown") + 1])
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    stop = re.fullmatch(r"\$\{API_STOP_GRACE_PERIOD:-(\d+)s\}", compose["services"]["api"]["stop_grace_period"])
    assert stop is not None and int(stop.group(1)) > grace


@pytest.mark.parametrize(("configured", "expected"), [(None, "h11"), ("", "h11"), ("httptools", "httptools")])
def test_uvicorn_parses_with_h11_unless_the_operator_chose_otherwise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configured: str | None, expected: str
) -> None:
    """httptools bounds neither the URL nor the headers, and uvicorn collected a long URL in quadratic time; h11
    refuses a request line with headers over 16 KB (audit 2026-09-28, SE-19). An empty entry is the default."""
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    monkeypatch.setattr(serve, "DEFAULT_DIR", str(tmp_path / "metrics"))
    if configured is None:
        monkeypatch.delenv("UVICORN_HTTP", raising=False)
    else:
        monkeypatch.setenv("UVICORN_HTTP", configured)
    handed: list[dict[str, str]] = []
    monkeypatch.setattr(os, "execvpe", lambda file, args, env: handed.append(env))

    serve.main()

    assert handed[0]["UVICORN_HTTP"] == expected
