"""M90: the paragraphs Wikibooks and Wikiversity bring at the block budget times 1 and 10, and the paragraphs of
Wikipedia and Klexikon they push out, judged blind as in M86 (mc_budget_absaetze.py): does a paragraph treat the
topic asked for, and does it stand in the right block?

The rows of mc_zusatzquellen_budget.py keep, where a further archive printed something, its paragraphs and the
paragraphs it pushed out. The requests of one topic share their twin ("Optik", "Optik in Klasse 7", ...), so a
paragraph is judged once per topic, block and text and counted for every factor that printed or lost it. Gained and
lost paragraphs stand mixed under their block: a rater cannot tell them apart. The key goes into a folder of its own.

Usage:
  python mc_zusatzquellen_boegen.py boegen <folder> <key folder> <runs.json> [--seed=90]
  python mc_zusatzquellen_boegen.py auswertung <out.json> <folder> <key folder>
      every urteil_zusatz_<rater>.json in the folder against the key
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

from mc_budget_absaetze import INSTRUCTIONS, TOPIC_CLASSES, blocks, kappa, unit

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# The topic a request asks for: the requests of eval/artikelwahl that drew a twin, by the topic they mean
TOPIC_OF = {
    "Optik": "Optik",
    "Optik in Klasse 7": "Optik",
    "Physik: Optik (Sek I)": "Optik",
    "Lineare Funktion": "Lineare Funktion",
    "Lineare Funktionen": "Lineare Funktion",
    "OER-Förderungen": "OER-Förderungen",
}
KINDS = ("gewonnen", "verdraengt")


def collected(rows: list[dict]) -> dict[str, dict]:
    """unit -> topic, block, text, kind, project, the factors and requests that printed or lost it."""
    found: dict[str, dict] = {}
    for row in rows:
        topic = TOPIC_OF.get(row["topic"])
        if topic is None:
            continue
        lists = (("gewonnen", row.get("mit", {}).get("extra", [])), ("verdraengt", row.get("verdraengt_absaetze", [])))
        for kind, paragraphs in lists:
            for paragraph in paragraphs:
                text = " ".join(paragraph["text"].split())
                entry = found.setdefault(
                    unit(topic, paragraph["baustein"], text),
                    {
                        "topic": topic,
                        "block": paragraph["baustein"],
                        "text": text,
                        "art": kind,
                        "projekt": paragraph["projekt"],
                        "artikel": paragraph["artikel"],
                        "faktoren": [],
                        "anfragen": [],
                    },
                )
                if row["factor"] not in entry["faktoren"]:
                    entry["faktoren"].append(row["factor"])
                if row["topic"] not in entry["anfragen"]:
                    entry["anfragen"].append(row["topic"])
    return found


def boegen(folder: Path, keys: Path, rows: list[dict], seed: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    keys.mkdir(parents=True, exist_ok=True)
    found = collected(rows)
    described = blocks()
    rng = random.Random(seed)
    key: dict[str, dict] = {}
    parts, number = [], 0
    for topic in dict.fromkeys(TOPIC_OF.values()):
        own = [entry for entry in found.values() if entry["topic"] == topic]
        if not own:
            continue
        parts.append(f"## Thema: {topic}\n")
        for block in sorted({entry["block"] for entry in own}, key=lambda title: int(title.split(" ")[0])):
            slot = described.get(block, {})
            parts.append(
                f"### Baustein: {block}\n\nAufgabe: {slot.get('description', '–')} Gehört hinein: "
                f"{slot.get('inclusions', '–')}\n"
            )
            entries = [entry for entry in own if entry["block"] == block]
            rng.shuffle(entries)
            for entry in entries:
                number += 1
                ident = f"z{number:04d}"
                key[ident] = {name: value for name, value in entry.items() if name != "text"}
                parts.append(f"**{ident}** {entry['text']}\n")
    (folder / "bogen_zusatz.md").write_text("\n".join(parts), encoding="utf-8")
    (folder / "anleitung_zusatz.md").write_text(INSTRUCTIONS, encoding="utf-8")
    (keys / "schluessel_zusatz.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{number} Absätze: " + ", ".join(f"{k} {sum(1 for e in key.values() if e['art'] == k)}" for k in KINDS))


def counts(ids: list[str], raters: list[dict]) -> dict[str, float]:
    """The mean of the raters over ``ids``: the three topic classes and the paragraphs in a wrong block."""
    found = Counter()
    for rater in raters:
        for ident in ids:
            judged = rater[ident]
            found[judged["thema"]] += 1
            found["falscher_baustein"] += judged["thema"] != "daneben" and judged["baustein"] != "ja"
    return {name: found[name] / len(raters) for name in (*TOPIC_CLASSES, "falscher_baustein")} | {"absaetze": len(ids)}


def auswertung(out: Path, folder: Path, keys: Path) -> None:
    key = json.loads((keys / "schluessel_zusatz.json").read_text(encoding="utf-8"))
    paths = sorted(folder.glob("urteil_zusatz_*.json"))
    raters = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    result: dict = {"raters": [path.stem for path in paths], "alle": {}, "themen": {}}
    for kind in KINDS:
        for factor in (1, 10):
            ids = [i for i, entry in key.items() if entry["art"] == kind and factor in entry["faktoren"]]
            result["alle"][f"{kind}@{factor}"] = counts(ids, raters)
            for topic in dict.fromkeys(entry["topic"] for entry in key.values()):
                own = [i for i in ids if key[i]["topic"] == topic]
                if own:
                    result["themen"].setdefault(topic, {})[f"{kind}@{factor}"] = counts(own, raters)
    if len(raters) > 1:
        ids = sorted(key)
        first, second = ([rater[i]["thema"] for i in ids] for rater in raters[:2])
        result["agreement"] = {
            "thema_gleich": sum(a == b for a, b in zip(first, second, strict=True)),
            "thema_kappa": round(kappa(first, second), 3),
            "absaetze": len(ids),
        }
    result["projekte"] = dict(Counter(entry["projekt"] for entry in key.values()))
    result["artikel"] = dict(Counter(f"{entry['projekt']}: {entry['artikel']}" for entry in key.values()))
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, row in result["alle"].items():
        print(name, row)
    print(result.get("agreement"))


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    options = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--"))
    if args[0] == "boegen":
        rows = json.loads(Path(args[3]).read_text(encoding="utf-8"))
        boegen(Path(args[1]), Path(args[2]), rows, int(options.get("seed", 90)))
    elif args[0] == "auswertung":
        auswertung(Path(args[1]), Path(args[2]), Path(args[3]))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
