"""Messskript M76 (08.10.2026): was ein Deckel für die KI-Prüfung der Lehrplanelemente an Teil 2 ändern würde.

Jan, 08.10.2026, zu M75 (sechs von 57 Themen verbrauchten 54 % der Prüftokens): „teil-2-prüfung nochmal genauer
nachmessen“. Je Thema prüft Teil 2 in ``best-quality`` alle gefundenen Elemente (wie ausgeliefert, D58); das Skript
schneidet die Elemente in der Reihenfolge der Prüfung mit (nach Punkten der Regeln absteigend), ihre Noten und die
Darstellung. Danach rechnet es je Deckel N nach, was Teil 2 zeigte, wenn nur die ersten N Elemente geprüft und die
übrigen weggelassen würden: dieselbe Darstellung (``render_curricula``) mit den geprüften und behaltenen Elementen.
Gezählt werden die Elemente, die als eigene Zeile gedruckt werden, die verloren gingen, davon die mit Note 2 (passt),
und die Tokens der Prüfung anteilig zu den geprüften Elementen.

Einmal-Container mit den Archiven und dem Lehrplan-Cache, LLM über OpenAI direkt (mc_openai_direkt.py):

  cat mc_openai_direkt.py mc_teil2_deckel.py | docker compose run --rm --no-deps -T -v <app>:/src/app:ro \\
      -e PYTHONPATH=/src -e LLM_ENABLED=true -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid \\
      -e OPENAI_API_KEY -e LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY=400000 -e REQUEST_TIMEOUT_S=600 api \\
      python - <thema> [...]

Das Budget und die Zeitgrenze sind hoch gesetzt, damit die volle Prüfung nicht abbricht. Ergebnis als JSON nach der
Zeile JSON-START.
"""

# --- M76: what a cap on the curriculum check would change in part 2 ---
import json
import sys
from dataclasses import replace

install()  # noqa: F821 - defined by mc_openai_direkt.py, which comes first
import app.compendium.llm_policy as llm_policy
import app.sources.lehrplan.part as part_module
import app.sources.lehrplan.render as render_module
from app.domain.requests import GenerateRequest
from app.main import build_registry, build_service
from app.settings import get_settings
from app.templates.manager import TemplateManager

CAPS = (120, 240, 360, 480, 600)
CAPTURED: dict = {}
PRINTED: list[str] = []
shipped_check = llm_policy.check_curriculum
shipped_render = part_module.render_curricula
shipped_item_line = render_module._item_line


def check_recorded(job, matches):
    kept, report = shipped_check(job, matches)
    CAPTURED["matches"], CAPTURED["kept"] = list(matches), list(kept)
    return kept, report


def render_recorded(result, *, meta, options):
    CAPTURED["render"] = (result, meta, options)
    return shipped_render(result, meta=meta, options=options)


def item_line_recorded(match):
    PRINTED.append(match.hit.iri)
    return shipped_item_line(match)


llm_policy.check_curriculum = check_recorded
part_module.render_curricula = render_recorded
render_module._item_line = item_line_recorded


def printed(result, matches, meta, options) -> list[str]:
    """The elements the part prints as lines of their own, for ``matches`` in place of the result's."""
    PRINTED.clear()
    shipped_render(replace(result, matches=matches), meta=meta, options=options)
    return list(PRINTED)


def notes_of(matches, kept) -> list:
    """The note of each element in ``matches``: 0 when the check left it out, else the kept element's note."""
    notes, position = [], 0
    for match in matches:
        if position < len(kept) and kept[position].hit.iri == match.hit.iri:
            notes.append(kept[position].note)
            position += 1
        else:
            notes.append(0)
    return notes


settings = get_settings()
service = build_service(settings, build_registry(settings), TemplateManager())
rows = []
for topic in sys.argv[1:]:
    CAPTURED.clear()
    result = service.generate(GenerateRequest(topic=topic, parts=["curricula"], preset="best-quality"))
    if "matches" not in CAPTURED:
        rows.append({"topic": topic, "note": "keine Prüfung (keine Elemente)"})
        continue
    matches, kept = CAPTURED["matches"], CAPTURED["kept"]
    notes = notes_of(matches, kept)
    found_result, meta, options = CAPTURED["render"]
    full = printed(found_result, kept, meta, options)
    tokens = (result.audit.llm or {}).get("curriculum_check") or {}
    row = {
        "topic": topic, "rated": len(matches), "dropped": notes.count(0), "note2": notes.count(2),
        "note1": notes.count(1), "unrated": notes.count(None), "printed": len(full),
        "printed_note2": sum(1 for m in kept if m.hit.iri in set(full) and m.note == 2),
        "tokens": result.audit.llm_tokens, "check": tokens, "caps": {},
    }
    by_iri = {m.hit.iri: note for m, note in zip(matches, notes, strict=True)}
    position = {m.hit.iri: index for index, m in enumerate(matches)}
    for cap in CAPS:
        if cap >= len(matches):
            continue
        capped = [m for m in kept if position[m.hit.iri] < cap]  # checked within the cap and kept, with its note
        shown = printed(found_result, capped, meta, options)
        lost = [iri for iri in full if iri not in set(shown)]
        row["caps"][cap] = {
            "printed": len(shown), "lost": len(lost), "lost_note2": sum(1 for iri in lost if by_iri.get(iri) == 2),
            "gained": len([iri for iri in shown if iri not in set(full)]),
            "share_checked": round(cap / len(matches), 3),
        }
    rows.append(row)
    print(f"# {topic}: {len(matches)} geprüft, {row['dropped']} verworfen, gedruckt {len(full)} | "
          + " | ".join(f"{c}: gedruckt {v['printed']}, verloren {v['lost']} (Note 2: {v['lost_note2']})"
                       for c, v in row["caps"].items()), file=sys.stderr, flush=True)

print("JSON-START")
print(json.dumps(rows, ensure_ascii=False))
