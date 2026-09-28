# Kompendium-Dienst SC26: Entwicklung und Methoden

Stand 28.09.2026 · neuer Dienst Release 2.2.2 (`compendious-text-fastapi`, GitHub `compendius-textgenerator-sc26`) ·
alter Dienst v0.2.0 (`alterCode/compendious`) · was seit v2.0.0 dazukam, steht unter „Die wichtigsten
Entscheidungen“ und im Entwicklungsweg; die Releases 2.1.0 bis 2.2.2 enthalten alles bis zum 28.09.2026

Diese Seiten beschreiben, wie der Kompendium-Dienst für das Sommercamp 2026 (SC26) neu gebaut wurde, was vom alten
Dienst geblieben ist und warum die Verfahren so gewählt sind. Die Messungen vom 23. bis 28.09.2026 stehen mit Aufbau
und Rohdaten im [Messprotokoll](05-messprotokoll.md); ältere Messwerte tragen Datum und Quelle (`PLAN.md`,
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
  2,3 s und kein Sprachmodell (M45). Der alte Dienst brauchte im besten Fall 35 s und rund 7.900 Tokens. So wie er
  ausgeliefert ist, weist Wikipedia seine Anfragen ab: Er lief dann 374 s und lieferte einen Text ohne eine einzige
  Quelle, aber mit Belegnummern.
- **Quellen offline.** Wikipedia und Klexikon liegen als Kiwix-ZIM-Archive beim Dienst: direkt lesbar, mit
  eingebautem Suchindex, ohne Sperren oder Drosselung zur Laufzeit.
- **Artikelwahl gemessen und verbessert.** Den Hauptartikel trifft der Dienst bei normalen Themen und
  Klassenzusätzen immer. Bei mehrdeutigen Wörtern mit Fachangabe waren es in M8 nur 6 von 16; mit den Kontextwörtern
  des Fachs, Wortstämmen und Genitivregeln trifft er über drei Goldsätze 86 statt 66 von 94 Anfragen, und wo er
  unsicher ist, holt ein LLM (`article_choice=llm`) weitere 5. Auf den zehn Goldthemen passen 6 % der Korpusartikel
  nicht zum Thema, beim alten Dienst 14 %. Die schwächste Quelle sind die Volltexttreffer je Baustein; die ohne
  Link zum Hauptartikel fallen seit D48 immer weg, und `llm-free` druckt 12 statt 25 Absätze aus unpassenden
  Artikeln. Seit D63 nennt das LLM im Standardprofil `balanced` Übersicht und Teile des Themas: Bei Sammel- und
  Mischthemen stammen dann 87 statt 43 % der gedruckten Absätze aus passenden Artikeln, für rund 5 s und 500 Tokens
  je Kompendium (M39, M45); `llm-free` bleibt bei den Regeln.
- **Ein Material als Eingang.** Mit `node_id` liest der Dienst Titel, Beschreibung, Schlagwörter, Fach und Stufe
  eines Materials. Weil Titel oft ein Format nennen, sucht er den Artikel in Titel und Beschreibung: ohne LLM mit
  Hauptartikel-F1 0,56 und 0,63 an zwei Stichproben echter Materialien (der Titel allein: 0,20 und 0,00), mit LLM
  0,98 und 0,88. Thema und Material lassen sich kombinieren; der Artikel des Materials kommt dann als weitere Quelle
  dazu (M21 bis M25).
- **Zuordnung zu den zehn Inhaltsbausteinen des SC26-Templates** über eine Regel-Policy mit einfachen Rankern
  (`hybrid_light` mit Model2Vec). Alle Verfahren wurden im selben Ablauf gegen den Goldstandard des Dienstes
  gemessen. Unter den lokal laufenden erreicht der Standard den besten Wert (macro-F1 0,45, 67 % richtige
  Spitzenabsätze) in 0,3 s. Die schwereren Modelle der Testapp und ein Cross-Encoder als Umsortierung schneiden
  schlechter ab. Ein LLM als Zuordner ist deutlich besser, macro-F1 0,70 statt 0,45 auf den gelabelten Absätzen (M19),
  und steht als `matcher=llm` in den `best-quality`-Profilen; es kostet rund 170 Tokens je Absatz und rund 13 s je
  Kompendium (M27, M45). Standard bleibt deshalb `hybrid_light` (D38).
- **Sprachmodell optional.** Schalter lassen ein LLM Sätze auswählen oder Bausteine umformulieren, auf Wunsch auch
  mit eigenem, sichtbar markiertem Wissen; jeder Satz wird gegen seine Quelle geprüft, und ohne LLM läuft der
  Regelmodus weiter.
- **Vier Profile.** `preset` wählt die Methoden aller Schritte. Ein Kompendium mit Teil 1 und 2 braucht auf dem
  Server mit `llm-free` 2,3 s und keine Tokens, mit dem Standard `balanced` rund 7 s und 580 Tokens, mit
  `best-quality` rund 26 s und 49.000, mit `best-quality-generated` rund 36 s und 60.000 (M45). Welche Methode in
  welchem Profil steckt, wie gut sie ist und warum: [Methoden, Messwerte und Profile](09-methoden-und-profile.md).
- **Der Preis:** Der Text liest sich wie eine geordnete Sammlung von Auszügen. Für KI und Weiterverarbeitung ist das
  ideal, für Menschen weniger; kleine Bausteine bleiben oft leer.

## Die drei Bereiche

| Bereich | Inhalt | Quelle | Verfahren | Form im Markdown |
|---|---|---|---|---|
| Teil 1 · Weltwissen | gesichertes Wissen zum Thema, gegliedert nach dem SC26-Template (13 Bausteine, drei davon erzeugt) | Wikipedia DE und Klexikon als lokale ZIM-Archive | Absätze auswählen, einem Baustein zuordnen, wörtlich übernehmen, belegen | Bausteine mit Belegnummern `[n]`, dazu Akteure, Quellen, Glossar |
| Teil 2 · Lehrplanbezüge | was Lehrpläne aller Bildungsstufen zum Thema vorsehen | MEM-Lehrpläne (Bayern, Sachsen, Rheinland-Pfalz, Berlin) als lokaler Cache | Stichwortsuche mit Fach- und Wortgrenzenfilter | nach Stufe, Land und Lehrplan gruppiert, je Gruppe ein Facettenmarker |
| Teil 3 · Sammlungsüberblick | was die WLO-Sammlung zum Thema enthält | edu-sharing-Repository | Abruf zur Anfragezeit, gebündelt | je Sammlung und Inhalt eine Zeile mit Art und nodeId |

## Alt und neu auf einen Blick

| | Alter Dienst v0.2.0 | Neuer Dienst 2.2.2 |
|---|---|---|
| Bereiche | Weltwissen | Weltwissen, Lehrplanbezüge, Sammlungsüberblick |
| Quelle des Weltwissens | Wikipedia-Live-API, je Begriff nur die Einleitung | Wikipedia und Klexikon als ZIM-Archive, ganze Artikel |
| Artikelwahl | LLM rät zehn Artikeltitel | Titel, Weiterleitung, Begriffsklärung nach den Fachwörtern, Titelvorschläge, Volltextsuche; meldet, wie sicher sie ist; LLM optional für unsichere Fälle; ab `balanced` nennt das LLM Übersicht und Teile jedes Themas (D63) |
| Entstehung des Textes | ein LLM-Aufruf schreibt alles | Absätze werden zugeordnet und wörtlich übernommen, LLM optional |
| Gliederung | 15 Aspekte als Hinweis im Prompt | Template SC26 mit 13 Bausteinen, maschinenlesbar markiert |
| Belege | 24 % der Sätze mit Quellenangabe, 21 % gestützt | jeder Absatz belegt; jeder Satz steht wörtlich im zitierten Absatz |
| Dauer je Kompendium | 35 s (bester Fall) bis 374 s (Wikipedia weist ab) | Teil 1 und 2 auf dem Server: 2,3 s (`llm-free`), rund 6,9 s (`balanced`, Standard), 26 s (`best-quality`) und 36 s (`best-quality-generated`) (M45) |
| Tokens je Kompendium | rund 7.900 | Median je Profil 0, 576, 49.019 und 60.357 (M45) |
| Hauptartikel richtig | 9 von 10 Themen hatten ihn unter den Quellen (M2) | 10 von 10 (M3); an 94 schwierigeren Goldanfragen 87 mit den Regeln (`llm-free`), 91 mit `article_choice=llm` (`balanced`), 93 mit `llm-thorough` (`best-quality`-Profile, M35) |
| unpassende Artikel unter den Quellen (blind bewertet, M8) | 14 % | 6 % |
| Sammel- und Mischthemen wie „deutsche Dichter“: gedruckte Absätze aus passenden Artikeln, 25 Themen, zwei Gutachter | mit den Entitäten des alten Linkers als Korpus 63 % (M37) | `llm-free` 43 %; `balanced` seit D63 87 %, das LLM nennt Übersicht und Teile; bei 20 gewöhnlichen Themen 71 und 93 % (M37, M39) |
| Zuordnung zu den Bausteinen, macro-F1 am Goldstandard | – (keine Bausteine) | 0,45 mit `hybrid_light` in 0,3 s je Thema (`llm-free`, und `balanced` vor D63, M27); 0,70 mit `matcher=llm` (`best-quality`, M19), rund 11 s |
| QA-Paare, mangelfrei nach zwei Gutachtern | – | sechs Themen, je 20 Paare verlangt: `rule-based` (`llm-free`, seit D57 auch `balanced`) 58 von 95 in 0,3 s je Text (M34, vorher 48 von 96 in M30), `llm` (`best-quality`, `best-quality-generated`) 99 von 120 mit rund 2.400 Tokens (M30) |
| Entitäten in einem Text (`/entities`), F1 an 40 Materialtexten nach zwei Gutachtern | der Linker ließ ein LLM Begriffe nennen und schlug sie live nach; an diesen Texten nicht gemessen | 0,38 mit spaCy und dem Wörterbuch der Artikeltitel (`llm-free`), 0,78 mit dem LLM, das die Entitäten mit Artikeltitel nennt (`balanced` und `best-quality`-Profile; an 1.500 Zeichen rund 1.300 Tokens und 7 s; M36, M45, D62) |
| Lehrplanelemente von Teil 2, passend nach zwei Gutachtern | – | 20 Themen, Mittel: Regeln mit B (`llm-free`, `balanced`) 70 bis 81 %, LLM-Prüfung (`best-quality`) 74 bis 79 %, vorher 62 bis 67 % (M32) |
| Wenn eine Quelle ausfällt | liefert trotzdem eine normale Antwort, ohne Quellen | Archive liegen lokal; ein fehlender Teil steht in `parts_status` |

## Die wichtigsten Entscheidungen

Der Preis gilt zur Zeit der Entscheidung; die heutigen Werte je Profil stehen auf
[Methoden, Messwerte und Profile](09-methoden-und-profile.md) (M45). Je Teil ausführlich: [Alter und neuer Dienst im
Vergleich](01-alt-und-neu.md).

| Entscheidung | Warum | Preis |
|---|---|---|
| Neubau statt Umbau des alten Dienstes | Der alte Dienst ist um einen einzigen LLM-Aufruf gebaut; drei Teile, feste Bausteine und Belegpflicht passen nicht hinein. Der Kern kommt aus der Testapp `kompendium-test`. | Aufrufer stellen auf die Endpunkte unter `/api/v2` um. |
| Kiwix-ZIM statt Live-API oder XML-Dump | direkt nutzbar, Suchindex eingebaut, keine Sperren, Klexikon und weitere Quellen im selben Format | 15 GB Speicher; Aktualität so, wie Kiwix die Archive baut |
| Extraktiv als Standard, LLM optional | keine Verfälschung, jeder Satz prüfbar, schnell, ohne Tokens, reproduzierbar | liest sich weniger flüssig |
| Template SC26 mit Markern | einheitliche Gliederung; Bausteine und Facetten lassen sich maschinell herauslösen | – |
| Zuordnung über Regel-Policy mit `hybrid_light` und Model2Vec | bester Wert der lokal laufenden Verfahren auf dem Goldstandard, 0,3 s auf der CPU, ohne Tokens; ein LLM ordnet besser zu (0,69 bis 0,72), braucht aber für Teil 1 12,0 bis 22,7 statt 1,2 bis 1,8 s und im Mittel 29.400 bis 34.500 Tokens je Kompendium (M13, M14) und bleibt deshalb wählbar (`matcher=llm`, D38) | Ziel macro-F1 0,70 nicht erreicht |
| Artikelwahl mit `article_choice=llm` (D35) | holt die unsicheren Fälle (91 statt 86 von 94 Goldanfragen) und wirft unpassende Nebenartikel heraus (gedruckt aus unpassenden Artikeln 5 statt 12 Absätze, M25) | rund 1,5 bis 2 s und 900 Tokens je Kompendium |
| Vier Profile statt Einzelvorgaben, Standard `balanced` (D53, D54) | ein Schalter wählt alle Verfahren, auch das der QA-Paare; das LLM arbeitet dort, wo es am meisten bringt, und ohne konfiguriertes LLM sagt ein 503, was fehlt | der Server braucht ein LLM, sonst `PRESET_DEFAULT=llm-free` |
| QA-Paare ohne LLM aus dem Parse, Teil 1 von `/qa` immer ohne LLM (D55) | die vier Vorlagen fragten zu 82 % nach einer Zeit und hielten `count` nicht ein; die Regeln fragen nach Zeit, Ort, Person, Sache, Anzahl, Grund und Definition und liefern die Hälfte ihrer Paare mangelfrei, in 0,3 s und ohne Tokens (M30) | ein kurzer Text gibt weniger Paare her als verlangt, `note` sagt es; jedes zweite Paar hat noch einen Mangel, meist eine Frage, die ohne den Text unklar ist |
| Modellwissen sichtbar gekennzeichnet und nur als Sachaussage (D56) | der Kommentar allein verschwand beim Rendern; der schärfere Prompt ergänzt 50 statt 82 Sätze, davon 13 statt 50 Füllsätze (M31) | rund 3 % mehr Tokens; einige Füllsätze bleiben |
| Der Standard fragt mit den Regeln, die zwei QA-Modelle sind entfernt (D57) | in M30 waren die Modelle die schwächste und langsamste Stufe (25 von 120 mangelfrei, rund 25 s je Text, 1,3 GB je Worker); der Standard soll schnell und sparsam fragen (Jan) | im Standard 48 von 96 mangelfrei statt 99 von 120 mit dem LLM; wer mehr will, nimmt `best-quality` |
| Lehrplanbezüge je Profil: Überschriften-Treffer gebündelt, LLM-Prüfung in `best-quality`, Herkunft je Block (D58) | B hebt den Anteil passender Elemente ohne Kosten von 62 bis 67 auf 70 bis 81 %; die LLM-Prüfung hält ihn ohne ein passendes Element zu verlieren (M32) | ein Viertel der passenden steht mit B nur gebündelt; die Prüfung kostet rund 8.000 bis 10.000 Tokens und 6 s je Anfrage |
| Budget je Anfrage nach Profil, 180.000 Tokens für die `best-quality`-Profile; Lehrplansuche mit Profilen; `/docs` je Endpunkt (D59) | die LLM-Prüfung braucht 80 bis 90 Tokens je Lehrplanelement; mit 180.000 prüft sie beim breitesten Thema alle 819 Elemente, auch neben Zuordnung und Schreiben (M33) | eine Anfrage darf bis 180.000 Tokens kosten; Demokratie mit Teil 1 und 2 kostete 137.398 und 152.197 |
| QA-Paare: Glossar und Akteure füllen auf, drei Sperren aus M30, ein Kompendium als Text wird wie eines gelesen, keine Fragen als Modellwissen (D60) | Jan: gibt ein Text wenig her, auffüllen; an den Texten von M30 58 statt 46 von 95 Paaren mangelfrei (M34) | kurze Themen bleiben kurz, und Nachbar-Personen gelten den Gutachtern oft als trivial |
| Der Text eines Aufrufers und ein mitgeschicktes Kompendium werden in linearer Zeit gelesen; ein leerer Baustein ist keine Prosa, ein Kompendium ohne Prosa hat nichts zu fragen (Reviews von D60) | seit D60 laufen Glossar- und Akteursmuster auf dem Text, den `/qa` ohne Anmeldung annimmt, und `existing_markdown` von `/compendium` darf 2.000.000 Zeichen haben; eine präparierte Eingabe hielt einen Worker Sekunden bis Stunden fest | keiner: die Paare der sechs Themen von M30 bleiben gleich |
| Das LLM prüft in den `best-quality`-Profilen auch sichere Auflösungen mehrdeutiger Wörter (`article_choice: llm-thorough`, D61) | Jan: mehrdeutige Wörter prüfen; am Gold 93 statt 91 von 94, keine der 44 richtigen sicheren Auflösungen verdorben (M35) | das LLM wird bei 64 statt 18 von 94 Anfragen gefragt, je Frage rund 800 Tokens und 1 s; `balanced` bleibt bei `llm` |
| `/entities` nimmt Profile: `llm-free` erkennt mit den Regeln, `balanced` und die `best-quality`-Profile lassen das LLM die Entitäten mit ihrem Artikeltitel nennen (D62) | Jan: Methoden gemäß den Ergebnissen zuordnen; an den Texten von 40 Materialien F1 0,78 statt 0,38, durch den Endpunkt nachgemessen (M36); die Prüfung jeder Verknüpfung hob die Präzision auf 0,94, kostete aber ein Drittel der passenden Entitäten (F1 0,76) und bleibt ein eigener Schalter | rund 800 Tokens und 4 s je Text; ohne `preset` braucht der Endpunkt nun ein LLM, auf einem Server ohne LLM ein 503 |
| Ab `balanced` nennt das LLM Übersicht und Teile jedes Themas; sie ersetzen die verlinkten Unterartikel und Volltexttreffer, die Übersicht den Hauptartikel, wo die Regeln das Thema verfehlen (D63) | Jan: `gpt-6-luna` stellt die Frage ab `balanced`, `llm-free` bleibt ohne LLM; 87 statt 45 % passende Absätze bei Sammelthemen und 93 statt 73 % bei gewöhnlichen, durch den Dienst nachgemessen (M37, M39); ohne großes LLM nicht erreichbar, auch nicht mit kleinen lokalen Modellen (M38, M40) | rund 3,6 s und 480 Tokens je Thema statt der Prüfung der Nebenartikel; das Gold der Zuordnung deckt den neuen Korpus nicht mehr ab |
| Neue Installationen bauen den Wikidata-Index selbst: Sidecar `wikidata-updater`, neu nach einem jüngeren Wikipedia-Archiv, die API übernimmt ihn ohne Neustart (D64) | Jan: neue Installationen müssen die Daten bekommen; ohne Index fehlte jede Wikidata-Nummer, und das ZIM trägt sie nicht (14 von 188 Seiten, M41) | rund 420 MB Download und 6 min, wenn der Index fehlt oder ein neues Archiv kommt; ein vierter Container |
| Kennungen wie empfohlen, lokal und in allen Profilen gleich: die GND ohne Normdaten-Block aus einem Index der DNB-Abzüge, die DBpedia-URI über den englischen Artikel (D65) | Jan: `de.dbpedia.org` antwortet nicht mehr, also `dbpedia.org`; die GND-Abzüge sind freigegeben. Im Dienst tragen 160 statt 139 der 188 richtigen Artikel eine richtige GND, und 96 % der Artikel von `balanced` bekommen eine DBpedia-URI, die antwortet (M42, M43) | ein fünfter Container; zusammen rund 815 MB Download (750 MB Wikipedia-Dumps, 65 MB GND), der Wikidata-Sync rund 10 min; ohne englischen Artikel bleibt die deutsche IRI, die ins Leere führt |
| Lieber leer als falsch | Ein falscher Absatz schadet mehr als ein ehrlich leerer Baustein. | kleine Bausteine bleiben oft leer |
| Lehrpläne aus einem MEM-Vollabzug, keine Abfrage zur Laufzeit | schnell, keine Last und kein Ausfallrisiko beim Anbieter | Inhalte bis zu einem Monat alt; vier Länder |
| Teil 3 zur Anfragezeit aus edu-sharing | aktuell bis auf einen Zwischenspeicher von einer Stunde, kein eigener Datenbestand | hängt an der Erreichbarkeit des Repositorys |
| Kein Rückschreiben | Der Dienst liefert Markdown und JSON, der Aufrufer speichert. | – |

## Die Seiten

1. [Alter und neuer Dienst im Vergleich](01-alt-und-neu.md): die drei Teile im Soll und was der alte und der neue
   Dienst liefern; Güte, Zeit und Kosten in einer Grafik; Zusatzfunktionen; Probleme des alten Dienstes
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
   ihre Schalter und Standardwerte, Güte, Zeit und Tokens mit Grafiken, die vier Profile und ihre Werte je Endpunkt
8. [Entitäten und Kennungen](08-entitaeten-und-kennungen.md): wie `/entities` erkennt, verknüpft und GND, VIAF,
   Wikidata und DBpedia liest, Methoden und Werte je Profil, die Daten im Container und was nicht gebaut ist
9. [Methoden, Messwerte und Profile](09-methoden-und-profile.md): die vier Profile mit ihren Methoden als Grafik und
   Tabelle; je Schritt (Artikelwahl, Korpus, Zuordnung, Text, Lehrplanschnipsel, QA-Paare, Entitäten) die gemessenen
   Methoden mit Güte, Zeit und Tokens und warum welches Profil welche nutzt; Kosten je Profil und Endpunkt (M45)

Die Seiten sind als Baum für Confluence gedacht: diese Übersicht als Elternseite, die neun übrigen darunter. Die
Links zwischen ihnen zeigen auf die Markdown-Dateien und müssen nach dem Import auf die Confluence-Seiten umgestellt
werden. Die Grafiken liegen als SVG unter `docs/entwicklung/bilder/` und kommen beim Import als Anhänge mit. Die
Messskripte bleiben im Repository unter `docs/entwicklung/messung/`.

Für die Präsentation gibt es die Seiten 01, 09 und 07 auch als eine HTML-Seite: [praesentation.html](praesentation.html),
mit Inhaltsverzeichnis und allen Grafiken eingebettet. Sie braucht keine weiteren Dateien und öffnet sich nach dem
Herunterladen in jedem Browser; GitHub selbst zeigt nur ihren Quelltext. `messung/mc_praesentation.py` erzeugt sie
neu, nachdem sich eine der drei Seiten oder eine Grafik geändert hat, und nennt den Commit ihrer Quellen.

## Entwicklungsweg

| Zeitraum | Schritt |
|---|---|
| 16.–18.09.2026 | Testapp `kompendium-test`: ZIM-Zugriff, Segmentierung, mehrere Matcher, extraktive Synthese |
| 17.09. | Neubauplan (`PLAN.md`); Fundament, ZIM-Betrieb, Goldstandard, Lehrplan-Cache (Teil 2), Sammlung (Teil 3) |
| 18.09. | LLM-Schicht über die b-api, Audit, Nachschärfung der Zuordnung (Schwelle 0,65, Abschnitts-Glättung) |
| 19.09. | Review-Runden; LLM-Schalter statt fester Modi |
| 20.–22.09. | Umbau: alte v1-Endpunkte entfernt; neue Endpunkte für Wissen, Entitäten und Fragen; Modelle im Image |
| 23.09. | Release v2.0.0, Betrieb auf Hostinger; danach die Artikelwahl gemessen und der LLM-Zuordner als `matcher=llm` eingebaut (D34) |
| 24.09. | Artikelwahl mit den Kontextwörtern des Fachs (M9), Trefferprüfung (M10), Wikibooks und Wikiversity verworfen (M11), günstigere LLM-Zuordnung (D36, M12), Laufzeit der LLM-Schalter (M13); `article_choice=llm` Vorgabe, wo ein LLM konfiguriert ist (D37); `hybrid_light` bleibt Standard (D38); `matcher=llm` ohne Rückfall am Budget (D39, M14); Entscheidungsvorlage mit Grafiken (M15); Standard wieder LLM-frei (D40) und der Schalter `preset` (D41); laya gemessen und nicht eingebaut (M16, D42); der alte Weg über Begriffe vom LLM auf dem Gold (M17); GND-Nummern aus dem Archiv (M18); Kennungen GND, Wikidata und DBpedia im Entitäten-Endpunkt (D43); `gpt-6-luna` als Vorgabemodell (M19, D44); Genitiv beim Verknüpfen der Entitäten (M20, D46); Artikelwahl für echte Materialien (M21), Lehrplanbezüge von Teil 2 (M22) und ein Kompendium aus den Metadaten eines Materials (M23); ein Knoten eines Repositorys als Eingang (D45) |
| 25.09. | Artikel eines Materials ohne LLM (M24) und die eigene Artikelwahl für Materialien (D47); Volltexttreffer ohne Link zum Hauptartikel fallen weg (D48), gemessen mit Knoten-Eingang und QA-Paaren (M25); 422 statt stiller Übergehung (D49); `/matching/compare` entfernt (D50); Fächer nach den Vokabularen von edu-sharing (D51); vier Profile, Standard `balanced`, und das Verfahren der QA-Paare je Profil (D53, D54), gemessen in M27 bis M29 |
| 26.09. | QA-Paare ohne LLM aus dem Parse jedes Satzes, Teil 1 von `/qa` immer ohne LLM (D55, M30); Modellwissen sichtbar gekennzeichnet und nur als Sachaussage (D56, M31); der Standard fragt mit den Regeln, die Stufen `models` und `parse-based` samt Modellen und torch sind entfernt (D57); Lehrplanbezüge je Profil mit gebündelten Überschriften-Treffern, LLM-Prüfung in `best-quality` und Herkunft je Block (D58, M32); 180.000 Tokens je Anfrage für die `best-quality`-Profile, die Lehrplansuche mit Profilen und `/docs` je Endpunkt mit Beispielen bis zu allen Parametern (D59, M33); QA-Paare aufgefüllt und nachgeschärft, keine Fragen als Modellwissen (D60, M34); im Review davon präparierte Texte in linearer Zeit gelesen und vier kleinere Fehler behoben; ein Thema, das auf einen Abschnitt weiterleitet, führt zum Artikel, und die Prüfung sicherer Auflösungen ist am Gold gemessen (M35) und in den `best-quality`-Profilen eingeschaltet (D61); die Verfahren von `/entities` (M36) und Sammel- und Mischthemen wie „deutsche Dichter“ (M37) sind gemessen; `/entities` nimmt Profile, das LLM nennt die Entitäten in `balanced` und den `best-quality`-Profilen (D62); Sammelthemen: `llm-free` bleibt, die neue Frage kommt ab `balanced` (Jan), ohne großes LLM geht sie nicht, ein kleines Modell reicht bei Sammelthemen (M38) |
| 27.09. | Die Frage N ab `balanced`: das LLM nennt Übersicht und Teile jedes Themas (D63), vorher an den Gold-Anfragen geprüft und danach durch den Dienst nachgemessen (M39); kleine lokale Modelle für `llm-free` gemessen, LFM2-700M, LFM2.5-1.2B und Qwen3-0.6B: kein Gewinn, 4,4 bis 6,3 s je Frage (M40), `llm-free` bleibt, wie es ist (Jan); die Kennungen von `/entities` je Profil gemessen (M41), der Wikidata-Index kommt über einen Sidecar in jede neue Installation (D64), GND-Lücke, DBpedia-URIs und DBpedia Spotlight gemessen (M42); der GND-Index und die DBpedia-URI über den englischen Artikel gebaut (D65), der Leser der GND-Abzüge am echten Abzug nachgebessert und alles im Dienst nachgemessen (M43), Methoden und Werte je Profil auf einer eigenen Seite |
| 28.09. | Das Audit vom 27.09. mit 73 Befunden abgearbeitet, Releases 2.1.0 bis 2.2.2; Model2Vec wieder im Image; die Faktoren der Zuordnungsregeln gemessen (M44); alle vier Profile an allen Endpunkten mit Release 2.2.2 nachgemessen (M45); Seite 01 nach den drei Teilen neu gegliedert, Methoden, Messwerte und Profile auf einer eigenen Seite (09) |

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
