# Entitäten und Kennungen: Methoden und Werte je Profil

[Übersicht](README.md) · Stand 28.09.2026 · Zahlen: [Messprotokoll](05-messprotokoll.md), M18, M20, M36, M41 bis
M43 und M45; Rohdaten und Zusammenfassungen in [messung/ergebnisse](messung/ergebnisse/README.md); alle Schritte im
Vergleich: [Methoden, Messwerte und Profile](09-methoden-und-profile.md)

`POST /api/v2/entities` findet in einem Text die Entitäten - Personen, Orte, Organisationen, Werke, Ereignisse und
Fachbegriffe -, verknüpft jede mit einem Artikel der geladenen Archive und nennt zu jedem Wikipedia-Artikel seine
Kennungen: GND, VIAF, Wikidata und DBpedia. Statt eines Textes nimmt er auch ein Material (`node_id`) und liest dann
dessen Titel, Beschreibung und Schlagwörter. Das geschieht in drei Schritten:

1. **Erkennen:** Welche Wörter des Textes sind Entitäten? Den Weg wählt das Profil (`preset`, D62).
2. **Verknüpfen:** Welcher Artikel ist gemeint? In allen Profilen gleich.
3. **Kennungen lesen:** Welche Nummern hat dieser Artikel? In allen Profilen gleich, aus lokalen Daten (D43, D64,
   D65).

Die Kennungen folgen also der Verknüpfung: Ist der Artikel richtig, sind es auch seine Nummern. Das Profil
entscheidet über die Güte, die lokalen Daten entscheiden darüber, wie viele Artikel eine Nummer bekommen. Zur
Anfragezeit fragt der Dienst nichts online außer der b-api für das LLM.

## Die Profile auf einen Blick

| | `llm-free` | `balanced` (Standard) | `best-quality` | `best-quality-generated` |
|---|---|---|---|---|
| Erkennen (`methods`) | `ner` (spaCy) und `dictionary` (Artikeltitel) | `llm`: das LLM nennt die Entitäten mit dem Titel ihres Artikels | wie `balanced` | wie `balanced` |
| Prüfen (`link_check`) | aus | aus, `llm` wählbar | aus, `llm` wählbar | aus, `llm` wählbar |
| Verknüpfen und Kennungen | Titel zum Artikel; Kennungen aus lokalen Daten | wie `llm-free` | wie `llm-free` | wie `llm-free` |
| Entitäten: Präzision / Recall / F1 (M36, D62) | 0,29 / 0,55 / 0,38 | 0,70 / 0,89 / 0,78 | wie `balanced` | wie `balanced` |
| Wikidata-Nummer: Präzision / Recall / F1 (M43) | 0,29 / 0,55 / 0,38 | 0,70 / 0,89 / 0,78 | wie `balanced` | wie `balanced` |
| GND: Präzision / Recall / F1 (M43) | 0,31 / 0,57 / 0,40 | 0,70 / 0,88 / 0,78 | wie `balanced` | wie `balanced` |
| DBpedia-URI über den englischen Artikel (M43) | 348 von 394 Artikeln (88 %) | 259 von 269 (96 %) | wie `balanced` | wie `balanced` |
| Tokens und Zeit je Text | keine; rund 0,25 s an den Materialtexten (M36), 1,0 s an 1.500 Zeichen Kompendiumtext auf dem Server (M45) | rund 800 Tokens und 4 s an den Materialtexten (M36); 1.284 Tokens und 6,8 s an 1.500 Zeichen (M45) | wie `balanced` | wie `balanced` |

`best-quality` und `best-quality-generated` erkennen wie `balanced`. Sie unterscheiden sich nur in Teil 1 des
Kompendiums, nicht in `/entities`. Die Werte gelten für die Texte von 40 echten Materialien (M36), benotet von zwei
Gutachtern. Mit `link_check: llm` prüft das LLM jede Verknüpfung, und nur die mit Note 2 bleiben: Die Präzision
steigt auf 0,94, aber ein Drittel der passenden Entitäten fällt weg (F1 0,76). Das kostet rund 820 Tokens und 2 s
mehr. Deshalb steht die Prüfung in keinem Profil; wer eine kurze, sichere Liste will, setzt sie selbst.

## 1. Erkennen

| Weg | Wie | Präzision / Recall / F1 (M36) | Kosten |
|---|---|---|---|
| `ner` | das spaCy-Modell des Images (`SPACY_MODEL`) findet Namen von Personen, Orten, Organisationen und Sonstigem | 0,41 / 0,23 / 0,30 | 0,25 s mit `dictionary` zusammen |
| `dictionary` | Wörter und Wortfolgen, die ein Artikeltitel der Archive sind; eine Begriffsklärung zählt nicht | 0,25 / 0,58 / 0,35 | |
| `ner` + `dictionary` (`llm-free`) | beide, überlappende Erwähnungen zusammengeführt | 0,29 / 0,55 / 0,38 | |
| `llm` (`balanced`, `best-quality`) | eine Frage an das LLM (`gpt-6-luna`): die Entitäten des Textes mit dem genauen Titel ihres Artikels; es zählt nur ein Titel, den das Archiv als Artikel hat, und nur ein Wort, das im Text steht | 0,70 / 0,89 / 0,78 | rund 800 Tokens, 4 s |
| `link_check: llm` | das LLM benotet jede Verknüpfung (2 zentral und genau gemeint, 1 nebensächlich, 0 etwas anderes); es bleibt Note 2 | im Dienst 0,94 / 0,64 / 0,76 | rund 820 Tokens, 2 s |

