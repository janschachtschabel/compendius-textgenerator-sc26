"""The entity linker of the old service (v0.2.0), word for word, for the measurements that replay it.

Its linker asked an LLM for up to ten entities with exact Wikipedia article titles (mode generate, educational
mode on, alterCode/compendious/app/core/openai_wrapper.py) and looked every title up, directly and with simple
spelling variants. M17 (mc_alte_artikelwahl.py) replays it for the article choice, M23 (mc_material_kompendium.py)
for the compendium of a material.
"""

from __future__ import annotations

import json

MAX_ENTITIES = 10  # the ten terms per topic of M2

# The old prompt, word for word (openai_wrapper.get_educational_block_de and generate_entities).
EDUCATIONAL_DE = (
    "Ergänzen Sie die Entitäten so, dass sie das für Bildungszwecke relevante Weltwissen zum Thema abbilden. "
    "Nutzen Sie folgende Aspekte zur Strukturierung: Einführung, Zielsetzung, Grundlegendes (Thema, Zweck, "
    "Abgrenzung, Beitrag zum Weltwissen); Grundlegende Fachinhalte & Terminologie (inkl. Englisch: "
    "Schlüsselbegriffe, Formeln, Gesetzmäßigkeiten, mehrsprachiges Fachvokabular); Systematik & Untergliederung ("
    "Fachliche Struktur, Teilgebiete, Klassifikationssysteme); Gesellschaftlicher Kontext (Alltag, Haushalt, "
    "Natur, Hobbys, soziale Themen, öffentliche Debatten); Historische Entwicklung (Zentrale Meilensteine, "
    "Personen, Orte, kulturelle Besonderheiten); Akteure, Institutionen & Netzwerke (Wichtige Persönlichkeiten "
    "historisch & aktuell, Organisationen, Projekte); Beruf & Praxis (Relevante Berufe, Branchen, Kompetenzen, "
    "kommerzielle Nutzung); Quellen, Literatur & Datensammlungen (Standardwerke, Zeitschriften, Studien, "
    "OER-Repositorien, Datenbanken); Bildungspolitische & didaktische Aspekte (Lehrpläne, Bildungsstandards, "
    "Lernorte, Lernmaterialien, Kompetenzrahmen); Rechtliche & ethische Rahmenbedingungen (Gesetze, Richtlinien, "
    "Lizenzmodelle, Datenschutz, ethische Grundsätze); Nachhaltigkeit & gesellschaftliche Verantwortung ("
    "Ökologische und soziale Auswirkungen, globale Ziele, Technikfolgenabschätzung); Interdisziplinarität & "
    "Anschlusswissen (Fachübergreifende Verknüpfungen, mögliche Synergien, angrenzende Wissensgebiete); "
    "Aktuelle Entwicklungen & Forschung (Neueste Studien, Innovationen, offene Fragen, Zukunftstrends); "
    "Verknüpfung mit anderen Ressourcentypen (Personen, Orte, Organisationen, Berufe, technische Tools, "
    "Metadaten); Praxisbeispiele, Fallstudien & Best Practices (Konkrete Anwendungen, Transfermodelle, "
    "Checklisten, exemplarische Projekte)."
)
SYSTEM = (
    f"You are an AI system for suggesting named entities relevant to the given text. "
    f"Your task is to identify up to {MAX_ENTITIES} important related entities "
    f"and provide their exact Wikipedia article titles.\n\n"
    f"CRITICAL: Use the EXACT Wikipedia article title format. Examples:\n"
    f"- For Goethe: 'Johann Wolfgang von Goethe' (not just 'Goethe')\n"
    f"- For Einstein: 'Albert Einstein' (not 'Einstein')\n"
    f"- For Berlin: 'Berlin' (the city)\n"
    f"- For Germany: 'Germany' (the country)\n\n"
    f"Focus on the most relevant entity types (PERSON, LOCATION, ORGANIZATION, CONCEPT, etc.).\n\n"
    f"For each entity, provide:\n"
    f"- label_de: The canonical German Wikipedia article title (exact format)\n"
    f"- label_en: The canonical English Wikipedia article title (exact format)\n"
    f"- type: The entity type (e.g. PERSON, LOCATION, ORGANIZATION)\n"
    f"- wikipedia_url_de: null (will be generated automatically)\n"
    f"- wikipedia_url_en: null (will be generated automatically)\n"
    f"- wikidata_id: null (will be fetched automatically)\n\n"
    f"Return a JSON array of objects with these keys. Focus on using the EXACT canonical Wikipedia article titles."
    f"\n\nBILDUNGSMODUS AKTIVIERT:\n{EDUCATIONAL_DE}"
)


def user_prompt(text: str) -> str:
    return (
        f"TEXT (language=de):\n{text}\n\n"
        f"Think about related important concepts and list up to {MAX_ENTITIES} "
        "additional entities that would help a student understand the text. "
        "Use EXACT Wikipedia article titles for both German and English labels. Return JSON only."
    )


def labels_of(content: str) -> list[str]:
    """The German labels in the order the model gave them, cleaned as the old service cleaned its answer."""
    cleaned = content.strip()
    for fence in ("```json", "```"):
        if cleaned.startswith(fence):
            cleaned = cleaned[len(fence) :]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    items = json.loads(cleaned.strip())
    if isinstance(items, dict):
        items = items.get("entities", [])
    return [label for item in items if (label := (item.get("label_de") or item.get("label", "")).strip())]


def variations(name: str) -> list[str]:
    """The old service's spelling variants (fallbacks/strategies.py, _generate_name_variations)."""
    found = [name.title(), name.lower(), name.upper()]
    found += [name[4:] for article in ("Der ", "Die ", "Das ") if name.startswith(article)]
    found += [name.replace("ß", "ss"), name.replace("ä", "ae"), name.replace("ö", "oe"), name.replace("ü", "ue")]
    return [v for v in dict.fromkeys(found) if v != name]
