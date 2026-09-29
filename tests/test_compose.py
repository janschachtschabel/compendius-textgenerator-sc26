"""What docker-compose.yml grants its services (audit 2026-09-27, SE-12).

The file says that no service has Linux capabilities or gains new privileges, but the Prometheus service of the
profile monitoring ran without the hardening every other service carries (audit 2026-09-29, O5).
"""

from __future__ import annotations

import pytest
import yaml

from tests.conftest import ROOT

SERVICES: dict[str, dict[str, object]] = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))[
    "services"
]


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_no_service_has_capabilities_or_gains_privileges(name: str) -> None:
    service = SERVICES[name]

    assert service.get("cap_drop") == ["ALL"]
    assert service.get("security_opt") == ["no-new-privileges:true"]
