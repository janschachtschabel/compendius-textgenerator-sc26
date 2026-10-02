"""M53: the check of model knowledge (07, point 12a) on the nine topics of M48 and M52.

best-coverage-generated with model_knowledge_check=llm through the service; a wrapper around the writer's check keeps
each block's text before and after it, so the two variants of a topic come from the same run and differ only where
the check struck or corrected: bcg (as written) and bcg-pruefung (as checked), in the format of mc_kompendium_profil.py
for the blind sheets of mc_profilvergleich_boegen.py. Every change - the sentence before and after, or struck - goes
to a list for judges of their own, who say whether the sentence was wrong and the correction right. The outputs stay
outside the repository.

Usage (from the project folder):
  python mc_modellwissen_pruefung.py run <runs.json> <changes.json> [topic ...]
  python mc_modellwissen_pruefung.py sheet <changes.json> <folder>
  python mc_modellwissen_pruefung.py score <runs.json> <changes.json> <out.json> <rater.json> [<rater.json> ...]
"""

from __future__ import annotations

import difflib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from statistics import median
from typing import Any

os.environ["LLM_ENABLED"] = "true"
os.environ["B_API_BASE_URL"] = "https://b-api.staging.openeduhub.net"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import app.synthesis.writer as writer  # noqa: E402
from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.synthesis.citations import MODEL_KNOWLEDGE_LABEL, MODEL_KNOWLEDGE_OPEN  # noqa: E402
from app.synthesis.facets import END_MARKER  # noqa: E402
from app.synthesis.safe_markdown import unescape  # noqa: E402
from mc_kompendium_profil import CONTENT, MARK, ZIMS, model_chars  # noqa: E402
from mc_profilvergleich_boegen import KINDS  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

TOPICS = [topic for topics in KINDS.values() for topic in topics]
SPAN = re.compile(re.escape(MODEL_KNOWLEDGE_OPEN) + r"(.*?)" + re.escape(END_MARKER), re.DOTALL)
INSTRUCTIONS = """Du bist Fachgutachterin oder Fachgutachter für Unterrichtsmaterial. Die Datei, deren Pfad du bekommst, listet
nummerierte Änderungen an Sätzen aus Kompendien für Lehrkräfte. Ein Sprachmodell hatte die Sätze aus eigenem Wissen
geschrieben; eine Prüfung hat sie danach gestrichen oder berichtigt. Zu jeder Änderung stehen das Thema, der Satz vorher
und - bei einer Berichtigung - der Satz nachher.

Beurteile jede Änderung mit deinem Fachwissen:

1. **vorher_falsch**: Enthält der Satz vorher eine sachlich falsche oder erfundene Angabe? "ja", "nein" oder "unklar"
   (wenn du es nicht mit guter Sicherheit sagen kannst).
2. **nachher_richtig** (nur bei einer Berichtigung): Ist der Satz nachher sachlich richtig? "ja", "nein" oder "unklar".
3. **grund**: ein kurzer Satz, warum.

Antworte ausschließlich mit einem JSON-Objekt, ohne weiteren Text:

{"1": {"vorher_falsch": "ja", "nachher_richtig": "ja", "grund": "…"}, "2": {"vorher_falsch": "nein", "grund": "…"}, …}
"""


def plain(span: str) -> str:
    return " ".join(unescape(span.replace(MODEL_KNOWLEDGE_LABEL, "")).split())


def sentences(text: str) -> list[str]:
    return [plain(span) for span in SPAN.findall(text)]


def changes_of(before: str, after: str) -> list[dict[str, Any]]:
    """The sentences of model knowledge the check struck or replaced, in their order."""
    old, new = sentences(before), sentences(after)
    found = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "delete":
            found += [{"art": "gestrichen", "vorher": sentence, "nachher": None} for sentence in old[i1:i2]]
        elif tag == "replace" and i2 - i1 >= j2 - j1:
            found += _aligned(old[i1:i2], new[j1:j2])
        elif tag == "replace":  # more sentences after than before: the check never adds one, so as they stand
            found.append({"art": "geändert", "vorher": " ".join(old[i1:i2]), "nachher": " ".join(new[j1:j2])})
    return found


def _aligned(olds: list[str], news: list[str]) -> list[dict[str, Any]]:
    """Struck and corrected sentences side by side: each new one corrects the old one it is most like, in order (the
    check mends a date or a name), and the old ones between were struck."""
    found: list[dict[str, Any]] = []
    start = 0
    for index, sentence in enumerate(news):
        last = len(olds) - (len(news) - index)  # leave an old sentence for each new one still to come
        best = max(range(start, last + 1), key=lambda k: difflib.SequenceMatcher(None, olds[k], sentence).ratio())
        found += [{"art": "gestrichen", "vorher": struck, "nachher": None} for struck in olds[start:best]]
        found.append({"art": "berichtigt", "vorher": olds[best], "nachher": sentence})
        start = best + 1
    return found + [{"art": "gestrichen", "vorher": struck, "nachher": None} for struck in olds[start:]]


