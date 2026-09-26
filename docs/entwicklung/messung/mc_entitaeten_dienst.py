"""M36 in the service (D62): /api/v2/entities in its profiles, and with the check of the links, on the 40 materials.

M36 ran the LLM ways as prototypes next to the endpoint; D62 built them into it. This run asks the endpoint itself,
with ``node_id`` - it reads title, description and keywords of each material, the text M36 read - once per profile,
and keeps the Wikipedia articles each profile linked, with the words that named them, the LLM's report and the
seconds; no texts. The naming asks with the prompt of M36 word for word, so the b-api answers it from its cache: the
same answers, and times of the cache (the real ones are M36's). The check (link_check llm, which no profile sets)
sees only what the LLM named, where the check of M36 saw every link of a text: new questions, real times.
mc_entitaeten_dienst_auswertung.py rates the articles with the grades of M36.

The development container needs the LLM for balanced and best-quality (LLM_ENABLED, B_API_KEY). Its rate limit
(RATE_LIMIT, 60 a minute) turns away a run that is fast because the cache answers; a 429 waits and asks again.

Usage (from the project folder): python mc_entitaeten_dienst.py <out.json> [<api base>]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

GOLD = Path("eval") / "materialwahl" / "materialien.yaml"
WAIT_S = 10  # after a 429 of the rate limit
VARIANTS = {
    "llm-free": {"preset": "llm-free"},
    "balanced": {"preset": "balanced"},
    "best-quality": {"preset": "best-quality"},
    "mit Prüfung": {"preset": "balanced", "link_check": "llm"},
}

out_path = Path(sys.argv[1])
api = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8001"
rows: list[dict[str, Any]] = []
with httpx.Client(base_url=api, timeout=180) as http:
    for entry in yaml.safe_load(GOLD.read_text(encoding="utf-8"))["materialien"]:
        row: dict[str, Any] = {"node_id": entry["node_id"], "profile": {}}
        for profile, switches in VARIANTS.items():
            for _ in range(30):
                started = time.perf_counter()
                answer = http.post(
                    "/api/v2/entities",
                    json={"node_id": entry["node_id"], "repository": entry["repository"], **switches},
                )
                seconds = round(time.perf_counter() - started, 2)
                if answer.status_code != 429:
                    break
                time.sleep(WAIT_S)
            if answer.status_code != 200:
                row["profile"][profile] = {"status": answer.status_code, "sekunden": seconds}
                print(f"{entry['node_id']} {profile}: {answer.status_code} {answer.text[:120]}")
                continue
            body = answer.json()
            wiki = [e for e in body["entities"] if e["linked"] and e["article"]["project"] == "wikipedia"]
            row["profile"][profile] = {
                "methods": body["methods"],
                "artikel": list(dict.fromkeys(e["article"]["title"] for e in wiki)),
                "erwaehnungen": [[e["text"], e["article"]["title"], e["source"]] for e in wiki],
                "llm": body["llm"],
                "note": body["note"],
                "sekunden": seconds,
            }
        rows.append(row)
        counts = "  ".join(f"{p} {len(row['profile'][p].get('artikel', []))}" for p in VARIANTS)
        print(f"{entry['titel'][:40]:40s} {counts}", flush=True)

out_path.write_text(json.dumps({"materialien": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
