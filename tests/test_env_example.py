"""The example configuration documents every variable the service reads (PLAN.md 3.5).

A variable that only lives in ``app/settings.py`` is invisible to an operator, and a line in the example that
no longer matches a setting is worse than none: it promises an effect the service does not have.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.settings import Settings

EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"
# Read by the processes themselves, not by Settings: uvicorn takes the first two, app/serve.py the third
PROCESS_VARIABLES = {"WEB_CONCURRENCY", "FORWARDED_ALLOW_IPS", "PROMETHEUS_MULTIPROC_DIR"}
# The example is committed, so everything that would be a credential stays empty in it
SECRETS = ("B_API_KEY", "EDU_SHARING_USER", "EDU_SHARING_PASSWORD", "ADMIN_TOKEN", "METRICS_TOKEN")

_LINE = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=(.*)$", re.M)


def documented() -> dict[str, str]:
    """Variable -> value in .env.example; a commented line documents the variable as well."""
    return {match.group(1): match.group(2).strip() for match in _LINE.finditer(EXAMPLE.read_text(encoding="utf-8"))}


def settings_variables() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


def test_every_setting_has_a_line_in_the_example() -> None:
    missing = settings_variables() - set(documented())
    assert not missing, f"not documented in .env.example: {sorted(missing)}"


def test_the_variables_of_the_processes_are_documented_too() -> None:
    missing = PROCESS_VARIABLES - set(documented())
    assert not missing, f"not documented in .env.example: {sorted(missing)}"


def test_the_example_names_no_variable_the_service_reads_nowhere() -> None:
    stale = set(documented()) - settings_variables() - PROCESS_VARIABLES
    assert not stale, f"no longer a setting: {sorted(stale)}"


def test_no_credential_carries_a_value() -> None:
    values = documented()
    filled = [name for name in SECRETS if values.get(name)]
    assert not filled, f"the committed example must not carry credentials: {filled}"


_VARIABLE_LINE = re.compile(r"^[A-Z][A-Z0-9_]*=.*$")
PROSE = (
    Path(__file__).resolve().parents[1] / "README.md",
    *(Path(__file__).resolve().parents[1] / "docs").glob("*.md"),
)


def test_the_example_is_nothing_but_variable_lines() -> None:
    """No comments, no blank lines: the file is parsed line by line by the hosting we import into.

    A hoster that reads every line on its own chokes on a prose comment and can take "# FOO=bar" for a
    variable named "# FOO". So the explanations live in README.md and docs/, and this file stays machine
    readable - which is also why the test below makes sure the explanations really are there.
    """
    offenders = [
        f"{number}: {line}"
        for number, line in enumerate(EXAMPLE.read_text(encoding="utf-8").splitlines(), start=1)
        if not _VARIABLE_LINE.match(line)
    ]
    assert not offenders, "only NAME=value lines belong in .env.example:\n" + "\n".join(offenders)


def test_every_variable_is_explained_in_the_prose() -> None:
    """What the comments used to say has to be somewhere a reader finds it, or it is gone."""
    prose = "\n".join(path.read_text(encoding="utf-8") for path in PROSE)
    missing = sorted(name for name in documented() if name not in prose)
    assert not missing, f"named in .env.example but explained nowhere in README.md or docs/: {missing}"
