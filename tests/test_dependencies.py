"""Every package the service imports is one it declares (audit 2026-09-27, AB-02)."""

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions

from tests.conftest import ROOT


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared() -> set[str]:
    """The distributions pyproject.toml names, the extras included."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    extras = [requirement for group in project.get("optional-dependencies", {}).values() for requirement in group]
    return {
        _normalized(re.split(r"[\s<>=!~\[;]", requirement, maxsplit=1)[0])
        for requirement in [*project["dependencies"], *extras]
    }


def _imported_modules() -> set[str]:
    """The top-level modules that ``app`` imports, its own and the standard library's left out."""
    found: set[str] = set()
    for path in (ROOT / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found - set(sys.stdlib_module_names) - {"app"}


def test_every_package_the_app_imports_is_declared() -> None:
    """A package that comes only as another one's dependency goes when that one drops it, and the service fails at its
    import. fastapi brought starlette and anyio, which the service imports itself, while pyproject.toml named neither."""
    distributions = packages_distributions()
    imported = {
        _normalized(distribution)
        for module in _imported_modules()
        for distribution in distributions.get(module, [module])
    }
    assert imported <= _declared(), sorted(imported - _declared())


def test_the_server_comes_without_reload_and_websocket_packages() -> None:
    """uvicorn[standard] put watchfiles (for --reload) and websockets in the image, and the service uses neither: it
    never reloads and serves no WebSocket route (audit 2026-09-18, DEP-02). uvloop and httptools are declared on their
    own: uvicorn runs its event loop on uvloop where it is installed, and UVICORN_HTTP=httptools stays a choice."""
    locked = {package["name"] for package in tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))["package"]}
    assert not locked & {"watchfiles", "websockets"}
    assert {"uvloop", "httptools"} <= _declared()
