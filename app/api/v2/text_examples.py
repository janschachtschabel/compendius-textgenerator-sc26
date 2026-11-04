"""The examples of the text input (D114) for /docs: a collection, a material and texts as sources, shared by the
compendium, knowledge and qa."""

from __future__ import annotations

from typing import Any

# "Grundlagen" under Kernphysik: a title that names no subject matter, made clear by its place in the topic tree
COLLECTION_CONTEXT: dict[str, Any] = {
    "title": "Grundlagen",
    "path": ["Kernphysik"],
    "children": ["Atomaufbau", "Radioaktivität"],
    "materials": ["Der Atomkern im Überblick", "Zerfallsarten erklärt"],
    "neighbours": ["Kernspaltung", "Kernfusion"],
    "subjects": ["Physik"],
    "levels": ["Sekundarstufe I"],
}
MATERIAL: dict[str, Any] = {
    "title": "Stationsarbeit zur Optik",
    "description": "An sechs Stationen untersuchen die Lernenden, wie Licht an Linsen und Spiegeln gelenkt wird.",
    "keywords": ["Licht", "Linse", "Spiegel"],
    "subjects": ["Physik"],
    "levels": ["Sekundarstufe I"],
    "url": "https://example.org/stationsarbeit-optik",
}
SOURCES: list[dict[str, Any]] = [
    {
        "title": "Lochkamera im Unterricht",
        "text": (
            "Mit einer Lochkamera sehen die Lernenden, dass sich Licht geradlinig ausbreitet: Das Bild steht auf dem "
            "Kopf.\nJe kleiner das Loch, desto schärfer und dunkler wird das Bild auf dem Pergamentpapier."
        ),
        "url": "https://example.org/lochkamera",
        "license": "CC BY 4.0",
        "authors": ["Beispiel-Autorin"],
    }
]

COLLECTION_CONTEXT_DESCRIPTION = (
    "Die Sammlung als Text statt als node_id (D114): Der Dienst liest kein Repository und kommt zum selben Ergebnis "
    "wie mit dem Knoten. title ist der Titel der Sammlung; ein Titel ohne Sachbegriff wie Grundlagen steht für den "
    "nächsten aussagekräftigen Titel aus path. path sind die Sammlungen DARÜBER, von oben nach unten, die nächste "
    "zuletzt, ohne Fachportal und Wurzel; children ihre Untersammlungen (darunter), materials die Titel ihrer ersten "
    "Materialien, neighbours die "
    "anderen Untersammlungen ihrer Elternsammlung - dem LLM als nicht gemeint genannt. Ohne LLM zählt nur path, mit "
    "LLM hört die Artikelwahl alles. GET /api/v2/nodes/{node_id} liefert die Felder fertig unter "
    "text_input.collection_context."
)
MATERIAL_DESCRIPTION = (
    "Das Material als Text statt als node_id (D114): Titel, Beschreibung, Schlagwörter, Fächer und Stufen, wie sie "
    "in den Metadaten stehen. Der Titel nennt oft ein Format; die Regeln suchen den Artikel in Titel und "
    "Beschreibung (D47), mit LLM nennt ihn das LLM. GET /api/v2/nodes/{node_id} liefert die Felder fertig unter "
    "text_input.material."
)
SOURCES_DESCRIPTION = (
    "Eigene Texte als Quellen für Teil 1, wie die Materialien einer Wissens-Sammlung (D70, D114): je Zeile ein "
    "Absatz, Zeilen unter 40 Zeichen und Cookie-Hinweise fallen weg. Der Text wird wie ein Material zitiert und im "
    "Quellenverzeichnis mit seiner Lizenz genannt; weitergegeben unter CC BY-SA 4.0 nur aus freier Lizenz. "
    "audit.text_sources zählt, was ankam. Teil 1 muss dabei sein."
)
