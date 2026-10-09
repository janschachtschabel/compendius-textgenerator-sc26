"""M91: blind sheets of the profile comparison with one topic per sheet - the variants as texts A to E in a seeded
random order, cut as in M48 (blocks 1-4 and 8-10, without citation numbers and model knowledge labels).

mc_profilvergleich_boegen.py puts three topics on a sheet; at ten times the block budget (D102) the verbatim texts are
so long that five texts on three topics make a sheet of about 450 KB. One topic per sheet keeps it near 150 KB. The
key goes into a folder of its own, in the form mc_profilvergleich_auswertung.py reads; the raters' answers of all
sheets are merged per rater for it.

Usage: python mc_profilvergleich_boegen_je_thema.py <runs.json> <folder> <key folder> --variants=a,b,... [--seed=91]
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from mc_profilvergleich_boegen import KINDS, LETTERS, NO_TEXT, excerpt, instructions

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    options = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--"))
    variants = tuple(options["variants"].split(","))
    runs = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    folder, keys = Path(args[1]), Path(args[2])
    folder.mkdir(parents=True, exist_ok=True)
    keys.mkdir(parents=True, exist_ok=True)
    found = {(r["topic"], r["variant"]): r for r in runs}
    rng = random.Random(int(options.get("seed", 91)))
    key: dict[str, dict[str, str]] = {}
    number = 0
    for topics in KINDS.values():
        for topic in topics:
            number += 1
            order = list(variants)
            rng.shuffle(order)
            key[topic] = dict(zip(LETTERS[: len(variants)], order, strict=True))
            parts = [f"## Thema: {topic}\n"]
            for letter, variant in key[topic].items():
                run = found.get((topic, variant), {})  # a run that failed wrote nothing: graded as such
                parts.append(f"### Text {letter}\n\n{excerpt(run['text']) if 'text' in run else NO_TEXT}\n")
            (folder / f"bogen_{number}.md").write_text("\n".join(parts), encoding="utf-8")
    words = instructions(len(variants))
    assert "zu\ndrei Themen je" in words, "the instructions of M48 changed"
    words = words.replace("zu\ndrei Themen je", "zu\neinem Thema")
    (folder / "anleitung.md").write_text(words, encoding="utf-8")
    (keys / "schluessel.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{number} Bögen, je {len(variants)} Texte")


if __name__ == "__main__":
    main()