Die Regeln finden gut die Hälfte dessen, worum es in einem Text geht, bringen aber viel Beifang: Das Wörterbuch
verknüpft jedes Wort, das zugleich ein Artikeltitel ist („Woche“, „Frage“, „Ich“), und `ner` findet in englischen
Texten Verlage und Musiknachweise. Das LLM nennt, worum es geht, auch Fachbegriffe, die im Text anders dastehen, und
verknüpfte an diesen Texten nur einmal falsch. Jedes Wort, das es nennt, steht im Text; seine Stelle wird wie bei den
Regeln angegeben.

Ein lokaler Verknüpfer wäre die einzige Möglichkeit, `llm-free` treffsicherer zu machen. DBpedia Spotlight, der
einzige freie und lokal lauffähige für Deutsch, verknüpfte dieselben Texte nicht besser als die Regeln: bei gleicher
Menge F1 0,37 statt 0,38, aber doppelt so oft etwas ganz anderes, meist Namensvettern (M42 c). `llm-free` bleibt
deshalb bei den Regeln.

## 2. Verknüpfen

Jede Erwähnung wird über ihren Titel mit einem Artikel verknüpft, in der Reihenfolge der Archive (Wikipedia, dann
Klexikon; `archives` grenzt ein):

- Eine Weiterleitung führt zu ihrem Ziel. Eine Weiterleitung auf einen Abschnitt ist im ZIM eine eigene Seite, und
  der Endpunkt verknüpft mit ihr, nicht mit dem Artikel dahinter (D43). Manchen solchen Weiterleitungen gibt Wikidata
  ein eigenes Objekt: *Nenner* führt in *Bruchrechnung*, ist aber Q3044574.
- Eine Begriffsklärung zählt nicht als Artikel.
- Ein Genitiv findet seinen Artikel über die Grundform: „des Wassers“ führt zu *Wasser*, „Abraham Lincolns“ zu
  *Abraham Lincoln* (D46, M20).
- Die Art der Entität (Person, Organisation, Werk …) liest der Dienst aus der Einleitung des Artikels.

## 3. Kennungen

Zu jedem verknüpften Wikipedia-Artikel nennt der Endpunkt unter `ids` diese Kennungen, dazu alle als URI unter
`same_as`. Artikel anderer Archive tragen keine.

| Kennung | Woher | Wie | richtige Artikel mit Kennung (M43) | Stimmt die Nummer? |
|---|---|---|---|---|
| GND | Normdaten-Block der Seite im ZIM | der Link auf `d-nb.info/gnd/` im Block; `gnd_source: normdaten` | 139 von 188 | 30 von 30 (M18) |
| GND, wo der Block keine nennt | GND-Index aus den Abzügen der DNB (Sachbegriffe, Geografika) | zuerst der GND-Satz, der das Wikidata-Objekt des Artikels nennt (`gnd_source: wikidata`), sonst der eine Satz, der den Titel als Namen trägt (`name`); was zwei Sätze teilen, zählt nicht; nennt der Block eine Art (Person, Werk …), muss der Satz diese Art haben | 22 weitere, 21 davon derselbe Begriff | an allen 46 GND, die der Index verknüpften Artikeln gab: 41 derselbe Begriff, 3 verwandt, 2 etwas anderes, beide über den Namen (M43) |
| VIAF | Normdaten-Block | der Link auf `viaf.org` im Block | | |
| Wikidata | Wikidata-Index aus den Dumps `page_props` und `page` der deutschen Wikipedia | Titel zur Nummer; eine Weiterleitung mit eigenem Objekt behält ihre Nummer | 188 von 188 | 29 von 30 (M18) |
| DBpedia | derselbe Index, aus dem Dump `langlinks` | `http://dbpedia.org/resource/<englischer Titel>`; ohne englischen Artikel die IRI des deutschen Kapitels, `http://de.dbpedia.org/resource/<Titel>` | 198 von 211 Paaren aus Material und Artikel (94 %) | gebildet, nicht nachgeschlagen |

**Warum DBpedia über den englischen Artikel?** `de.dbpedia.org` antwortet nicht mehr: HTTP wird zurückgesetzt, und
HTTPS zeigt ein fremdes Zertifikat (geprüft am 27.09.2026). Der letzte deutsche Release stammt von 2022. DBpedia
vergibt seine lebenden Kennungen nach dem englischen Artikel, und `dbpedia.org/resource/<englischer Titel>` antwortet.
Die deutsche IRI bleibt nur als Rückfall für Artikel ohne englisches Gegenstück, meist deutsche Besonderheiten wie
*Deutschunterricht* oder *Landesbildungsserver Baden-Württemberg*.

