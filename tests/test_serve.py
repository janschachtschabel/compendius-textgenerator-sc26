"""Start command of the image: only the metric files of an earlier run are removed, then uvicorn takes over."""

import os
from pathlib import Path
from typing import Any

import pytest

from app import serve


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
