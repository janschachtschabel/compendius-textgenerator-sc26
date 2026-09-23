"""Evaluate the measured runs of the old service: sources, article choice, citations and their support.

Citation support uses the new service's own check (app.synthesis.citations, PLAN.md D26): a cited sentence with
at least 3 content stems counts as supported when at least 20 % of its stems occur in the text it cites. The old
service cites "(n)" for the n-th Wikipedia URL of its reference list; the text behind a number is the lead extract
the model received for that URL. Article checks read the same Wikipedia dump the new service uses (2026-01).

Usage (project venv): python old_analyze.py <out.json> <run_dir> [<run_dir> ...]
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import urllib.parse
from pathlib import Path

from app.sources.zim.registry import ZimRegistry
from app.synthesis.citations import MIN_CONTENT_STEMS, MIN_SUPPORT, _cited_sentences, _stems, _units

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DATA = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data")
registry = ZimRegistry([DATA / "wikipedia_de_all_nopic_2026-01.zim", DATA / "klexikon_de_all_maxi_2026-08.zim"])
wikipedia = next(a for a in registry.archives if a.project == "wikipedia")
ASPECTS = [
    "Einführung", "Grundlegende Fachinhalte", "Systematik", "Gesellschaftlicher Kontext", "Historische Entwicklung",
    "Akteure", "Beruf", "Quellen, Literatur", "Bildungspolitische", "Rechtliche", "Nachhaltigkeit",
    "Interdisziplinarität", "Aktuelle Entwicklungen", "Verknüpfung mit anderen Ressourcentypen", "Praxisbeispiele",
]
PAREN = re.compile(r"\((\d{1,2}(?:\s*[,;]\s*\d{1,2})*)\)")
MARKER = re.compile(r"\[(\d{1,3})\]")


def title_of(url: str) -> str:
    return urllib.parse.unquote(url.rsplit("/wiki/", 1)[-1]).replace("_", " ")


def as_markers(markdown: str, n_refs: int) -> str:
    def repl(match: re.Match[str]) -> str:
        numbers = [int(x) for x in re.split(r"\s*[,;]\s*", match.group(1))]
        return "".join(f"[{n}]" for n in numbers) if all(1 <= n <= n_refs for n in numbers) else match.group(0)

    return PAREN.sub(repl, markdown)


def citation_stats(markdown: str, extracts: dict[int, str]) -> dict[str, object]:
    stems_by_number = {n: _stems(text) for n, text in extracts.items()}
    total = cited = supported = unsupported = short = 0
    coverages: list[float] = []
    weakest: list[tuple[float, str]] = []
    body = "\n".join(line for line in markdown.splitlines() if not line.lstrip().startswith(("#", "|")))
    for paragraph in re.split(r"\n\s*\n", as_markers(body, len(extracts))):
        for unit in _units(paragraph):
            for sentence in _cited_sentences(unit):
                if not MARKER.sub("", sentence).strip(" .;:,!?…()0123456789*"):
                    continue
                total += 1
                numbers = [int(n) for n in MARKER.findall(sentence)]
                if not numbers:
                    continue
                cited += 1
                own = _stems(MARKER.sub("", sentence))
                if len(own) < MIN_CONTENT_STEMS:
                    short += 1
                    continue
                pool: set[str] = set()
                for n in numbers:
                    pool |= stems_by_number.get(n, set())
                coverage = len(own & pool) / len(own)
                coverages.append(coverage)
                if coverage >= MIN_SUPPORT:
                    supported += 1
                else:
                    unsupported += 1
                    weakest.append((coverage, " ".join(sentence.split())[:220]))
    weakest.sort()
    return {
        "sentences": total, "cited": cited, "uncited": total - cited, "supported": supported,
        "unsupported": unsupported, "too_short": short,
        "coverage_median": round(statistics.median(coverages), 2) if coverages else None,
        "weakest": weakest[:3],
    }


rows = []
for run_dir in sys.argv[2:]:
    for path in sorted(Path(run_dir).glob("*.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        result = run.get("result") or {}
        entities = result.get("linker_output", {}).get("entities", [])
        markdown = result.get("compendium_output", {}).get("markdown", "")
        # the old reference list: unique URLs in entity order (core/compendium.py extract_references_from_linker_data)
        references: list[str] = []
        extract_of_url: dict[str, str] = {}
        for entity in entities:
            wiki = entity["sources"]["wikipedia"]
            url = wiki.get("url_de") or wiki.get("url_en")
            if url and url not in references:
                references.append(url)
                extract_of_url[url] = wiki.get("extract") or ""
        extracts = {i: extract_of_url[url] for i, url in enumerate(references, 1)}
        found_titles = [title_of(u) for u in references]
        resolution = registry.resolve_topic(run["topic"])
        mismatched, disambiguation = [], []
        for entity in entities:
            wiki = entity["sources"]["wikipedia"]
            url = wiki.get("url_de")
            if not url:
                continue
            title = title_of(url)
            if title.lower() != entity["entity"].lower():
                mismatched.append(f"{entity['entity']} -> {title}")
            article = wikipedia.read(title)
            if article is not None and wikipedia.parse(article).is_disambiguation:
                disambiguation.append(title)
        headings = [line.lstrip("#").strip() for line in markdown.splitlines() if line.startswith("## ")]
        aspects = sum(1 for a in ASPECTS if any(a.lower() in h.lower() for h in headings))
        http = run["http_calls"]
        row = {
            "topic": run["topic"],
            "dir": Path(run_dir).name,
            "seconds": run["seconds"],
            "error": run["error"],
            "llm_calls": len(run["llm_calls"]),
            "llm_tokens": sum(c.get("total_tokens") or 0 for c in run["llm_calls"]),
            "llm_seconds": round(sum(c.get("seconds") or 0 for c in run["llm_calls"]), 1),
            "wiki_requests": len(http),
            "wiki_not_ok": sum(1 for c in http if c.get("status") != 200),
            "wiki_seconds": round(sum(c.get("seconds") or 0 for c in http), 1),
            "entities": len(entities),
            "found": len(references),
            "main_article": resolution.title,
            "main_article_used": (resolution.title or "").lower() in {t.lower() for t in found_titles},
            "title_differs": mismatched,
            "disambiguation_pages": disambiguation,
            "extract_chars": sum(len(t) for t in extracts.values()),
            "markdown_chars": len(markdown),
            "headings": len(headings),
            "aspects_as_headings": aspects,
            **citation_stats(markdown, extracts),
        }
        rows.append(row)
        print(
            f"{row['topic']:24s} {row['dir']:12s} {row['seconds']:6.1f}s LLM {row['llm_calls']:2d}/{row['llm_tokens']:6d} "
            f"Wiki {row['wiki_requests']:3d} (!200 {row['wiki_not_ok']:3d}) Quellen {row['found']:2d}/{row['entities']:2d} "
            f"Hauptartikel {'ja ' if row['main_article_used'] else 'NEIN'} ({row['main_article']}) BKL {len(disambiguation)} "
            f"abweichend {len(mismatched)} | Quelltext {row['extract_chars']:5d} -> Text {row['markdown_chars']:5d} | "
            f"Sätze {row['sentences']:3d} zitiert {row['cited']:3d} gestützt {row['supported']:3d} "
            f"nicht gestützt {row['unsupported']:3d} (Median {row['coverage_median']})"
        )

Path(sys.argv[1]).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
