"""M49 (V2): the runs to compare blind - best-quality-generated of M48 (bqg), the same profile writing about the
topic as asked (bqg-thema, the prototype) and best-coverage-generated of M48 (bcg) as the anchor.

Usage: python mc_v2_vergleich.py <m48_laeufe.json> <m49_v2_laeufe.json> <out.json>
"""

import json
import sys
from pathlib import Path

m48 = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
v2 = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
rows = [{**r, "variant": "bqg"} for r in m48 if r["variant"] == "best-quality-generated"]
rows += [{**r, "variant": "bcg"} for r in m48 if r["variant"] == "best-coverage-generated"]
rows += [{**r, "variant": "bqg-thema"} for r in v2 if r["variant"] == "best-quality-generated"]
Path(sys.argv[3]).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(rows), "Läufe:", {v: sum(r["variant"] == v for r in rows) for v in ("bqg", "bqg-thema", "bcg")})
