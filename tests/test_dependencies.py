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
    declared = _declared()
    missing: set[str] = set()
    for module in _imported_modules():
        if module in NAMESPACES:
            continue  # its parts are checked one by one below
        found = {_normalized(distribution) for distribution in distributions.get(module, [module])}
        missing |= found - declared
    # A namespace package is shared by many distributions, most of them only dependencies of others: each part the
    # service imports needs the distribution of that part (review of D115)
    for name in _imported_names():
        owner = next((owner for prefix, owner in NAMESPACES.get(name.split(".")[0], ()) if _within(name, prefix)), None)
        if name.split(".")[0] in NAMESPACES:
            assert owner is not None, f"{name}: no distribution named for this part of a namespace package"
            missing |= {owner} - declared
    assert not missing, sorted(missing)


# The parts of a namespace package and their distributions, the longest prefix first
NAMESPACES: dict[str, tuple[tuple[str, str], ...]] = {
    "opentelemetry": (
        ("opentelemetry.exporter.otlp.proto.http", "opentelemetry-exporter-otlp-proto-http"),
        ("opentelemetry.propagators.b3", "opentelemetry-propagator-b3"),
        ("opentelemetry.sdk", "opentelemetry-sdk"),
        ("opentelemetry.trace", "opentelemetry-api"),
        ("opentelemetry.context", "opentelemetry-api"),
        ("opentelemetry.propagators.composite", "opentelemetry-api"),
        ("opentelemetry", "opentelemetry-api"),
    )
}


def _within(name: str, prefix: str) -> bool:
    """The top level alone (``from opentelemetry import trace``) names only itself: a new part needs its own entry."""
    return name == prefix or ("." in prefix and name.startswith(prefix + "."))


def _imported_names() -> set[str]:
    """The dotted modules ``app`` imports, ``from a.b import c`` as ``a.b``."""
    found: set[str] = set()
    for path in (ROOT / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module)
    return found


def test_the_server_comes_without_reload_and_websocket_packages() -> None:
    """uvicorn[standard] put watchfiles (for --reload) and websockets in the image, and the service uses neither: it
    never reloads and serves no WebSocket route (audit 2026-09-18, DEP-02). uvloop and httptools are declared on their
    own: uvicorn runs its event loop on uvloop where it is installed, and UVICORN_HTTP=httptools stays a choice."""
    locked = {package["name"] for package in tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))["package"]}
    assert not locked & {"watchfiles", "websockets"}
    assert {"uvloop", "httptools"} <= _declared()
