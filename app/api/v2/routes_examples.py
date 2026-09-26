"""The examples /docs offers for the endpoints of routes.py: compendium requests and templates.

Swagger shows them in a chooser, from the shortest request to one that sets every field; tests/test_docs_*.py
check that the endpoints take them.
"""

from __future__ import annotations

from typing import Any

EXAMPLES: dict[str, dict[str, Any]] = {
    "kuerzeste Anfrage": {
        "summary": "Das Nötigste: ein Thema, zwei Teile, eine Ziellänge",
        "value": {"topic": "Optik", "parts": ["world", "curricula"], "target_length": 8000},
    },
    "Profil llm-free": {
        "summary": "Profil llm-free: ohne Sprachmodell, für einen Dienst ohne LLM",
        "description": (
            "preset wählt eines der vier Profile der Entscheidungsvorlage; ohne preset gilt PRESET_DEFAULT, "
            "ausgeliefert balanced. llm-free: die "
            "Regeln wählen die Artikel, hybrid_light ordnet die Absätze zu, der Text bleibt wörtlich. 87 von 94 "
            "Hauptartikeln richtig, macro-F1 0,45, Teil 1 und 2 in rund 1,6 s, keine Tokens (M27). Teil 2 findet und "
            "bewertet mit den Stichwortregeln; ein Element, dessen Überschrift allein das Thema nennt, zählt beim "
            "Bereich mit (M32)."
        ),
        "value": {"topic": "Optik", "parts": ["world"], "preset": "llm-free"},
    },
    "Profil balanced": {
        "summary": "Profil balanced (Standard): das LLM wählt die Artikel, alles andere bleibt lokal",
        "description": (
            "Wie llm-free, aber das LLM entscheidet, wo die Regeln beim Artikel unsicher sind - hier das "
            "mehrdeutige Wort Linse -, und verwirft unpassende Nebenartikel. 91 von 94 Hauptartikeln richtig, "
            "rund 3,4 s und 900 Tokens je Kompendium (M27). Teil 2 wie llm-free. Ohne konfiguriertes LLM ist die "
            "Anfrage ein 503."
        ),
        "value": {"topic": "Physik: Linse", "parts": ["world"], "preset": "balanced"},
    },
    "Profil best-quality": {
        "summary": "Profil best-quality: das LLM wählt die Artikel und ordnet die Absätze zu",
        "description": (
            "Wie balanced, dazu matcher llm: macro-F1 0,70 statt 0,45, rund 14 s und 26.000 Tokens je "
            "Kompendium (M19, M27). Der Text bleibt wörtlich; lesbar formuliert ihn das Profil "
            "best-quality-generated. Mit curricula in parts bewertet das LLM auch jedes Lehrplanelement "
            "(curriculum_check llm, M32). Budget je Anfrage: 180.000 Tokens statt 60.000 "
            "(LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY, D59)."
        ),
        "value": {"topic": "Physik: Linse", "parts": ["world"], "preset": "best-quality"},
    },
    "Profil best-quality-generated": {
        "summary": "Profil best-quality-generated: alles mit dem LLM, der Text ergänzt und lesbar formuliert",
        "description": (
            "Wie best-quality, dazu schreibt das LLM jeden Baustein neu (generation llm) und darf eigenes Wissen "
            "ergänzen (enrichment model-knowledge); solche Sätze tragen keine Belegnummer und enden sichtbar mit "
            "[Modellwissen]. Für Texte, die Menschen direkt lesen; rund 24 s und 35.000 Tokens (M27). Zwei "
            "Gutachter zogen den Text in 11 von 12 Urteilen dem wörtlichen vor; unter dem ersten Prompt waren zwei "
            "Drittel des Modellwissens Füllsätze (M28), der zweite verlangt eine prüfbare Sachaussage oder nichts "
            "(D56) und ergänzte an sechs Themen 50 statt 82 solche Sätze, 13 statt 50 davon Füllsätze (M31). "
            "Teil 2 und Budget wie best-quality. Einzeln gesetzte Schalter gehen dem preset vor."
        ),
        "value": {"topic": "Optik", "parts": ["world"], "preset": "best-quality-generated"},
    },
    "Lehrplanbezüge mit best-quality": {
        "summary": "Nur Teil 2: die Regeln finden die Lehrplanelemente, das LLM bewertet jedes",
        "description": (
            "Ohne world entsteht kein Teil 1; das Thema wird trotzdem aufgelöst, in best-quality mit dem LLM. Die "
            "Stichwortregeln finden die Elemente, das LLM liest jedes mit Bereich und Lehrplan und bewertet es: passt, "
            "streift das Thema, passt nicht - was nicht passt, fällt heraus. 74 bis 79 % der gelisteten Elemente "
            "passen, keins, das zwei Gutachter passend nannten, ging verloren; rund 80 Tokens je Element, im Median "
            "7.800 bis 9.600 Tokens und 6 s mehr (M32), aus 180.000 Tokens je Anfrage (D59). Jeder Block nennt "
            "Lehrplan, Land, Bildungsstufe, Schulart und Klasse; audit.llm.curriculum_check sagt, was das LLM tat."
        ),
        "value": {"topic": "Optik", "subject": "Physik", "parts": ["curricula"], "preset": "best-quality"},
    },
    "mit den Schaltern": {
        "summary": "Was sonst noch geht: Template, Artikelwahl, Zuordnung, die drei Schreib-Schalter, Facetten",
        "description": (
            "article_choice wählt die Artikel (rule-based oder llm), matcher ordnet die Absätze den Bausteinen zu "
            "(hybrid_light, bm25, char_tfidf, lexicon_only oder llm; die Liste mit Güte, Zeit und Kosten steht unter "
            "GET /api/v2/matching/strategies). extraction wählt die Sätze, generation formuliert die Bausteine, "
            "enrichment entscheidet, ob das Modell eigenes Wissen beisteuern darf. Ohne konfiguriertes LLM ist ein "
            "LLM-Schalter ein 503; ist die b-api nur gerade nicht erreichbar, laufen die Regeln, und audit sagt "
            "hinterher, was wirklich lief."
        ),
        "value": {
            "topic": "Optik",
            "parts": ["world", "curricula"],
            "target_length": 12000,
            "template_id": "sc26",
            "article_choice": "llm",
            "matcher": "hybrid_light",
            "extraction": "llm",
            "generation": "llm-fast",
            "enrichment": "sources-only",
            "facets_visible": True,
            "max_articles": 12,
            "empty_slot_policy": "note",
        },
    },
    "Artikelwahl und Zuordnung durch das LLM": {
        "summary": "Das LLM wählt die Artikel und ordnet die Absätze zu; der Text bleibt wörtlich aus den Quellen",
        "description": (
            "article_choice llm entscheidet, wo die Regeln unsicher sind - hier das mehrdeutige Wort Linse -, und "
            "verwirft unpassende Nebenartikel. matcher llm lässt das LLM jeden Absatz einem Baustein zuordnen. "
            "Beides fällt ohne b-api auf die Regeln zurück; Güte, Sekunden und Tokens stehen in den Hilfetexten der "
            "beiden Felder."
        ),
        "value": {
            "topic": "Physik: Linse",
            "parts": ["world"],
            "article_choice": "llm",
            "matcher": "llm",
            "target_length": 12000,
        },
    },
    "mit einer Sammlung (Teil 3)": {
        "summary": "Alle drei Teile: Weltwissen, Lehrpläne und die Materialien einer edu-sharing-Sammlung",
        "description": (
            "collection_id ist die Knoten-ID der Sammlung im Repository, hier eine aus der Staging - für "
            "eine andere Umgebung ersetzen. Teil 3 braucht EDU_SHARING_BASE_URL; fehlt sie, bleibt Teil 3 aus und "
            "parts_status.collection sagt unavailable, und nur wenn kein angefragter Teil erzeugbar ist - oder das "
            "Thema allein aus der Sammlung käme -, antwortet der Endpunkt 503. Mit collection_id braucht Teil 3 "
            "keinen Artikel in den Archiven."
        ),
        "value": {
            "topic": "Optik",
            "parts": ["world", "curricula", "collection"],
            "collection_id": "9e7ae956-e9df-430f-bace-f3db4b910013",
            "target_length": 12000,
        },
    },
    "aus einem Knoten des Repositorys": {
        "summary": "Thema, Fach und Stufe aus den Metadaten eines Knotens, hier die Sammlung Optik der WLO-Staging",
        "description": (
            "node_id nennt ein Material oder eine Sammlung, gelesen ohne Zugangsdaten, also nur Öffentliches. Der "
            "Titel wird zum Thema, alle Fächer zählen gleich; Bildungsstufen und Schlagwörter gehen als "
            "Kontextwörter mit, die bei einer Begriffsklärung nur zählen, wenn die Fächer keine eigenen Wörter "
            "haben. Die Antwort "
            "nennt den Knoten unter node. repository ist die REST-Adresse des Repositorys, ohne Angabe das "
            "konfigurierte; erlaubt sind nur Hosts aus EDU_SHARING_REPOSITORIES, über https. "
            "GET /api/v2/nodes/{node_id} zeigt vorab, was gelesen wird."
        ),
        "value": {
            "node_id": "9e7ae956-e9df-430f-bace-f3db4b910013",
            "repository": "https://repository.staging.openeduhub.net/edu-sharing/rest",
            "parts": ["world", "curricula"],
        },
    },
    "Material mit eigenem Thema": {
        "summary": "Ein Material der WLO-Staging mit einem Thema dazu: beide Artikel kommen in den Korpus",
        "description": (
            "Titel von Materialien nennen oft ihr Format (hier: Stationsarbeit zur Optik) statt eines "
            "Lexikonthemas; ohne topic suchen die Regeln den Artikel in Titel und Beschreibung (D47). Ein topic dazu "
            "geht vor, und der Artikel des Materials kommt als weitere Quelle dazu, wenn er mit dem Hauptartikel "
            "verlinkt ist; audit.node_article sagt, wie er gefunden wurde. Fach, Stufe und Schlagwörter des "
            "Materials gehen weiter in die Auflösung ein."
        ),
        "value": {
            "node_id": "ac66224b-42b0-4676-a53d-71b058dc780b",
            "repository": "https://repository.staging.openeduhub.net/edu-sharing/rest",
            "topic": "Optik",
            "parts": ["world"],
        },
    },
    "alle Parameter": {
        "summary": "Jedes Feld einmal gesetzt: Thema mit Material, alle drei Teile, Wissenssammlung, alle Schalter",
        "description": (
            "Ein topic mit einem Material (node_id, repository), dessen Artikel als weitere Quelle dazukommt, wenn er "
            "mit dem Hauptartikel verlinkt ist; alle drei Teile, Teil 3 aus collection_id, dieselbe Sammlung als "
            "Wissensquelle für Teil 1 (knowledge_collection_id); subject entscheidet die Artikelwahl mit und grenzt "
            "Teil 2 ein. preset setzt die Schalter, jeder hier gesetzte geht ihm vor. existing_markdown ist ein "
            "früheres Kompendium, hier gekürzt auf einen redaktionell geprüften Baustein; mit regenerate_sections "
            "entstehen nur die genannten Bausteine neu, alle anderen bleiben wortgleich. Die Knoten stammen aus der "
            "WLO-Staging - für eine andere Umgebung ersetzen. Braucht LLM_ENABLED und B_API_KEY, sonst 503."
        ),
        "value": {
            "topic": "Optik",
            "node_id": "ac66224b-42b0-4676-a53d-71b058dc780b",
            "repository": "https://repository.staging.openeduhub.net/edu-sharing/rest",
            "collection_id": "9e7ae956-e9df-430f-bace-f3db4b910013",
            "knowledge_collection_id": "9e7ae956-e9df-430f-bace-f3db4b910013",
            "parts": ["world", "curricula", "collection"],
            "subject": "Physik",
            "language": "de",
            "template_id": "sc26",
            "preset": "best-quality",
            "article_choice": "llm",
            "matcher": "llm",
            "curriculum_check": "llm",
            "extraction": "rule-based",
            "generation": "llm-fast",
            "enrichment": "sources-only",
            "target_length": 12000,
            "empty_slot_policy": "note",
            "existing_markdown": (
                "### 3 · Fachinhalte\n"
                "<!-- kompendium:section id=sc26_3 status=redaktionell-geprüft -->\n"
                "Licht breitet sich im Vakuum geradlinig aus.\n"
            ),
            "regenerate_sections": ["sc26_1", "sc26_11"],
            "facets_visible": True,
            "frontmatter_in_markdown": False,
            "max_articles": 12,
        },
    },
}
TEMPLATE_ID_HELP = (
    "The id of a template: sc26 (13 blocks, the shipped TEMPLATE_DEFAULT) and standard (6 blocks, the structure of "
    "a textbook) ship with the image and are read-only; a custom one has the id it was saved under - letters, "
    "digits, underscore and hyphen, up to 80 characters. GET /api/v2/templates lists them; an unknown one is a 404"
)
BUILTIN_TEMPLATES: dict[str, dict[str, Any]] = {
    "sc26": {"summary": "SC26, 13 Bausteine - die Vorgabe", "value": "sc26"},
    "standard": {"summary": "Standard, 6 Bausteine wie ein Lehrbuch", "value": "standard"},
}
TEMPLATE_EXAMPLES: dict[str, dict[str, Any]] = {
    "kleinstes Template": {
        "summary": "Das Nötigste: Kennung, Name und ein Baustein",
        "description": (
            "Jedes andere Feld hat eine Vorgabe: ein Baustein ohne generator wird aus den Quellen gefüllt, mit "
            "min_chunks 1, max_chunks 4 und 1.500 Zeichen; leere Bausteine fallen weg (empty_slot_policy omit)."
        ),
        "value": {
            "id": "optik-kurz",
            "name": "Optik kurz",
            "slots": [{"id": "k1", "slot": "fachinhalte", "title": "Fachinhalte"}],
        },
    },
    "alle Felder": {
        "summary": "Jedes Feld einmal gesetzt: vier Bausteine, zwei aus den Quellen und zwei erzeugte",
        "description": (
            "default_slot nimmt Absätze ohne sichere Zuordnung auf und muss einen Baustein ohne generator nennen; "
            "assignment_rules gilt für matcher llm. heading_patterns sind reguläre Ausdrücke für Überschriften der "
            "Quellen, facets die Facetten des Bausteins über den Katalog config/facets.yaml hinaus, budget seine "
            "Menge, source_preference die bevorzugten Projekte. generator sources, glossary oder actors erzeugt "
            "Quellenliste, Glossar oder Akteursverzeichnis. version und builtin setzt der Dienst."
        ),
        "value": {
            "id": "optik-unterricht",
            "name": "Optik im Unterricht (4 Bausteine)",
            "description": "Fachinhalte, Praxis, Quellen und Glossar für eine Unterrichtseinheit",
            "empty_slot_policy": "note",
            "default_slot": "fachinhalte",
            "assignment_rules": (
                "- fachinhalte: Gesetze, Modelle, Begriffe; der Regelfall für Fließtext.\n"
                "- praxis: Versuche, Geräte und Anwendungen im Alltag.\n"
                "- keiner: Personenlisten, Bildunterschriften, Verweise."
            ),
            "slots": [
                {
                    "id": "u1",
                    "slot": "fachinhalte",
                    "title": "1 · Fachinhalte",
                    "description": "Gesetze, Modelle und Fachbegriffe des Themas",
                    "inclusions": "Gesetze, Formeln, Modelle, Fachbegriffe, Einheiten",
                    "exclusions": "Geschichte, Anwendungsgeräte (2)",
                    "sub_items": ["Modelle mit Geltungsbereich", "Formeln"],
                    "search_queries": ["Gesetz", "Modell", "Formel"],
                    "heading_patterns": ["^(Grundlagen|Physikalische Grundlagen)$"],
                    "facets": {"required": [], "allowed": ["Bildungsstufe"], "defaults": {"Bildungsstufe": "Sek I"}},
                    "budget": {"min_chunks": 1, "max_chunks": 6, "target_chars": 2400, "weight": 1.4},
                    "generator": "",
                    "source_preference": ["wikipedia", "wikibooks"],
                },
                {
                    "id": "u2",
                    "slot": "praxis",
                    "title": "2 · Praxis",
                    "description": "Versuche, Geräte und Anwendungen",
                    "search_queries": ["Versuch", "Anwendung"],
                },
                {"id": "u3", "slot": "quellen", "title": "3 · Quellen", "generator": "sources"},
                {"id": "u4", "slot": "glossar", "title": "4 · Glossar", "generator": "glossary"},
            ],
        },
    },
}
