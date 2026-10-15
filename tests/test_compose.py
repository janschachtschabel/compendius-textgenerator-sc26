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


def test_the_api_publishes_both_ports_on_host_ports_of_their_own() -> None:
    """Several services on one host differ in API_BIND and INTERNAL_BIND (Jan, 2026-10-15). The public port in the
    container follows PUBLIC_PORT; the internal one stays 9000, because Compose refuses a container port 0, the value
    that switches the internal port off."""
    assert SERVICES["api"]["ports"] == [
        "${API_BIND:-0.0.0.0:8000}:${PUBLIC_PORT:-8000}",
        "${INTERNAL_BIND:-127.0.0.1:9000}:9000",
    ]
