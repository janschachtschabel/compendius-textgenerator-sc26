"""The service is wired outside the web entry (audit 2026-09-18, A-03).

The builders of the registry, the service, the LLM gateway, part 2 and part 3 lived in app/main.py, so the CLI and the
sync and harvest sidecars imported the FastAPI module to get them - inside functions, to keep the API's metrics from
being created where PROMETHEUS_MULTIPROC_DIR points nowhere. They live in app/wiring.py now.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.test_architecture import imported_modules

ROOT = Path(__file__).resolve().parents[1]
WEB_ENTRY = {ROOT / "app" / "main.py", ROOT / "app" / "serve.py"}


def test_the_wiring_loads_neither_fastapi_nor_the_api_metrics() -> None:
    script = (
        "import sys, app.wiring, app.cli, app.cli_common, app.cli_collection; "
        "print(sorted(m for m in ('fastapi', 'app.main', 'app.observability.metrics') if m in sys.modules))"
    )
    loaded = subprocess.run(  # noqa: S603 - the interpreter of this test, a fixed script
        [sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, check=True, timeout=120
    ).stdout.strip()

    assert loaded == "[]"


def test_nothing_but_the_web_entry_imports_app_main() -> None:
    importers = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        if path in WEB_ENTRY:
            continue
        if "app.main" in imported_modules(path):  # also "from app import main" and relative imports
            importers.append(str(path.relative_to(ROOT)))

    assert importers == []
