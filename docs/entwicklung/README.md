# Kompendium-Dienst SC26: Entwicklung und Methoden

Stand 24.09.2026 · neuer Dienst v2.0.0 (`compendious-text-fastapi`, GitHub `compendius-textgenerator-sc26`) ·
alter Dienst v0.2.0 (`alterCode/compendious`) · nach v2.0.0 kamen hinzu: der LLM-Zuordner `matcher=llm` (D34), die
schärfere Artikelwahl mit `article_choice=llm` (D35), die günstigere LLM-Zuordnung (D36), `hybrid_light` bleibt
Standard der Zuordnung (D38), `matcher=llm` ohne Rückfall am Budget (D39), der LLM-freie Modus als Standard (D40, statt
`article_choice=llm` als Vorgabe mit LLM, D37) und der Schalter `preset` für die drei Stufen der Entscheidungsvorlage
(D41); eine Version mit Tag gibt es dafür noch nicht

Diese Seiten beschreiben, wie der Kompendium-Dienst für das Sommercamp 2026 (SC26) neu gebaut wurde, was vom alten
Dienst geblieben ist und warum die Verfahren so gewählt sind. Die Messungen vom 23. und 24.09.2026 stehen mit Aufbau und
Rohdaten im [Messprotokoll](05-messprotokoll.md); ältere Messwerte tragen Datum und Quelle (`PLAN.md`,
`eval/README.md`).

## Kurzfassung

- **Drei Bereiche statt einem.** Der Dienst erzeugt ein Markdown-Kompendium aus Weltwissen (Wikipedia, Klexikon),
  Lehrplanbezügen (MEM-Lehrpläne) und einem Überblick über die WLO-Sammlung (edu-sharing). Der alte Dienst kannte
  nur das Weltwissen.
- **Übernehmen statt Schreibenlassen.** Im Standardmodus trägt jeder Absatz des Weltwissens eine Belegnummer, und
  jeder Satz steht wörtlich in dem Absatz, auf den seine Nummer zeigt: 432 von 432 Sätzen mit eigener Nummer in zehn
  Testthemen, dazu 26 Listenpunkte, deren Liste als Ganzes belegt ist. Beim alten Dienst tragen 24 % der Sätze eine
  Quellenangabe, nachweislich gestützt sind 21 %; der Rest ist nicht belegt.
- **Schneller, ohne Tokens.** Weltwissen und Lehrplanbezüge brauchen ohne LLM-Schalter auf dem Server im Median
  2,8 s und kein Sprachmodell. Der alte Dienst brauchte im besten Fall 35 s und rund 7.900 Tokens. So wie er
  ausgeliefert ist, weist Wikipedia seine Anfragen ab: Er lief dann 374 s und lieferte einen Text ohne eine einzige
  Quelle, aber mit Belegnummern.
- **Quellen offline.** Wikipedia und Klexikon liegen als Kiwix-ZIM-Archive beim Dienst: direkt lesbar, mit
  eingebautem Suchindex, ohne Sperren oder Drosselung zur Laufzeit.
- **Artikelwahl gemessen und verbessert.** Den Hauptartikel trifft der Dienst bei normalen Themen und
  Klassenzusätzen immer. Bei mehrdeutigen Wörtern mit Fachangabe waren es in M8 nur 6 von 16; mit den Kontextwörtern
  des Fachs, Wortstämmen und Genitivregeln trifft er über drei Goldsätze 86 statt 66 von 94 Anfragen, und wo er
  unsicher ist, holt ein LLM (`article_choice=llm`) weitere 5. Auf den zehn Goldthemen passen 6 % der Korpusartikel
  nicht zum Thema, beim alten Dienst 14 %. Die schwächste Quelle sind die Volltexttreffer je Baustein; mit
  `article_choice=llm` fallen die unpassenden heraus, und der Standard druckt 10 statt 26 Absätze aus unpassenden
  Artikeln. Das kostet im Median 1,7 s und rund 930 Tokens je Kompendium; man schaltet es mit `preset: balanced`
  ein, Standard ist der LLM-freie Modus (D40).