**Warum der GND-Index?** Ein Viertel der richtigen Artikel hat keinen Normdaten-Block (M41), meist Fachbegriffe,
Ereignisse und Produkte. Die GND-Abzüge der DNB (CC0) nennen zu vielen Sätzen das Wikidata-Objekt und alle Namen. Wo
der Normdaten-Block die GND schon nennt, führten Objekt und Name im gebauten Index an 139 bekannten Nummern in 107 von
109 und 90 von 91 Fällen zu derselben Nummer (M43). Der Index nimmt nur Sachbegriffe und Geografika: Alle Vorschläge
für die Lücke kamen aus den Sachbegriffen, die Körperschaften (205 MB, 1,6 Millionen Namen) brachten keinen, dafür
viele Namensvettern (M42). Der Leser setzt Namenslisten fort, die die DNB nach einem Komma auf die nächste Zeile
umbricht; ohne das fehlten dem Index rund 139.000 Namen (M43).

## 4. Die Daten im Container

Beide Indexe baut je ein Sidecar selbst, auch bei einer neuen Installation. Die API öffnet einen neuen Index binnen
einer Minute, ohne Neustart. Fehlt ein Index, fehlt nur sein Teil der Kennungen, und `/health` meldet es unter
`entities`.

| Index | Sidecar | Quelle | Download | Bau (Entwicklungsrechner) | neu gebaut | Größe |
|---|---|---|---|---|---|---|
| `wikidata.db` | `wikidata-updater` (D64) | dumps.wikimedia.org, `dewiki`: `page_props`, `page`, `langlinks`, geprüft gegen die SHA-1 von Wikimedia | rund 750 MB | 619 s, davon rund 3,5 min Download (vor dem Vorfilter für `langlinks` 1.271 s) | wenn er fehlt oder unbrauchbar ist, und wenn das aktive Wikipedia-Archiv jünger ist als sein Dump und ein neuerer Lauf fertig ist; Prüfung täglich | 139 MB |
| `gnd.db` | `gnd-updater` (D65) | data.dnb.de/opendata: Sachbegriffe und Geografika als Turtle, geprüft gegen die SHA-256 der DNB | rund 65 MB | 78 s mit Download | wenn er fehlt oder unbrauchbar ist, und bei einer neueren Ausgabe der DNB, etwa zweimal im Jahr; Prüfung täglich | 55 MB |

Die Dumps löscht der Sidecar nach dem Bau. Jeder Lauf baut den neuen Index neben dem alten; scheitert er, bleibt der
alte in Betrieb. `wikidata_status.json` und `gnd_status.json` halten den letzten Lauf oder die letzte Prüfung fest.
Die Metriken `kompendium_wikidata_*` und `kompendium_gnd_*` samt vier Alarmen melden einen fehlenden Index und einen
gescheiterten Lauf.

## 5. Nicht gebaut, und warum

- **Lebende Abfragen** wie lobid-gnd (hbz), Entity Facts und SPARQL der DNB, die Wikidata-API oder DBpedia Lookup: Sie
  beruhen auf denselben Daten wie die Abzüge. lobid-gnd brächte vor allem eine unscharfe Suche, und die liefert gerade
  die Namensvettern, die der Index mit seiner Eindeutigkeitsregel ausschließt. Entity Facts braucht die GND-Nummer
  schon und kann eine Lücke deshalb nicht schließen. Jede lebende Abfrage machte die Antwort vom Netz und von einem
  fremden Dienst abhängig, und der Dienst fragt zur Anfragezeit nichts online.
- **Ein lokaler Verknüpfer für `llm-free`** (DBpedia Spotlight): nicht besser als die Regeln, dafür 4,4 GB
  Arbeitsspeicher und ein Modell von 2022 (M42 c).
- **Entitäten ohne Artikel in der deutschen Wikipedia:** Dafür bräuchte es die deutschen Namen aus Wikidata (Dump
  71,6 GB, 17 Millionen deutsche Namen, viele mehrdeutig) oder die ganze GND als Namensliste (1,8 GB, 10 Millionen
  Sätze). Fertige Verknüpfer für Wikidata auf Deutsch sind groß, alt oder nicht frei.
- **GND-Schlagwörter für einen ganzen Text,** wie die DNB sie vergibt: eine eigene Aufgabe (etwa Annif mit freien
  GND-Modellen), nicht gemessen.

## Grenzen der Zahlen

Alle Werte stammen von denselben 40 Materialtexten (M36). Der Recall zählt gegen das, was irgendein Weg fand
(Pooling), nicht gegen eine vollständige Liste. Alle Gutachter sind Claude-Subagenten, die blind und unabhängig
benoteten. Die Nummern selbst sind an Stichproben geprüft (M18: 30 GND- und 30 Wikidata-Nummern; M42 und M43: alle
46 GND, die der Index verknüpften Artikeln gab).
