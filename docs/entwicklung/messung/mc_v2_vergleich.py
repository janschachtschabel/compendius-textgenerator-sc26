"""M49 (V2) and M51 (D72): the runs to compare blind - best-quality-generated of M48 (bqg), the same profile changed
(M49: bqg-thema, the prototype writing about the topic as asked; M51: bqg-d72, the shipped profile of D72) and
best-coverage-generated of M48 (bcg) as the anchor.

Usage: python mc_v2_vergleich.py <m48_laeufe.json> <neue_laeufe.json> <out.json> [--name=bqg-thema]
"""

import json
import sys
from pathlib import Path

args = [arg for arg in sys.argv[1:] if not arg.startswith("--name=")]
name = next((arg.removeprefix("--name=") for arg in sys.argv[1:] if arg.startswith("--name=")), "bqg-thema")
m48 = json.loads(Path(args[0]).read_text(encoding="utf-8"))
new = json.loads(Path(args[1]).read_text(encoding="utf-8"))
rows = [{**r, "variant": "bqg"} for r in m48 if r["variant"] == "best-quality-generated"]
rows += [{**r, "variant": "bcg"} for r in m48 if r["variant"] == "best-coverage-generated"]
rows += [{**r, "variant": name} for r in new if r["variant"] == "best-quality-generated"]
Path(args[2]).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(rows), "Läufe:", {v: sum(r["variant"] == v for r in rows) for v in ("bqg", name, "bcg")})