- **Zuordnung zu den zehn Inhaltsbausteinen des SC26-Templates** über eine Regel-Policy mit einfachen Rankern
  (`hybrid_light` mit Model2Vec). Alle Verfahren wurden im selben Ablauf gegen den Goldstandard des Dienstes
  gemessen. Unter den lokal laufenden erreicht der Standard den besten Wert (macro-F1 0,45, 67 % richtige
  Spitzenabsätze) in 0,3 s. Die schwereren Modelle der Testapp und ein Cross-Encoder als Umsortierung schneiden
  schlechter ab. Ein LLM als Zuordner (`gpt-5.6-luna`) ist deutlich besser, rund 0,7 statt 0,43 auf den gelabelten
  Absätzen (0,66 bis 0,73 in vier Läufen), und ist seit D34 als `matcher=llm` wählbar; es kostet seit D36 rund 180
  Tokens je Absatz, und Teil 1 dauert im Median 12 statt 1,2 s. Standard bleibt deshalb `hybrid_light` (D38).
- **Sprachmodell optional.** Schalter lassen ein LLM Sätze auswählen oder Bausteine umformulieren, auf Wunsch auch
  mit eigenem, sichtbar markiertem Wissen; jeder Satz wird gegen seine Quelle geprüft, und ohne LLM läuft der
  Regelmodus weiter.
- **Der Preis:** Der Text liest sich wie eine geordnete Sammlung von Auszügen. Für KI und Weiterverarbeitung ist das
  ideal, für Menschen weniger; kleine Bausteine bleiben oft leer.

## Die drei Bereiche

| Bereich | Inhalt | Quelle | Verfahren | Form im Markdown |
|---|---|---|---|---|
| Teil 1 · Weltwissen | gesichertes Wissen zum Thema, gegliedert nach dem SC26-Template (13 Bausteine, drei davon erzeugt) | Wikipedia DE und Klexikon als lokale ZIM-Archive | Absätze auswählen, einem Baustein zuordnen, wörtlich übernehmen, belegen | Bausteine mit Belegnummern `[n]`, dazu Akteure, Quellen, Glossar |
| Teil 2 · Lehrplanbezüge | was Lehrpläne aller Bildungsstufen zum Thema vorsehen | MEM-Lehrpläne (Bayern, Sachsen, Rheinland-Pfalz, Berlin) als lokaler Cache | Stichwortsuche mit Fach- und Wortgrenzenfilter | nach Stufe, Land und Lehrplan gruppiert, je Gruppe ein Facettenmarker |
| Teil 3 · Sammlungsüberblick | was die WLO-Sammlung zum Thema enthält | edu-sharing-Repository | Abruf zur Anfragezeit, gebündelt | je Sammlung und Inhalt eine Zeile mit Art und nodeId |

## Alt und neu auf einen Blick

| | Alter Dienst v0.2.0 | Neuer Dienst v2.0.0 |
|---|---|---|
| Bereiche | Weltwissen | Weltwissen, Lehrplanbezüge, Sammlungsüberblick |
| Quelle des Weltwissens | Wikipedia-Live-API, je Begriff nur die Einleitung | Wikipedia und Klexikon als ZIM-Archive, ganze Artikel |
| Artikelwahl | LLM rät zehn Artikeltitel | Titel, Weiterleitung, Begriffsklärung nach den Fachwörtern, Titelvorschläge, Volltextsuche; meldet, wie sicher sie ist; LLM optional für unsichere Fälle |
| Entstehung des Textes | ein LLM-Aufruf schreibt alles | Absätze werden zugeordnet und wörtlich übernommen, LLM optional |
| Gliederung | 15 Aspekte als Hinweis im Prompt | Template SC26 mit 13 Bausteinen, maschinenlesbar markiert |
| Belege | 24 % der Sätze mit Quellenangabe, 21 % gestützt | jeder Absatz belegt; jeder Satz steht wörtlich im zitierten Absatz |
| Dauer | 35 s (bester Fall) bis 374 s (Wikipedia weist ab) | 2,8 s für Teil 1 und 2 (Median, Server, ohne LLM); mit `article_choice=llm` im Median 1,7 s mehr, mit `matcher=llm` dauert Teil 1 12,0 statt 1,2 s (M13, Entwicklungsrechner), bei langsamerer b-api und ohne Rückfall am Budget 22,7 s (M14) |
| Tokens je Kompendium | rund 7.900 | 0 im Standard (D40); mit `article_choice=llm` (`preset: balanced`) im Median 927; `matcher=llm` im Mittel 29.400 (M13), seit D39 34.500 (M14); Satzauswahl und Umformulierung 2.300 bis rund 37.000 |
| Hauptartikel richtig | 9 von 10 Themen hatten ihn unter den Quellen (M2) | 10 von 10 (M3); an 94 schwierigeren Goldanfragen 86 mit den Regeln, 91 mit `article_choice=llm` (M9) |
| unpassende Artikel unter den Quellen (blind bewertet, M8) | 14 % | 6 % |
| Zuordnung zu den Bausteinen, macro-F1 am Goldstandard | – (keine Bausteine) | 0,43 bis 0,45 mit `hybrid_light` in 0,3 s je Thema; 0,69 bis 0,72 mit `matcher=llm` in 11 bis 22 s (Median in M13 und M14) |
| Wenn eine Quelle ausfällt | liefert trotzdem eine normale Antwort, ohne Quellen | Archive liegen lokal; ein fehlender Teil steht in `parts_status` |

