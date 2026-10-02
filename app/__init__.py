"""compendious-text-fastapi v2: compendium generation from Kiwix ZIM knowledge."""

import os

__version__ = "2.7.1"


def revision() -> str | None:
    """The commit the image was built from - the publish job sets GIT_REVISION -, ``None`` for a local build.

    The version changes only with a release, so after an update only the revision tells which code runs (audit
    2026-09-27, BE-03)."""
    return os.environ.get("GIT_REVISION") or None