def run(runs_path: Path, changes_path: Path, topics: list[str]) -> None:
    captured: dict[str, tuple[str, str, Any, float]] = {}
    lock = threading.Lock()
    original = writer._checked

    def recording(job: Any, slot: Any, written: Any) -> Any:
        start = time.monotonic()
        checked, outcome = original(job, slot, written)
        with lock:
            captured[slot.id] = (written.text, checked.text, outcome, time.monotonic() - start)
        return checked, outcome

    writer._checked = recording
    service = cli_service(ZIMS)
    if service.llm is None:
        raise SystemExit("LLM_ENABLED did not reach the settings")
    rows = json.loads(runs_path.read_text(encoding="utf-8")) if runs_path.exists() else []
    changes = json.loads(changes_path.read_text(encoding="utf-8")) if changes_path.exists() else []
    done = {r["topic"] for r in rows}
    for topic in topics:
        if topic in done:
            continue
        captured.clear()
        start = time.monotonic()
        request = GenerateRequest(
            topic=topic, parts=["world"], preset="best-coverage-generated", model_knowledge_check="llm"
        )
        result = service.generate(request)
        took = time.monotonic() - start
        before_blocks, after_blocks = [], []
        for section in result.sections:
            kept = section.text if section.text and section.status in CONTENT else ""
            before = captured[section.slot_id][0] if section.slot_id in captured else kept
            for blocks, text in ((before_blocks, before), (after_blocks, kept)):
                if text:
                    blocks.append(f"### {section.title}\n\n{MARK.sub('', text)}")
            if section.slot_id in captured:
                written, checked, _, _ = captured[section.slot_id]
                changes += [
                    {"thema": topic, "baustein": section.title, **change} for change in changes_of(written, checked)
                ]
        llm = result.audit.llm or {}
        check = llm.get("model_knowledge_check") or {}
        outcomes = [entry[2] for entry in captured.values()]
        common = {
            "topic": topic,
            "s": round(took, 1),
            "tokens": result.audit.llm_tokens,
            "check": check,
            "check_tokens": sum(outcome.total_tokens for outcome in outcomes),
            "check_calls": sum(outcome.calls for outcome in outcomes),
            "check_seconds_max": round(max((entry[3] for entry in captured.values()), default=0.0), 1),
            "heading": result.topic,
            "main": result.resolution.title,
        }
        for variant, blocks in (("bcg", before_blocks), ("bcg-pruefung", after_blocks)):
            text = "\n\n".join(blocks)
            rows.append({
                **common, "variant": variant, "chars": len(text), "marked": text.count("[Modellwissen]"),
                "model_chars": model_chars(text), "text": text,
            })  # fmt: skip
        print(
            f"{topic} | {took:.0f} s | geprüft {check.get('checked')} gestrichen {check.get('struck')} "
            f"berichtigt {check.get('corrected')} | Prüfung {common['check_tokens']} Tokens, längste "
            f"{common['check_seconds_max']} s | Rückfälle {check.get('fallbacks')}",
            flush=True,
        )
        runs_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        changes_path.write_text(json.dumps(changes, ensure_ascii=False, indent=1), encoding="utf-8")


def sheet(changes_path: Path, folder: Path) -> None:
    changes = json.loads(changes_path.read_text(encoding="utf-8"))
    folder.mkdir(parents=True, exist_ok=True)
    lines = []
    for number, change in enumerate(changes, start=1):
        lines.append(f"## {number}. {change['art'].capitalize()} - Thema: {change['thema']}\n")
        lines.append(f"Vorher: {change['vorher']}\n")
        if change["nachher"] is not None:
            lines.append(f"Nachher: {change['nachher']}\n")
    (folder / "aenderungen.md").write_text("\n".join(lines), encoding="utf-8")
    (folder / "anleitung_aenderungen.md").write_text(INSTRUCTIONS, encoding="utf-8")
    print(f"{len(changes)} Änderungen")


def score(runs_path: Path, changes_path: Path, out_path: Path, rater_paths: list[Path]) -> None:
    runs = [r for r in json.loads(runs_path.read_text(encoding="utf-8")) if r["variant"] == "bcg-pruefung"]
    changes = json.loads(changes_path.read_text(encoding="utf-8"))
    raters = [json.loads(path.read_text(encoding="utf-8")) for path in rater_paths]
    verdicts: dict[str, dict[str, int]] = {}
    for art in ("gestrichen", "berichtigt", "geändert"):
        numbers = [str(n) for n, change in enumerate(changes, start=1) if change["art"] == art]
        counted: dict[str, int] = {"änderungen": len(numbers)}
        for rater in raters:
            for number in numbers:
                answer = rater.get(number, {})
                for field in ("vorher_falsch", "nachher_richtig"):
                    if field in answer:
                        name = f"{field}={answer[field]}"
                        counted[name] = counted.get(name, 0) + 1
        verdicts[art] = counted
    agree = sum(
        1
        for number in map(str, range(1, len(changes) + 1))
        if len({rater.get(number, {}).get("vorher_falsch") for rater in raters}) == 1
    )
    checks = [run["check"] for run in runs]
    result = {
        "runs": len(runs),
        "checked": sum(c.get("checked", 0) for c in checks),
        "struck": sum(c.get("struck", 0) for c in checks),
        "corrected": sum(c.get("corrected", 0) for c in checks),
        "fallbacks": [c.get("fallbacks") for c in checks if c.get("fallbacks")],
        "check_tokens_median": median(run["check_tokens"] for run in runs),
        "check_seconds_max_median": median(run["check_seconds_max"] for run in runs),
        "seconds_median": median(run["s"] for run in runs),
        "tokens_median": median((run["tokens"] or {}).get("total", 0) for run in runs),
        "verdicts": verdicts,
        "agreement_vorher_falsch": f"{agree} von {len(changes)}",
        "raters": len(raters),
    }
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


def main() -> None:
    mode, *args = sys.argv[1:]
    if mode == "run":
        run(Path(args[0]), Path(args[1]), args[2:] or TOPICS)
    elif mode == "sheet":
        sheet(Path(args[0]), Path(args[1]))
    elif mode == "score":
        score(Path(args[0]), Path(args[1]), Path(args[2]), [Path(a) for a in args[3:]])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