## Die wichtigsten Entscheidungen

| Entscheidung | Warum | Preis |
|---|---|---|
| Neubau statt Umbau des alten Dienstes | Der alte Dienst ist um einen einzigen LLM-Aufruf gebaut; drei Teile, feste Bausteine und Belegpflicht passen nicht hinein. Der Kern kommt aus der Testapp `kompendium-test`. | Aufrufer stellen auf die Endpunkte unter `/api/v2` um. |
| Kiwix-ZIM statt Live-API oder XML-Dump | direkt nutzbar, Suchindex eingebaut, keine Sperren, Klexikon und weitere Quellen im selben Format | 15 GB Speicher; Aktualität so, wie Kiwix die Archive baut |
| Extraktiv als Standard, LLM optional | keine Verfälschung, jeder Satz prüfbar, schnell, ohne Tokens, reproduzierbar | liest sich weniger flüssig |
| Template SC26 mit Markern | einheitliche Gliederung; Bausteine und Facetten lassen sich maschinell herauslösen | – |
| Zuordnung über Regel-Policy mit `hybrid_light` und Model2Vec | bester Wert der lokal laufenden Verfahren auf dem Goldstandard, 0,3 s auf der CPU, ohne Tokens; ein LLM ordnet besser zu (0,69 bis 0,72), braucht aber für Teil 1 12,0 bis 22,7 statt 1,2 bis 1,8 s und im Mittel 29.400 bis 34.500 Tokens je Kompendium (M13, M14) und bleibt deshalb wählbar (`matcher=llm`, D38) | Ziel macro-F1 0,70 nicht erreicht |
| Artikelwahl mit `article_choice=llm` auf Wunsch (D35, D40) | holt die unsicheren Fälle (91 statt 86 von 94 Goldanfragen) und wirft unpassende Volltexttreffer heraus (gedruckt aus unpassenden Artikeln 10 statt 26 Absätze) | im Median 1,7 s und 927 Tokens je Kompendium |
| Standard LLM-frei, drei Stufen mit einem Schalter `preset` (D40, D41) | Zeit und Tokens eines LLM nur, wo es jemand ausdrücklich will; `llm-free`, `balanced` und `best-quality` statt fünf Einzelschalter | die Vorteile der LLM-Artikelwahl muss man einschalten |
| Lieber leer als falsch | Ein falscher Absatz schadet mehr als ein ehrlich leerer Baustein. | kleine Bausteine bleiben oft leer |
| Lehrpläne aus einem MEM-Vollabzug, keine Abfrage zur Laufzeit | schnell, keine Last und kein Ausfallrisiko beim Anbieter | Inhalte bis zu einem Monat alt; vier Länder |
| Teil 3 zur Anfragezeit aus edu-sharing | aktuell bis auf einen Zwischenspeicher von einer Stunde, kein eigener Datenbestand | hängt an der Erreichbarkeit des Repositorys |
| Kein Rückschreiben | Der Dienst liefert Markdown und JSON, der Aufrufer speichert. | – |

## Die Seiten

1. [Alter und neuer Dienst im Vergleich](01-alt-und-neu.md): Problemlagen des alten Dienstes, was der neue dagegen
   setzt, Funktionsumfang, Messvergleich
2. [Bereich 1: Weltwissen](02-weltwissen.md): Quellen (ZIM, API, XML-Dump), Artikelwahl und ihre Güte, extraktiv
   oder generativ, Wege zu besserer Lesbarkeit
3. [Zuordnung zu den SC26-Bausteinen](03-matching.md): welche Daten eingehen, Verfahren aus Dienst und Testapp im
   Ablauf des Dienstes am Goldstandard gemessen, das LLM als wählbare Strategie, Wahl des Standardverfahrens
