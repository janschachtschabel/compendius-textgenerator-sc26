"""Messskript M67 (04.10.2026): was die Belegprüfung der schreibenden Profile durchlässt, Satz für Satz mit Beleg.

Audit 2026-10-03, F01: Die Prüfung (app/synthesis/citations.py, drop_unsupported) vergleicht Wortstämme und Zahlen
eines Satzes mit den Absätzen, die er zitiert; Verneinung, Vorzeichen und die Zuordnung von Zahlen sieht sie nicht.
Ob das in echten Texten vorkommt, zeigt nur ein Lauf im Ablauf des Dienstes: best-quality-generated (Vorgabe seit D82)
zu jedem Thema, und jeder Aufruf der Prüfung festgehalten - der Text des Modells, die zitierten Absätze, was blieb.
Einmal-Container mit den Archiven, LLM über OpenAI direkt (mc_openai_direkt.py), frische Antworten:

  cat mc_openai_direkt.py mc_belegpruefung.py | docker compose run --rm --no-deps -T \
      -e LLM_ENABLED=true -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY \
      api python - <thema> [<thema> ...]

Ergebnis als JSON nach der Zeile JSON-START: je Thema Hauptartikel, Sekunden, Tokens und die Aufrufe der Prüfung.
Die Texte bleiben außerhalb des Repositorys; Auswertung mit mc_belegpruefung_auswertung.py (M67).
"""

# --- M67: every call of the citation check, with the model's text and the paragraphs it cites ---
import json
import sys
import threading
import time

install()
import app.synthesis.llm as synthesis_llm
from app.domain.requests import GenerateRequest
from app.main import build_registry, build_service
from app.settings import get_settings
from app.templates.manager import TemplateManager

topics = sys.argv[1:]
settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())
lock = threading.Lock()
calls = []
original = synthesis_llm.drop_unsupported


def recording(text, evidence, *, mark=""):
    kept, unsupported = original(text, evidence, mark=mark)
    with lock:
        calls.append(
            {"text": text, "evidence": {str(n): t for n, t in evidence.items()}, "mark": mark, "kept": kept,
             "unsupported": unsupported}
        )
    return kept, unsupported


synthesis_llm.drop_unsupported = recording

rows = []
for topic in topics:
    calls.clear()
    started = time.perf_counter()
    try:
        result = service.generate(GenerateRequest(topic=topic, parts=["world"], preset="best-quality-generated"))
    except Exception as exc:  # a measurement records the failure and goes on
        rows.append({"topic": topic, "error": f"{type(exc).__name__}: {exc}"[:300]})
        print(f"# {topic}: {type(exc).__name__}", file=sys.stderr, flush=True)
        continue
    seconds = round(time.perf_counter() - started, 1)
    rows.append(
        {"topic": topic, "main": result.resolution.title, "s": seconds, "tokens": result.audit.llm_tokens,
         "calls": list(calls)}
    )
    print(f"# {topic}: {result.resolution.title}, {seconds} s, {len(calls)} Bausteine", file=sys.stderr, flush=True)

print("JSON-START")
print(json.dumps(rows, ensure_ascii=False))
