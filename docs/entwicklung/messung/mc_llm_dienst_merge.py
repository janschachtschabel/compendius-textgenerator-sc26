"""Adds the run of mc_llm_dienst.py to a copy of the export, so mc_eval.py and mc_final_tables.py measure it like every
other method: topic["mine"]["gold"]["matcher=llm (Dienst)"] with its classification, selection and wall time.

Usage: python mc_llm_dienst_merge.py <export.json> <llm_dienst.json> <out_export.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

LABEL = "matcher=llm (Dienst)"

export = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
run = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))["topics"]
for topic in export["topics"]:
    data = run[topic["topic"]]
    topic["mine"]["gold"][LABEL] = {
        "ms": int(data["wall_seconds"] * 1000),
        "classified": data["classified"],
        "selection": data["selection"],
    }
Path(sys.argv[3]).write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
print(f"{LABEL} in {len(export['topics'])} Themen übernommen")
