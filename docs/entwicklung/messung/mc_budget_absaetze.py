"""M86: does a larger block budget print more paragraphs that do not belong? Every paragraph the verbatim profiles
printed at any factor, judged once by blind raters: does it treat the topic asked for, and does it stand in the right
block?

The runs of mc_kompendium_profil.py --budgets --fixed-corpus print nested sets: what factor 1 prints, every larger
factor prints too; the evidence rows of mc_budget_belege.py (best-quality-generated) nest the same way. So each
paragraph is judged once and counted for every run that printed it; the paragraphs a factor adds to the one before
tell whether the budget lets in worse ones. A paragraph is its topic, its block and its text without citation
numbers; one printed by both profiles is judged once. The order within a block is shuffled, so its place does not
betray the factor that first printed it.

Usage:
  python mc_budget_absaetze.py boegen <folder> <runs.json> [<runs.json> ...] [--seed=86]
      sheets (one per group of topics), the key and the instructions; the template's block descriptions come from
      app/templates/builtin/sc26.json
  python mc_budget_absaetze.py auswertung <out.json> <folder> <runs.json> [<runs.json> ...]
      every urteil_<sheet>_<rater>.json in the folder against the key, per profile and factor
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

TEMPLATE = Path(__file__).resolve().parents[3] / "app" / "templates" / "builtin" / "sc26.json"
SHEETS = {"a": ("Optik", "Komponisten der Klassik"), "b": ("Französische Revolution", "Inklusion im Sportunterricht")}
TOPIC_CLASSES = ("passt", "rand", "daneben")
CITATION = re.compile(r"\s*\[\d+(?:,\s*\d+)*\]")
INSTRUCTIONS = """Du bist Fachgutachterin oder Fachgutachter für Unterrichtsmaterial. Die Datei, deren Pfad du
bekommst, enthält Absätze aus Kompendien für Lehrkräfte, geordnet nach Thema und Baustein. Jeder Absatz steht unter dem
Baustein, in den ein Verfahren ihn einsortiert hat; jeder Baustein ist mit seiner Aufgabe beschrieben. Woher ein Absatz
stammt und welches Verfahren ihn wählte, spielt für dich keine Rolle.

Bewerte jeden Absatz für sich:

1. **thema**: Gehört der Absatz zum angefragten Thema?
   - „passt“: Er behandelt das Thema selbst. Bei einem Begriff wie „Optik“ das Fachgebiet und seine Teile; bei einer
     Gruppe wie „Komponisten der Klassik“ einen oder mehrere ihrer Vertreter, ihr Werk oder was sie verbindet; bei
     einem Thema mit Aspekt wie „Inklusion im Sportunterricht“ genau diesen Aspekt.
   - „rand“: Er behandelt einen Oberbegriff oder ein Nachbarthema, das eine Lehrkraft zum Thema noch brauchen kann,
     nicht aber das Thema selbst (etwa Inklusion in der Schule allgemein bei „Inklusion im Sportunterricht“).
   - „daneben“: Er hat mit dem Thema nichts zu tun, meint etwas anderes oder führt in die Irre.
2. **baustein**: „ja“, wenn seine Aussage zur Aufgabe des Bausteins passt, unter dem er steht, sonst „nein“; bei
   „daneben“ immer „nein“.

Bewerte jeden Absatz, auch einen kurzen oder abgerissenen. Antworte ausschließlich mit einem JSON-Objekt mit einem
Eintrag je Absatz-Kennung, ohne weiteren Text:

{"a0001": {"thema": "passt", "baustein": "ja"}, "a0002": {"thema": "rand", "baustein": "nein"}, …}
"""


def printed(run: dict) -> list[tuple[str, str]]:
    """The paragraphs of a run's text: (block title, text without citation numbers), in print order; for the evidence
    of mc_budget_belege.py the paragraphs the writer gets."""
    if "belege" in run:
        return [(block, " ".join(text.split())) for block, texts in run["belege"].items() for text in texts]
    found = []
    for block in re.split(r"(?m)^### ", run["text"]):
        title, _, body = block.strip().partition("\n")
        for paragraph in re.split(r"\n\s*\n", body.strip()):
            text = " ".join(CITATION.sub("", paragraph).split())
            if text:
                found.append((title.strip(), text))
    return found


def unit(topic: str, block: str, text: str) -> str:
    """The key of a paragraph across runs and profiles."""
    return f"{topic} | {block} | {text[:200]}"


def load_runs(paths: list[str]) -> list[dict]:
    runs = (run for path in paths for run in json.loads(Path(path).read_text(encoding="utf-8")))
    return [run for run in runs if "text" in run or "belege" in run]


def blocks() -> dict[str, dict]:
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    return {slot["title"]: slot for slot in template["slots"]}


def boegen(folder: Path, runs: list[dict], seed: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    found: dict[tuple[str, str], dict[str, str]] = {}  # (topic, block) -> unit -> text
    for run in runs:
        for block, text in printed(run):
            found.setdefault((run["topic"], block), {}).setdefault(unit(run["topic"], block, text), text)
    described = blocks()
    rng = random.Random(seed)
    key: dict[str, dict[str, str]] = {}
    for sheet, topics in SHEETS.items():
        parts, number = [], 0
        for topic in topics:
            parts.append(f"## Thema: {topic}\n")
            for (own, block), units in sorted(found.items(), key=lambda item: int(item[0][1].split(" ")[0])):
                if own != topic:
                    continue
                slot = described.get(block, {})
                parts.append(
                    f"### Baustein: {block}\n\nAufgabe: {slot.get('description', '–')} Gehört hinein: "
                    f"{slot.get('inclusions', '–')}\n"
                )
                order = list(units.items())
                rng.shuffle(order)
                for name, text in order:
                    number += 1
                    ident = f"{sheet}{number:04d}"
                    key[ident] = {"unit": name, "topic": topic, "block": block}
                    parts.append(f"**{ident}** {text}\n")
        (folder / f"bogen_absaetze_{sheet}.md").write_text("\n".join(parts), encoding="utf-8")
        print(f"Bogen {sheet}: {number} Absätze")
    (folder / "schluessel_absaetze.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    (folder / "anleitung_absaetze.md").write_text(INSTRUCTIONS, encoding="utf-8")


def kappa(first: list[str], second: list[str]) -> float:
    """Cohen's kappa of two raters over the same items."""
    n = len(first)
    observed = sum(a == b for a, b in zip(first, second, strict=True)) / n
    one, two = Counter(first), Counter(second)
    expected = sum(one[c] * two[c] for c in set(one) | set(two)) / n / n
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def shares(ids: list[str], rater: dict[str, dict[str, str]]) -> dict[str, int]:
    """Counts of one rater over ``ids``: the three topic classes and the paragraphs in a wrong block."""
    counts = Counter(rater[i]["thema"] for i in ids)
    return {
        **{name: counts.get(name, 0) for name in TOPIC_CLASSES},
        "falscher_baustein": sum(1 for i in ids if rater[i]["thema"] != "daneben" and rater[i]["baustein"] != "ja"),
    }


