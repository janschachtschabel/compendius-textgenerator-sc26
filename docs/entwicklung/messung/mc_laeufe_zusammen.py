"""M52: the runs of mc_kompendium_profil.py from more than one file as one round - each profile on each topic once,
under its profile's name - for the blind sheets of mc_profilvergleich_boegen.py and the evaluation.

M52 takes llm-free, balanced and best-coverage-generated from its own runs and best-quality and best-quality-generated
from those of M51, all with the code of D72.

Usage: python mc_laeufe_zusammen.py <out.json> <runs.json>:<variant>[,<variant>] [...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    rows: list[dict] = []
    for source in sys.argv[2:]:
        path, _, variants = source.rpartition(":")
        wanted = set(variants.split(","))
        rows += [r for r in json.loads(Path(path).read_text(encoding="utf-8")) if r.get("variant") in wanted]
    seen = [(r["topic"], r["variant"]) for r in rows]
    doubled = sorted({pair for pair in seen if seen.count(pair) > 1})
    if doubled:
        raise SystemExit(f"doppelte Läufe: {doubled}")
    failed = [pair for pair, r in zip(seen, rows, strict=True) if r.get("error")]
    if failed:
        raise SystemExit(f"Läufe mit Fehler: {failed}")
    Path(sys.argv[1]).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = {variant: sum(r["variant"] == variant for r in rows) for variant in dict.fromkeys(r["variant"] for r in rows)}
    print(len(rows), "Läufe:", counts)


if __name__ == "__main__":
    main()
