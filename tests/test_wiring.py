"""The service is wired outside the web entry (audit 2026-09-18, A-03).

The builders of the registry, the service, the LLM gateway, part 2 and part 3 lived in app/main.py, so the CLI and the
sync and harvest sidecars imported the FastAPI module to get them - inside functions, to keep the API's metrics from
being created where PROMETHEUS_MULTIPROC_DIR points nowhere. They live in app/wiring.py now.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.wiring import build_collections
from tests.conftest import make_settings
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


def test_a_password_without_a_user_is_named_at_start(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Without EDU_SHARING_USER the client reads anonymously, and a password set alone was dropped without a word."""
    value = "geheim-4711"
    with caplog.at_level("WARNING", logger="app.wiring"):
        builder = build_collections(make_settings([], tmp_path / "alone", edu_sharing_password=value))
    assert builder is not None and not builder.client.has_account
    builder.client.close()
    named = [record for record in caplog.records if "EDU_SHARING_PASSWORD" in record.getMessage()]
    assert len(named) == 1 and named[0].levelname == "WARNING" and "EDU_SHARING_USER" in named[0].getMessage()
    assert value not in caplog.text

    caplog.clear()
    with caplog.at_level("WARNING", logger="app.wiring"):
        both = make_settings([], tmp_path / "both", edu_sharing_user="wlo-gast", edu_sharing_password=value)
        builder = build_collections(both)
    assert builder is not None and builder.client.has_account
    builder.client.close()
    assert "EDU_SHARING_PASSWORD" not in caplog.text and value not in caplog.text


def test_credentials_in_the_repository_address_are_refused(tmp_path: Path) -> None:
    """httpx sends a name and password written into the address, and the address reaches 404 texts, the links of part
    3 and the log: they belong in EDU_SHARING_USER and EDU_SHARING_PASSWORD (audit 2026-10-15)."""
    address = "https://wlo-gast:geheim-4711@repository.example/edu-sharing/rest"
    with pytest.raises(ValueError, match="EDU_SHARING_USER") as refused:
        make_settings([], tmp_path / "s", edu_sharing_base_url=address)
    assert "geheim-4711" not in str(refused.value)


def test_an_account_over_plain_http_is_named_at_start(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Basic auth over http travels readable for anyone on the way."""
    settings = make_settings(
        [],
        tmp_path / "s",
        edu_sharing_base_url="http://repository.example/edu-sharing/rest",
        edu_sharing_user="wlo-gast",
        edu_sharing_password="geheim-4711",
    )
    with caplog.at_level("WARNING", logger="app.wiring"):
        builder = build_collections(settings)
    assert builder is not None
    builder.client.close()
    assert any("http" in r.getMessage() and "EDU_SHARING_BASE_URL" in r.getMessage() for r in caplog.records)
    assert "geheim-4711" not in caplog.text