def auswertung(out: Path, folder: Path, runs: list[dict]) -> None:
    key = json.loads((folder / "schluessel_absaetze.json").read_text(encoding="utf-8"))
    by_unit = {entry["unit"]: ident for ident, entry in key.items()}
    paths = sorted(folder.glob("urteil_absaetze_*_g*.json"))  # urteil_absaetze_<sheet>_<rater>.json
    graders = sorted({path.stem.rsplit("_", 1)[1] for path in paths})
    verdicts: dict[str, dict[str, dict[str, str]]] = {grader: {} for grader in graders}
    for path in paths:
        verdicts[path.stem.rsplit("_", 1)[1]].update(json.loads(path.read_text(encoding="utf-8")))
    for grader, given in verdicts.items():
        missing = set(key) - set(given)
        assert not missing, f"{grader}: {len(missing)} Absätze ohne Urteil"
    result: dict = {"absaetze": len(key), "raters": graders, "profiles": {}}
    if len(graders) >= 2:
        first, second = (verdicts[g] for g in graders[:2])
        ids = sorted(key)
        result["agreement"] = {
            "thema_gleich": sum(first[i]["thema"] == second[i]["thema"] for i in ids),
            "thema_kappa": round(kappa([first[i]["thema"] for i in ids], [second[i]["thema"] for i in ids]), 3),
            "baustein_gleich": sum(first[i]["baustein"] == second[i]["baustein"] for i in ids),
            "daneben_beide": sum(first[i]["thema"] == second[i]["thema"] == "daneben" for i in ids),
            "absaetze": len(ids),
        }
    for profile in sorted({run["variant"].split("@")[0] for run in runs}):
        entry: dict = {}
        for topic in [None, *sorted({run["topic"] for run in runs})]:
            previous: set[str] = set()
            rows = {}
            for factor in sorted({run["budget"] for run in runs}):
                ids: set[str] = set()
                for run in runs:
                    if run["variant"] != f"{profile}@{factor}" or (topic is not None and run["topic"] != topic):
                        continue
                    ids |= {by_unit[unit(run["topic"], block, text)] for block, text in printed(run)}
                added = sorted(ids - previous)
                rows[f"×{factor}"] = {
                    "gedruckt": len(ids),
                    "je_gutachter": {g: shares(sorted(ids), verdicts[g]) for g in graders},
                    "hinzu": len(added),
                    "hinzu_je_gutachter": {g: shares(added, verdicts[g]) for g in graders},
                }
                previous = ids
            entry[topic or "alle"] = rows
        result["profiles"][profile] = entry
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for profile, entry in result["profiles"].items():
        print(f"== {profile}")
        for factor, row in entry["alle"].items():
            mean = {
                name: sum(v[name] for v in row["je_gutachter"].values()) / len(graders)
                for name in (*TOPIC_CLASSES, "falscher_baustein")
            }
            add = {
                name: sum(v[name] for v in row["hinzu_je_gutachter"].values()) / len(graders)
                for name in (*TOPIC_CLASSES, "falscher_baustein")
            }
            print(
                f"  {factor:>4} gedruckt {row['gedruckt']:>4} "
                + " ".join(f"{k} {v:.1f}" for k, v in mean.items())
                + f" | hinzu {row['hinzu']:>3} "
                + " ".join(f"{k} {v:.1f}" for k, v in add.items())
            )
    print("Übereinstimmung:", result.get("agreement"))


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    options = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--"))
    if args[0] == "boegen":
        boegen(Path(args[1]), load_runs(args[2:]), int(options.get("seed", 86)))
    elif args[0] == "auswertung":
        auswertung(Path(args[1]), Path(args[2]), load_runs(args[3:]))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
