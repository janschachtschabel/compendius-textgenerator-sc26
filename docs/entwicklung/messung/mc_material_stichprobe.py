"""A sample of real WLO materials for the article choice of node input (M21): ids and titles, no descriptions.

Real requests bring a node - a material with title, description and keywords - instead of a clean topic (D45). To
measure how the service finds the main article for such a node, this script draws materials from the public search
of the WLO production repository: for each of ten subjects one page at an offset drawn with a fixed seed, and from
it the first materials that carry a description of some length, since that is the case node input is for. It asks
anonymously, like the service does for nodes.

It writes a draft of eval/materialwahl/materialien.yaml - node id, repository, title and subjects; the accepted main
articles are labelled by hand afterwards - and prints title, keywords and description for that labelling. The
descriptions stay out of the repository: they are texts of third parties, and the measurement reads them anew.

M25 drew a second sample with another seed to check the rules chosen on the first one, leaving out the materials of
the first (--ohne).

Usage (project venv, from the project root):
python docs/entwicklung/messung/mc_material_stichprobe.py <draft.yaml> [<materials per subject>] [--saat <seed>]
    [--ohne <gold.yaml>]
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import httpx
import yaml

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

REPOSITORY = "https://redaktion.openeduhub.net/edu-sharing/rest"
SEARCH = REPOSITORY + "/search/v1/queries/-home-/mds_oeh/ngsearch"
DISCIPLINE = "http://w3id.org/openeduhub/vocabs/discipline/"
SUBJECTS = {
    "460": "Physik",
    "100": "Chemie",
    "080": "Biologie",
    "380": "Mathematik",
    "240": "Geschichte",
    "220": "Geografie",
    "480": "Politik",
    "320": "Informatik",
    "120": "Deutsch",
    "700": "Wirtschaftskunde",
}
PAGE = 25
MIN_DESCRIPTION = 80  # characters; shorter ones say little more than the title
MAX_OFFSET = 4000  # the search pages far back slowly; the first 4000 of each subject are sample enough
SEED = 21


def search(client: httpx.Client, subject: str, skip: int, count: int) -> dict:  # type: ignore[type-arg]
    criteria = [
        {"property": "ngsearchword", "values": ["*"]},
        {"property": "ccm:taxonid", "values": [DISCIPLINE + subject]},
    ]
    params = {"contentType": "FILES", "maxItems": count, "skipCount": skip, "propertyFilter": "-all-"}
    response = client.post(SEARCH, params=params, json={"criteria": criteria})
    response.raise_for_status()
    return response.json()  # type: ignore[no-any-return]


def first(props: dict, key: str) -> str:  # type: ignore[type-arg]
    values = props.get(key) or [""]
    return str(values[0] or "").strip()


def option(name: str) -> str | None:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


out_path = Path(sys.argv[1])
per_subject = int(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else 4
rng = random.Random(int(option("--saat") or SEED))  # noqa: S311 - a reproducible sample, not a secret
known = option("--ohne")
taken_before = (
    {entry["node_id"] for entry in yaml.safe_load(Path(known).read_text(encoding="utf-8"))["materialien"]}
    if known
    else set()
)
entries = []
with httpx.Client(timeout=60, headers={"Accept": "application/json"}) as client:
    for subject, label in SUBJECTS.items():
        total = search(client, subject, 0, 1)["pagination"]["total"]
        skip = rng.randrange(0, max(1, min(total, MAX_OFFSET) - PAGE))
        taken = 0
        for node in search(client, subject, skip, PAGE)["nodes"]:
            props = node.get("properties") or {}
            title, description = (
                str(node.get("title") or first(props, "cclom:title")),
                first(props, "cclom:general_description"),
            )
            if node.get("type") != "ccm:io" or not title or len(description) < MIN_DESCRIPTION:
                continue
            if node["ref"]["id"] in taken_before:
                continue
            entries.append(
                {
                    "node_id": node["ref"]["id"],
                    "repository": REPOSITORY,
                    "titel": title,
                    "faecher": list(props.get("ccm:taxonid_DISPLAYNAME") or [label]),
                    "akzeptiert": [],
                }
            )
            keywords = ", ".join(props.get("cclom:general_keyword") or [])
            print(f"\n## {label} | {node['ref']['id']}\n{title}\nSchlagwörter: {keywords}\n{description[:700]}")
            taken += 1
            if taken == per_subject:
                break
        print(f"\n[{label}: {total} Materialien, Seite ab {skip}, {taken} genommen]")

out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(yaml.safe_dump({"materialien": entries}, allow_unicode=True, sort_keys=False), encoding="utf-8")
print(f"\n{len(entries)} Materialien nach {out_path}")
