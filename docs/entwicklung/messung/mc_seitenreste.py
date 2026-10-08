"""Messskript M74 (08.10.2026): ob Reste fremder Seiten aus Materialtexten in Teil 1 gedruckt werden.

M68 fand in Materialtexten neben Einwilligungstext auch Hinweise eines eingebetteten Videoplayers („Videos, die du dir
ansiehst, werden möglicherweise zum TV-Wiedergabeverlauf hinzugefügt …“ in 17 von 37 Optik-Texten), Fehlermeldungen
beim Teilen und Browserwarnungen. Die Entscheidungsgrundlage des Audits (Zeile 8) riet: erst messen, ob solche Zeilen
gedruckt werden. Dieses Skript erzeugt Teil 1 mit einer Wissens-Sammlung samt Volltexten (``knowledge_fulltext``) in
den angegebenen Profilen und zählt je Lauf die Absätze aus Materialien im Korpus, die als Seitenrest gelten - eine
Zeile, die in mindestens drei Materialtexten der Anfrage gleich steht, oder ein bekannter Player-Hinweis -, und welche
davon in einem Baustein stehen.

Einmal-Container, LLM über OpenAI direkt (mc_openai_direkt.py):

  cat mc_openai_direkt.py mc_seitenreste.py | docker compose run --rm --no-deps -T \
      -e LLM_ENABLED=true -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY \
      api python - <thema>=<sammlung> [...] -- <profil> [...]

Ergebnis als JSON nach der Zeile JSON-START.
"""

# --- M74: remnants of foreign pages in the material texts of part 1 ---
import collections
import json
import re
import sys

install()
from app.domain.requests import GenerateRequest
from app.main import build_registry, build_service
from app.settings import get_settings
from app.templates.manager import TemplateManager

KNOWN = re.compile(
    r"Wiedergabeverlauf|Falls die Wiedergabe nicht|Informationen zum Teilen abzurufen|JavaScript|PeerTube|"
    r"Warenkorb|Melde dich an|Abonnieren|Cookies? ",
    re.IGNORECASE,
)
REPEATED = 3

args = sys.argv[1:]
cut = args.index("--") if "--" in args else len(args)
pairs = [a.split("=", 1) for a in args[:cut]]
presets = args[cut + 1 :] or ["llm-free", "best-quality"]
settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())
original_prepare = service.prepare
last = {}


def preparing(*args, **kwargs):
    """The corpus generate builds, kept: the answer names its sources without their paragraphs."""
    last["prepared"] = original_prepare(*args, **kwargs)
    return last["prepared"]


service.prepare = preparing

rows = []
for topic, collection in pairs:
    for preset in presets:
        request = GenerateRequest(
            topic=topic, parts=["world"], preset=preset, knowledge_collection_id=collection, knowledge_fulltext=True
        )
        try:
            result = service.generate(request)
        except Exception as exc:  # a measurement records the failure and goes on
            rows.append({"topic": topic, "preset": preset, "error": f"{type(exc).__name__}: {exc}"[:200]})
            continue
        materials = [s for s in last["prepared"].sources if s.origin == "material"]
        texts = [p.text for s in materials for sec in s.sections for p in sec.paragraphs]
        per_material = [{p.text for sec in s.sections for p in sec.paragraphs} for s in materials]
        counts = collections.Counter(text for lines in per_material for text in lines)
        remnants = {t for t in texts if counts[t] >= REPEATED or KNOWN.search(t)}
        printed = "\n".join(s.text for s in result.sections if s.text)
        shown = sorted(t for t in remnants if t[:60] in printed)
        rows.append(
            {
                "topic": topic,
                "preset": preset,
                "materials": len(materials),
                "material_paragraphs": len(texts),
                "remnants": len(remnants),
                "remnants_printed": len(shown),
                "printed": shown[:20],
                "examples": sorted(remnants)[:20],
            }
        )
        print(f"# {topic}/{preset}: {len(materials)} Materialien, {len(texts)} Absätze, {len(remnants)} Reste, "
              f"{len(shown)} gedruckt", file=sys.stderr, flush=True)

print("JSON-START")
print(json.dumps(rows, ensure_ascii=False))
