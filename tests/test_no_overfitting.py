"""Guard against topic-specific vocabulary in code, configuration and built-in templates.

The prototype had optics-specific signal words in five matchers. Anything topic specific
belongs into a custom template, never into the package.
"""

from pathlib import Path

from tests.conftest import ROOT

FORBIDDEN = (
    "optotechniker",
    "feinoptiker",
    "augenoptiker",
    "ernst abbe",
    "kepler",
    "fraunhofer",
    "visby",
    "sehhilfen",
    "wellenoptik",
    "brechungsgesetz",
    "laserklasse",
    "photosynthese",
    "primzahl",
)


def _files() -> list[Path]:
    files = list((ROOT / "app").rglob("*.py"))
    files += list((ROOT / "app" / "templates" / "builtin").glob("*.json"))
    files += list((ROOT / "config").glob("*.yaml"))
    return files


def test_no_topic_specific_terms_in_package() -> None:
    offenders: list[str] = []
    for path in _files():
        text = path.read_text(encoding="utf-8").lower()
        for term in FORBIDDEN:
            if term in text:
                offenders.append(f"{path.relative_to(ROOT)}: {term}")
    assert not offenders, "topic-specific vocabulary found:\n" + "\n".join(offenders)
