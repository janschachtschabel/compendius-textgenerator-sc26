"""The release version is written down three times, and all three must agree."""

import tomllib

from app import __version__
from tests.conftest import ROOT


def test_the_package_the_app_and_the_lock_name_one_version() -> None:
    """pyproject.toml names the package, ``app.__version__`` is what /health, the metrics and the ZIM user agent
    report, and uv.lock pins the project for ``uv sync --locked``. A release that bumps one and forgets another would
    report a version that is not the one installed, or fail the image build."""
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = next(package["version"] for package in lock["package"] if package["name"] == "compendious-text-fastapi")

    assert __version__ == declared == locked