4. [Bereiche 2 und 3: Lehrpläne und Sammlung](04-lehrplaene-und-sammlung.md): MEM-Cache, Sammlungsüberblick,
   Vorschlag für einen Live-Teil 3, Markdown-Konventionen
5. [Messprotokoll](05-messprotokoll.md): Aufbau, Zahlen, Skripte; Rohdaten und lesbare Zusammenfassungen je Messung
   in [messung/ergebnisse](messung/ergebnisse/README.md)
6. [Daten für später: Protokoll, Training, Paket](06-daten-und-training.md): woher Trainingsdaten für ein lokales
   Modell kommen könnten, was ein Paket wäre, Empfehlung
7. [Entscheidungsvorlage: Verfahren und Schalter von Teil 1](07-entscheidungsvorlage.md): je Schritt die Verfahren,
   ihre Schalter und Standardwerte, Güte, Zeit und Tokens mit Grafiken, drei empfohlene Kombinationen

Die Seiten sind als Baum für Confluence gedacht: diese Übersicht als Elternseite, die sieben übrigen darunter. Die
Links zwischen ihnen zeigen auf die Markdown-Dateien und müssen nach dem Import auf die Confluence-Seiten umgestellt
werden. Die Grafiken liegen als SVG unter `docs/entwicklung/bilder/` und kommen beim Import als Anhänge mit. Die
Messskripte bleiben im Repository unter `docs/entwicklung/messung/`.

## Entwicklungsweg

| Zeitraum | Schritt |
|---|---|
| 16.–18.09.2026 | Testapp `kompendium-test`: ZIM-Zugriff, Segmentierung, mehrere Matcher, extraktive Synthese |
| 17.09. | Neubauplan (`PLAN.md`); Fundament, ZIM-Betrieb, Goldstandard, Lehrplan-Cache (Teil 2), Sammlung (Teil 3) |
| 18.09. | LLM-Schicht über die b-api, Audit, Nachschärfung der Zuordnung (Schwelle 0,65, Abschnitts-Glättung) |
| 19.09. | Review-Runden; LLM-Schalter statt fester Modi |
| 20.–22.09. | Umbau: alte v1-Endpunkte entfernt; neue Endpunkte für Wissen, Entitäten und Fragen; Modelle im Image |
| 23.09. | Release v2.0.0, Betrieb auf Hostinger; danach die Artikelwahl gemessen und der LLM-Zuordner als `matcher=llm` eingebaut (D34) |
| 24.09. | Artikelwahl mit den Kontextwörtern des Fachs (M9), Trefferprüfung (M10), Wikibooks und Wikiversity verworfen (M11), günstigere LLM-Zuordnung (D36, M12), Laufzeit der LLM-Schalter (M13); `article_choice=llm` Vorgabe, wo ein LLM konfiguriert ist (D37); `hybrid_light` bleibt Standard (D38); `matcher=llm` ohne Rückfall am Budget (D39, M14); Entscheidungsvorlage mit Grafiken (M15); Standard wieder LLM-frei (D40) und der Schalter `preset` (D41); laya gemessen und nicht eingebaut (M16, D42); der alte Weg über Begriffe vom LLM auf dem Gold (M17); GND-Nummern aus dem Archiv (M18); Kennungen GND, Wikidata und DBpedia im Entitäten-Endpunkt (D43); `gpt-6-luna` als Vorgabemodell (M19, D44) |

## Begriffe

| Begriff | Bedeutung |
|---|---|
| Baustein | ein Abschnitt des SC26-Templates, etwa „Themendefinition“ oder „Praxis“ |
| Belegnummer | `[n]` hinter einem Absatz; führt zu Artikel, Abschnitt und Textstelle |
| Facette | Merkmal eines Absatzes wie Bildungsstufe oder Bundesland, als unsichtbarer Marker im Markdown |
| ZIM | Archivformat von Kiwix: komprimierte Artikel mit Titel- und Volltextindex |
| MEM | Triplestore der FWU mit maschinenlesbaren Lehrplänen |
| b-api | Gateway der WLO-Infrastruktur (openeduhub) zu Sprachmodellen |
| Goldstandard | Absätze zu zehn Themen mit festgelegtem Soll-Baustein, gegen die Verfahren gemessen werden (von Claude vorgeschlagen, Zeile für Zeile gelesen, redaktionell noch ungeprüft) |
| Policy | die Regeln, die aus den Rankerwerten eine Zuordnung machen |
