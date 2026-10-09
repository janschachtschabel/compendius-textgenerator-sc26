"""M88: blind sheets for the articles N named (mc_n_bedeutung.py) - per topic as N heard it, every article of the
archive that one of the variants took for a named title, with the title as named and the start of its first
paragraph; in a seeded random order, without runs, variants or how a title was found. The sheets go into one folder,
the key into another; both stay outside the repository.

Usage: python mc_n_bedeutung_boegen.py <sheets folder> <key folder> <titel.json> [--batches=8] [--seed=88]
           [--zeichen=400]
  titel.json is the output of mc_n_bedeutung.py titel; --zeichen cuts the start of each article.
"""

import json
import random
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

INSTRUCTIONS = """\
Du bist Fachgutachterin oder Fachgutachter für Unterrichtsmaterial. Zu Unterrichtsthemen hat eine KI Artikel
der deutschsprachigen Wikipedia genannt, aus denen ein Kompendium für Lehrkräfte entstehen soll. Ein Dienst hat jeden
genannten Titel im Wikipedia-Archiv nachgeschlagen. Diese Datei zeigt je Thema die Artikel, die das Archiv für die
genannten Titel geliefert hat: wie die KI den Titel nannte, den Titel des Artikels im Archiv und den Anfang seines
ersten Absatzes.

Beurteile jeden Artikel für sich: Passt er zum Thema, so wie es gefragt ist?

- **passt**: Der Artikel behandelt das Thema als Ganzes oder einen Teil, einen Vertreter, einen Aspekt oder einen
  Grundbegriff davon, in der Bedeutung, die das Thema meint.
- **randthema**: Der Artikel behandelt etwas in der richtigen Bedeutung, das nur am Rand zum Thema gehört: ein
  Nachbarthema, einen weiten Oberbegriff, eine entfernte Anwendung.
- **andere_bedeutung**: Der Artikel behandelt etwas anderes, das nur denselben oder einen ähnlichen Namen trägt wie
  das, was zum Thema gehört: eine andere Bedeutung des Wortes, etwa einen Ort, ein Werk, eine Band, eine Person, einen
  Vornamen, eine Pflanzen- oder Tiergattung oder den Begriff eines anderen Fachs statt des gemeinten Fachbegriffs.
- **passt_nicht**: Der Artikel behandelt das, was die KI genannt hat, in der gemeinten Bedeutung, aber es gehört
  nicht zum Thema.

Hinweise:

- Das Thema steht so da, wie die KI es hörte; „(Fach: Physik)“ nennt das Fach der Anfrage. Hat ein Thema ohne Fach
  mehrere Bedeutungen, gilt die im Schulunterricht übliche.
- Entscheidend ist der Artikel, den das Archiv geliefert hat. Weicht sein Titel vom genannten ab (eine Weiterleitung,
  eine andere Schreibweise), ist das für sich kein Fehler; es zählt, ob der Artikel zum Thema passt.
- Urteile nach dem Anfang des ersten Absatzes und deinem Wissen; schlage nichts nach und frage niemanden.
- Bewerte jeden Artikel unabhängig von den anderen desselben Themas; die Reihenfolge ist zufällig.
- Die Datei ist lang: Lies sie in Abschnitten (etwa 250 Zeilen auf einmal) bis zum Ende, bevor du schreibst.

Schreib dein Urteil als JSON in die Datei, deren Pfad du mit dieser Datei bekommst, in dieser Form (jede Kennung des
Bogens genau einmal; eine kurze Notiz nur zu Artikeln, die nicht passen):

```json
{"urteile": {"T01-01": "passt", "T01-02": "andere_bedeutung"},
 "notizen": {"T01-02": "eine Stadt in Niedersachsen, nicht der Fachbegriff"}}
```
"""


def heard(n: dict) -> str:
    """The topic as N heard it (ask_topic_articles): the topic, the place after a dash, the subjects behind."""
    text = f"{n['thema']} – {n['kontext']}" if n.get("kontext") else n["thema"]
    return f"{text} (Fach: {', '.join(n['faecher'])})" if n.get("faecher") else text


def labels_by_title(row: dict, traces: dict) -> dict[str, list[str]]:
    """The titles N named for each article of a run: the overview, the parts as the archive resolved them today, and
    the qualifiers a variant took in their place."""
    n = row["n"][0]
    named = {}
    taken = {mark["genannt"]: mark["titel"] for mark in row.get("marken", {}).get("klammer", [])}
    if n.get("uebersicht") and n.get("uebersicht_titel"):
        named.setdefault(n["uebersicht_titel"], []).append(n["uebersicht"])
    for label in n["genannt"]:
        title = taken.get(label) or (traces.get(label) or {}).get("ergebnis")
        if title:
            named.setdefault(title, []).append(label)
    return named


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    options = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
    sheets, keys = Path(args[0]), Path(args[1])
    batches, seed = int(options.get("batches", "8")), int(options.get("seed", "88"))
    chars = int(options.get("zeichen", "400"))
    rows, traces, beginnings = [], {}, {}
    for name in args[2:]:
        data = json.loads(Path(name).read_text("utf-8"))
        rows += [row for row in data["zeilen"] if "fehler" not in row and row.get("n")]
        traces.update(data["spuren"])
        beginnings.update(data["anfaenge"])
    topics: dict[str, dict[str, set[str]]] = {}
    for row in rows:
        topic = heard(row["n"][0])
        known = topics.setdefault(topic, {})
        labels = labels_by_title(row, traces)
        for title in row["n"][0]["gefunden"]:
            known.setdefault(title, set()).update(labels.get(title, []) or [title])
    rng = random.Random(seed)
    order = sorted(topics)
    rng.shuffle(order)
    # topics whole per sheet, the sheets about the same size
    loads = [0] * batches
    groups: list[list[str]] = [[] for _ in range(batches)]
    for topic in sorted(order, key=lambda t: -len(topics[t])):
        smallest = loads.index(min(loads))
        groups[smallest].append(topic)
        loads[smallest] += len(topics[topic])
    sheets.mkdir(parents=True, exist_ok=True)
    keys.mkdir(parents=True, exist_ok=True)
    key: dict[str, dict] = {}
    for number, group in enumerate(groups, 1):
        rng.shuffle(group)
        lines = [INSTRUCTIONS.replace('"T01-', f'"B{number}T01-'), ""]  # the example in this sheet's form
        for t_index, topic in enumerate(group, 1):
            tag = f"B{number}T{t_index:02d}"
            lines += [f"## Thema {tag}: {topic}", ""]
            titles = sorted(topics[topic])
            rng.shuffle(titles)
            for a_index, title in enumerate(titles, 1):
                ident = f"{tag}-{a_index:02d}"
                start = (beginnings.get(title) or {}).get("text", "").replace("\n", " ")
                start = start if len(start) <= chars else start[:chars].rsplit(" ", 1)[0] + " …"
                named = " · ".join(sorted(topics[topic][title]))
                lines += [f"**{ident}** · genannt: {named} · Artikel im Archiv: **{title}**", "", f"> {start}", ""]
                key[ident] = {"thema": topic, "titel": title, "genannt": sorted(topics[topic][title]), "bogen": number}
        (sheets / f"bogen_{number}.md").write_text("\n".join(lines), "utf-8")
        print(f"Bogen {number}: {len(group)} Themen, {loads[number - 1]} Artikel")
    (keys / "schluessel.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), "utf-8")
    print(f"{len(topics)} Themen, {len(key)} Artikel; Schlüssel in {keys}")


if __name__ == "__main__":
    main()
