"""M50: how much of a compendium's text stands word for word in the articles it draws on - the five profiles of the
new service (the runs of M48) against the old service (old_run.py, best case, on the same nine topics).

A word counts as taken over when it lies in a run of at least eight words that stands so in one of the source
articles (lower case, words only; markers, labels and markdown removed). A sentence counts as taken over when nine in
ten of its words are, and as freely written when none is. The source articles of a topic: for the new service every
article a run of M48 named as a source for that topic, of any profile, read from the archives the service uses
(Wikipedia 2026-01 and Klexikon); for the old service the lead extracts it received live and the archive's articles
of the same titles. A sentence of the new service is model knowledge when it carries the label and cited when it
carries a number; one of the old service is cited when it carries "(n)" for one of its references.

Usage (project venv): python mc_wortlaut.py <m48_laeufe.json> <old_run_dir> <out.json>
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import urllib.parse
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from app.sources.zim.registry import ZimRegistry

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
RUN = 8  # words in a row that make a passage taken over
WHOLE = 0.9  # share of its words that makes a sentence taken over
OLD = "alter Dienst"
VARIANTS = ["llm-free", "balanced", "best-quality", "best-quality-generated", "best-coverage-generated", OLD]
WORD = re.compile(r"\w+")
NUMBER = re.compile(r"\[\d+(?:,\s?\d+)*\]")
LABEL = "[Modellwissen]"
PAREN = re.compile(r"\((\d{1,2}(?:\s*[,;]\s*\d{1,2})*)\)")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?!\[Modellwissen\])|(?<=\[Modellwissen\])\s+")
BIBLIOGRAPHY = re.compile(r"#+\s*(Literaturverzeichnis|Quellen|Referenzen|Literatur)\b", re.IGNORECASE)

registry = ZimRegistry([DATA / "wikipedia_de_all_nopic_2026-01.zim", DATA / "klexikon_de_all_maxi_2026-08.zim"])


def words(text: str) -> list[str]:
    return WORD.findall(text.replace("\\", "").lower())


class Sources:
    """The source texts of one topic, as runs of RUN words and as one string for sentences shorter than a run."""

    def __init__(self, texts: Iterable[str]) -> None:
        self.runs: set[str] = set()
        joined: list[str] = []
        for text in texts:
            found = words(text)
            joined.append(" " + " ".join(found) + " ")
            self.runs.update(" ".join(found[i : i + RUN]) for i in range(len(found) - RUN + 1))
        self.whole = "\n".join(joined)

    def taken(self, sentence: list[str]) -> int:
        """How many words of ``sentence`` lie in a run that stands so in a source."""
        if len(sentence) < RUN:
            return len(sentence) if f" {' '.join(sentence)} " in self.whole else 0
        covered = [False] * len(sentence)
        for i in range(len(sentence) - RUN + 1):
            if " ".join(sentence[i : i + RUN]) in self.runs:
                covered[i : i + RUN] = [True] * RUN
        return sum(covered)


def article_texts(titles: Iterable[str]) -> tuple[list[str], list[str]]:
    """The texts of ``titles`` in every archive that has them, and the titles no archive has."""
    texts, missing = [], []
    for title in dict.fromkeys(titles):
        found = False
        for archive in registry.archives:
            article = archive.read_article(title)
            if article is None:
                continue
            parsed = archive.parse(article)
            if not parsed.is_disambiguation:
                texts.append(parsed.text)
                found = True
        if not found:
            missing.append(title)
    return texts, missing


def new_sentences(text: str) -> list[tuple[str, str]]:
    """(class, sentence) of a text of the new service: 'model' with the label, 'cited' with a number, else 'plain'."""
    found = []
    for paragraph in re.split(r"\n\s*\n", text):
        if paragraph.lstrip().startswith("#"):
            continue
        for sentence in SENTENCE_END.split(" ".join(paragraph.split())):
            if sentence.strip():
                kind = "model" if LABEL in sentence else "cited" if NUMBER.search(sentence) else "plain"
                found.append((kind, NUMBER.sub("", sentence.replace(LABEL, ""))))
    return found


def old_sentences(markdown: str, references: int) -> list[tuple[str, str]]:
    """(class, sentence) of a text of the old service, without headings, rules and its reference list."""
    body: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if BIBLIOGRAPHY.match(stripped):
            break
        if not stripped.startswith(("#", "|")) and stripped != "---":
            body.append(line)
    found = []
    for paragraph in re.split(r"\n\s*\n", "\n".join(body)):
        for sentence in SENTENCE_END.split(" ".join(paragraph.split())):
            if not sentence.strip():
                continue
            numbers = [int(n) for m in PAREN.finditer(sentence) for n in re.split(r"\s*[,;]\s*", m.group(1))]
            cited = any(1 <= n <= references for n in numbers)
            found.append(("cited" if cited else "plain", PAREN.sub("", sentence)))
    return found


def tally(sentences: list[tuple[str, str]], sources: Sources) -> dict[str, dict[str, float]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for kind, sentence in sentences:
        found = words(sentence)
        if not found:
            continue
        taken = sources.taken(found)
        for key in (kind, "all"):
            row = counts[key]
            row["sentences"] += 1
            row["chars"] += len(sentence)
            row["words"] += len(found)
            row["taken_words"] += taken
            if taken >= WHOLE * len(found):
                row["whole_chars"] += len(sentence)
            if taken == 0:
                row["free_chars"] += len(sentence)
    return {
        key: {
            "sentences": row["sentences"],
            "chars": row["chars"],
            "taken": round(row["taken_words"] / row["words"], 3),
            "whole": round(row["whole_chars"] / row["chars"], 3),
            "free": round(row["free_chars"] / row["chars"], 3),
        }
        for key, row in counts.items()
    }


def main() -> None:
    runs = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    m48 = json.loads((Path(__file__).parent / "ergebnisse" / "m48_profilvergleich.json").read_text(encoding="utf-8"))
    kinds = {r["topic"]: r["kind"] for r in m48["run_rows"]}
    titles: dict[str, list[str]] = defaultdict(list)
    for run in runs:
        titles[run["topic"]].extend(run.get("sources") or [])
    rows = []
    for topic, named in titles.items():
        texts, missing = article_texts(named)
        sources = Sources(texts)
        for run in (r for r in runs if r["topic"] == topic):
            rows.append(
                {
                    "topic": topic,
                    "kind": kinds.get(topic, "?"),
                    "variant": run["variant"],
                    "articles": len(texts),
                    "missing": missing,
                    **tally(new_sentences(run["text"]), sources),
                }
            )
    for path in sorted(Path(sys.argv[2]).glob("*.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        result = run.get("result") or {}
        references: dict[str, str] = {}
        for entity in result.get("linker_output", {}).get("entities", []):
            wiki = entity["sources"]["wikipedia"]
            url = wiki.get("url_de") or wiki.get("url_en")
            if url and url not in references:
                references[url] = wiki.get("extract") or ""
        named = [urllib.parse.unquote(u.rsplit("/wiki/", 1)[-1]).replace("_", " ") for u in references if "/de." in u]
        texts, missing = article_texts(named)
        sources = Sources([*references.values(), *texts])
        markdown = result.get("compendium_output", {}).get("markdown", "")
        rows.append(
            {
                "topic": run["topic"],
                "kind": kinds.get(run["topic"], "?"),
                "variant": OLD,
                "articles": len(texts),
                "extracts": len(references),
                "missing": missing,
                **tally(old_sentences(markdown, len(references)), sources),
            }
        )
    summary: dict[str, dict[str, object]] = {}
    for variant in VARIANTS:
        mine = [r for r in rows if r["variant"] == variant]
        if not mine:
            continue
        entry: dict[str, object] = {"runs": len(mine)}
        for key in ("all", "cited", "model", "plain"):
            pairs = [(r[key], r["all"]["chars"]) for r in mine if key in r]
            if not pairs:
                continue
            have = [counts for counts, _ in pairs]
            entry[key] = {
                measure: round(statistics.median(h[measure] for h in have), 3) for measure in ("taken", "whole", "free")
            }
            entry[key]["span_taken"] = [min(h["taken"] for h in have), max(h["taken"] for h in have)]
            entry[key]["share_of_text"] = round(statistics.median(h["chars"] / total for h, total in pairs), 3)
        summary[variant] = entry
    out = {"run_words": RUN, "whole_share": WHOLE, "summary": summary, "rows": rows}
    Path(sys.argv[3]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for variant, entry in summary.items():
        line = [f"{variant:26s}"]
        for key in ("all", "cited", "model", "plain"):
            if key in entry:
                e = entry[key]
                line.append(
                    f"{key}: {e['share_of_text']:.0%} des Textes, wörtlich {e['taken']:.0%} der Wörter, "
                    f"ganze Sätze {e['whole']:.0%}, frei {e['free']:.0%}"
                )
        print(" | ".join(line))


if __name__ == "__main__":
    main()
