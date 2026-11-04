"""The Helm chart in deploy/helm: its version follows the release, its alert rules follow monitoring/alerts.yml, and
what it renders keeps the promises of the handover (docs/uebergabe/helm-values.example.yaml).

The platform team deploys every image version with the chart of the same tag. A release that bumps pyproject.toml
and forgets Chart.yaml would push a chart whose default image is the previous release; a change to the alert rules
that forgets the copy in the chart would leave production with the old rules. The rendering tests need helm; the
GitHub CI installs it (ci.yml), elsewhere they are skipped.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from typing import Any

import pytest
import yaml

from tests.conftest import ROOT

CHART = ROOT / "deploy" / "helm" / "compendious-text-generator"
ALL_ON = CHART / "ci" / "all-on-values.yaml"
HELM = shutil.which("helm")
ON_GITHUB = os.environ.get("GITHUB_ACTIONS") == "true"
UPDATERS = {
    "zim-updater": ["compendium", "zim", "sync"],
    "lehrplan-updater": ["compendium", "lehrplan", "harvest"],
    "wikidata-updater": ["compendium", "wikidata", "sync"],
    "gnd-updater": ["compendium", "gnd", "sync"],
}
needs_helm = pytest.mark.skipif(HELM is None and not ON_GITHUB, reason="helm is not installed")


def test_the_chart_carries_the_version_of_the_release() -> None:
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    chart = yaml.safe_load((CHART / "Chart.yaml").read_text(encoding="utf-8"))

    assert chart["version"] == declared, "Chart.yaml version mit pyproject.toml heben"
    assert chart["appVersion"] == declared, "Chart.yaml appVersion mit pyproject.toml heben"


def test_the_chart_ships_the_alert_rules_of_the_repository() -> None:
    """The PrometheusRule reads files/alerts.yml (.Files.Get reaches no file outside the chart)."""
    copy = (CHART / "files" / "alerts.yml").read_text(encoding="utf-8")

    assert copy == (ROOT / "monitoring" / "alerts.yml").read_text(encoding="utf-8"), (
        "cp monitoring/alerts.yml deploy/helm/compendious-text-generator/files/alerts.yml"
    )


def render(*args: str) -> list[dict[str, Any]]:
    assert HELM is not None, "the runner of GitHub installs helm; without it the chart went untested"
    done = subprocess.run(  # noqa: S603 - helm on the chart of this repository
        [HELM, "template", "kt", str(CHART), "--namespace", "wlo", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert done.returncode == 0, done.stderr[-4000:]
    return [doc for doc in yaml.safe_load_all(done.stdout) if doc]


def of_kind(docs: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [doc for doc in docs if doc["kind"] == kind]


def component(doc: dict[str, Any]) -> str:
    return str(doc["metadata"]["labels"]["app.kubernetes.io/component"])


def pod_spec(doc: dict[str, Any]) -> dict[str, Any]:
    spec = doc["spec"]["jobTemplate"]["spec"] if doc["kind"] == "CronJob" else doc["spec"]
    return dict(spec["template"]["spec"])


@needs_helm
def test_the_api_serves_on_8000_and_answers_its_probes_on_9000() -> None:
    [api] = [doc for doc in of_kind(render(), "Deployment") if component(doc) == "api"]
    spec = pod_spec(api)
    [container] = spec["containers"]

    assert {port["name"]: port["containerPort"] for port in container["ports"]} == {"http": 8000, "internal": 9000}
    probes = [container[name]["httpGet"] for name in ("startupProbe", "readinessProbe", "livenessProbe")]
    assert [(probe["path"], probe["port"]) for probe in probes] == [
        ("/health", "internal"),
        ("/ready", "internal"),
        ("/health", "internal"),
    ]
    assert spec["enableServiceLinks"] is False
    assert spec["terminationGracePeriodSeconds"] == 630
    assert spec["securityContext"]["runAsUser"] == 10001 and spec["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"] == {"drop": ["ALL"]}
    mounts = {mount["name"]: mount for mount in container["volumeMounts"]}
    assert mounts["zim"]["readOnly"] is True and mounts["state"]["readOnly"] is True  # only the updaters write (D113)
    secrets = [var for var in container["env"] if "valueFrom" in var]
    assert secrets and all(var["valueFrom"]["secretKeyRef"]["optional"] is True for var in secrets)


@needs_helm
def test_the_ingress_reaches_only_the_public_port() -> None:
    docs = render("--values", str(ALL_ON))
    [ingress] = of_kind(docs, "Ingress")
    [service] = of_kind(docs, "Service")
    ports = {port["name"]: port["port"] for port in service["spec"]["ports"]}
    backends = [
        path["backend"]["service"]["port"] for rule in ingress["spec"]["rules"] for path in rule["http"]["paths"]
    ]

    assert ports == {"http": 8000, "internal": 9000}
    assert backends and all(backend == {"name": "http"} for backend in backends)
    # and no public path covers an internal one (docs/betrieb.md, Erreichbarkeit)
    internal = ["/health", "/ready", "/metrics", "/api/v2/zim/status", "/api/v2/zim/sync", "/api/v2/lehrplan/harvest"]
    paths = [path["path"].rstrip("/") for path in ingress["spec"]["rules"][0]["http"]["paths"]]
    assert not [(path, hidden) for path in paths for hidden in internal if f"{hidden}/".startswith(f"{path}/")]


@needs_helm
def test_the_network_policy_opens_each_port_to_its_own_callers_only() -> None:
    policies = {component(doc): doc for doc in of_kind(render(), "NetworkPolicy")}
    api = policies.pop("api")["spec"]

    assert [rule["ports"] for rule in api["ingress"]] == [
        [{"port": "http", "protocol": "TCP"}],
        [{"port": "internal", "protocol": "TCP"}],
    ]
    assert [rule["from"][0]["namespaceSelector"]["matchLabels"] for rule in api["ingress"]] == [
        {"kubernetes.io/metadata.name": "b-api"},
        {"kubernetes.io/metadata.name": "monitoring"},
    ]
    assert set(policies) == set(UPDATERS)
    for policy in [api, *(doc["spec"] for doc in policies.values())]:
        assert policy["policyTypes"] == ["Ingress", "Egress"]
        assert {(port["port"], port["protocol"]) for port in policy["egress"][0]["ports"]} == {(53, "UDP"), (53, "TCP")}
    assert all(doc["spec"]["ingress"] == [] for doc in policies.values())


@needs_helm
def test_the_updaters_run_once_a_night_staggered_or_loop_as_before() -> None:
    docs = render()
    cronjobs = {component(doc): doc for doc in of_kind(docs, "CronJob")}
    deployments = {component(doc): doc for doc in of_kind(render("--set", "updaters.mode=deployment"), "Deployment")}

    assert {name: doc["spec"]["schedule"] for name, doc in cronjobs.items()} == {
        "gnd-updater": "15 1 * * *",
        "wikidata-updater": "15 2 * * *",
        "lehrplan-updater": "15 3 * * 0",
        "zim-updater": "15 4 * * 0",
    }
    for name, doc in cronjobs.items():
        assert doc["spec"]["concurrencyPolicy"] == "Forbid" and doc["spec"]["timeZone"] == "Europe/Berlin"
        assert pod_spec(doc)["containers"][0]["command"] == UPDATERS[name]  # once, without --loop
        assert pod_spec(doc)["restartPolicy"] == "Never"
    # the first run comes at the installation, not at the first night
    assert {component(doc) for doc in of_kind(docs, "Job")} == set(UPDATERS)
    for name, command in UPDATERS.items():
        deployment = deployments[name]
        assert deployment["spec"]["replicas"] == 1 and deployment["spec"]["strategy"] == {"type": "Recreate"}
        assert pod_spec(deployment)["containers"][0]["command"] == [*command, "--loop"]
    assert not of_kind(render("--set", "updaters.mode=deployment"), "CronJob")


@needs_helm
def test_in_cronjob_mode_the_rules_leave_out_the_signs_of_life_of_a_loop() -> None:
    """A CronJob writes no sign of life between its runs: the *Silent alerts would fire for good."""

    def alerts(*args: str) -> set[str]:
        [rule] = of_kind(render("--set", "prometheusRule.enabled=true", *args), "PrometheusRule")
        return {rule["alert"] for group in rule["spec"]["groups"] for rule in group["rules"]}

    source = yaml.safe_load((ROOT / "monitoring" / "alerts.yml").read_text(encoding="utf-8"))
    every = {rule["alert"] for group in source["groups"] for rule in group["rules"]}
    silent = {name for name in every if name.endswith("Silent")}

    assert len(silent) == 4
    assert alerts("--set", "updaters.mode=deployment") == every
    assert alerts() == (every - silent) | {"KompendiumUpdaterRunFailed"}


@needs_helm
def test_the_service_monitor_scrapes_the_internal_port_as_the_job_the_rules_ask_for() -> None:
    [monitor] = of_kind(render("--values", str(ALL_ON)), "ServiceMonitor")
    [endpoint] = monitor["spec"]["endpoints"]

    assert endpoint["port"] == "internal" and endpoint["path"] == "/metrics"
    assert {"targetLabel": "job", "replacement": "kompendium"} in endpoint["relabelings"]
    assert endpoint["authorization"]["credentials"] == {"name": "kompendium-secrets", "key": "METRICS_TOKEN"}
