"""Start command of the API image: prepare the metrics directory of the workers, then hand over to uvicorn.

The uvicorn workers keep their Prometheus values in files in ``PROMETHEUS_MULTIPROC_DIR`` and /metrics sums them.
Files of an earlier run would be counted again, so the start removes them, and only them: the directory is
operator configuration, and a mistaken value such as the state volume must not cost the curriculum cache or the
budget counter. The variable is set here for uvicorn only; the sidecars never load the metrics.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.settings import get_settings

DEFAULT_DIR = "/tmp/prometheus"  # noqa: S108  # container-local, emptied at every start
METRIC_FILES = ("counter_*.db", "gauge_*.db", "histogram_*.db", "summary_*.db")  # prometheus_client's file names
# All interfaces inside the container; compose publishes the port on 127.0.0.1 only
UVICORN = ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]  # noqa: S104
# A worker busy with one compendium answers the parent process late or not at all: the work happens in C code
# (ZIM reads, matching) that holds the interpreter lock, measured at 26 seconds without a break for one request.
# The parent kills a worker that stays silent longer than its healthcheck timeout - uvicorn allows five seconds -
# and the caller sees a broken connection instead of an answer. So the grace has to outlast a whole request.
HEALTHCHECK_MARGIN_S = 60


def clear_metric_files(directory: Path) -> None:
    """Create ``directory`` and delete the metric files of an earlier run in it; nothing else is touched."""
    directory.mkdir(parents=True, exist_ok=True)
    for pattern in METRIC_FILES:
        for path in directory.glob(pattern):
            path.unlink(missing_ok=True)


def uvicorn_command(request_timeout_s: int) -> list[str]:
    """The uvicorn call; a worker keeps its healthcheck grace until well past the request budget."""
    return [*UVICORN, "--timeout-worker-healthcheck", str(request_timeout_s + HEALTHCHECK_MARGIN_S)]


def main() -> None:
    directory = os.environ.get("PROMETHEUS_MULTIPROC_DIR") or DEFAULT_DIR
    clear_metric_files(Path(directory))
    command = uvicorn_command(get_settings().request_timeout_s)
    # exec: uvicorn takes over the process and receives the container's signals (clean shutdown)
    os.execvpe(command[0], command, {**os.environ, "PROMETHEUS_MULTIPROC_DIR": directory})  # noqa: S606


if __name__ == "__main__":
    main()
