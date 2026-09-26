# Bereiche 2 und 3: Lehrpläne und Sammlung

[Übersicht](README.md) · Messaufbau: [Messprotokoll](05-messprotokoll.md), Abschnitt M1

## Teil 2: Lehrplanbezüge

Teil 2 zeigt, was Lehrpläne aller Bildungsstufen zum Thema vorsehen. So wird sichtbar, was man im Lauf eines
Lernlebens zu einem Thema wie Optik lernen kann, von der Grundschule bis zur Oberstufe.

### Quelle: MEM

Maschinenlesbar liegen Lehrpläne heute nur in MEM vor, dem Triplestore der FWU
(`https://sparql.mem.edufeed.org/sparql/`). Er enthält 2.514 Lehrpläne aus vier Ländern: Bayern 1.707, Sachsen
532, Rheinland-Pfalz 229, Berlin 46. Jeder Lehrplan ist ein Baum aus Lernbereichen, Kompetenzen und Inhalten, bis
zu acht Ebenen tief.

### Puffern statt live abfragen

- **Vollabzug.** Ein Sidecar (`lehrplan-updater`) holt alle Lehrpläne per SPARQL in eine SQLite-Datenbank mit
  Volltextindex: 295.184 Knoten, 278 MB, rund 25 Minuten und 2.605 Anfragen. Die neue Datei ersetzt die alte erst,
  wenn sie vollständig ist.
- **Wöchentliche Prüfung.** Der Sidecar vergleicht die Zahl der Lehrpläne je Land mit MEM und holt bei einer
  Änderung, spätestens nach einem Monat, alles neu.
- **Zur Anfragezeit keine Abfrage an MEM.** Eine Themensuche ohne Fachfilter bräuchte Hunderte Anfragen je
  Kompendium, und Abfragen über ganze Teilbäume sprengen den Speicher des MEM-Servers. Der Cache ist schneller,
  belastet den Anbieter nicht und fällt nicht mit ihm aus.
- **Ergebnis:** Teil 2 kostet auf dem Server im Median 240 ms, bei einer Wiederholung 43 ms.

### Suche

1. **Stichwörter:** das Thema, seine Synonyme aus der Artikeleinleitung und die Titel der Unterartikel, die das
   Themenwort tragen, höchstens zwölf. Für Optik: Optik, Lehre vom Licht, Wellenoptik, Technische Optik,
   Geometrische Optik, Mikrooptik, Augenoptiker, Röntgenoptik.
2. **Fachfilter:** Die WLO-Fächer der Sammlung oder des Knotens, alle gleichwertig, oder das Fach der Anfrage werden
   über `config/subjects.yaml` auf die Fachnamen in MEM abgebildet; ein Lehrplan passt, wenn er zu einem davon
   gehört. Weil Sachsen bei vielen Lehrplänen Fächer ohne Namen führt, prüft der Filter auch den Titel des
   Lehrplans.
3. **Wortgrenzen:** Ein Treffer zählt nur, wenn das Stichwort an einer Wortgrenze steht, zuerst im Text des
   Elements, sonst in dem des übergeordneten Elements. Das hält zufällige Treffer mitten in anderen Wörtern fern.
   Am Anfang oder Ende eines längeren Wortes zählt ein Treffer, damit Zusammensetzungen wie „Lichtbrechung“ oder
   „Kernphysik“ bleiben. Seit der Nachschärfung nach M22 (A, `f5d8297`) braucht ein Treffer am Wortende zwei
   Buchstaben davor („Eizelle“ ja, „Herdplatten“ für „Erdplatten“ nein), nach „nicht-“ zählt er nicht, und
   Bindestrich-Teile kommen nur aus dem Thema selbst; andere Bedeutungen kurzer Stichwörter („Solarzelle“) bleiben.
4. **Stufen:** Schulstufe und Klassenstufe kommen aus den Daten; fehlen sie, leitet der Dienst sie aus der
   Jahrgangsstufe oder dem Titel ab und kennzeichnet sie als abgeleitet.
5. **Prüfung durch das LLM (nur `best-quality` und `best-quality-generated`, D58):** Mit `curriculum_check=llm`
   liest das LLM jedes gefundene Element mit seinem Bereich und seinem Lehrplan und bewertet es nach den Noten von
   M22: passt, berührt das Thema, passt nicht. Was nicht passt, fällt heraus; ein Element, das nur seine
   Überschrift zum Thema macht, steht einzeln da, wenn das LLM es passend nennt. Die Elemente gehen in Stapeln zu
   60 parallel an die b-api, auf Budget und Frist der Anfrage - in diesen Profilen 180.000 Tokens (D59); ein
   gescheiterter Stapel behält die Entscheidung der Regeln, und `audit.llm.curriculum_check` sagt, was geprüft,
   verworfen und warum etwas nicht geprüft wurde.

Für Optik fand Teil 2 im Test am 23.09.2026 (lokaler Cache vom 20.09.) 145 Lehrplanelemente in 19 Lehrplänen aus
drei Ländern.

**Die Suche einzeln** (`GET /api/v2/lehrplan/search`, D59): dieselben Schritte ohne Kompendium, zu einem Stichwort
(`mode=keyword`) oder einem Thema (`mode=topic`, aufgelöst wie für Teil 2). `preset` wirkt wie in Teil 2:
`llm-free` und `balanced` finden und bewerten mit den Regeln, `balanced` wählt im Themenmodus den Artikel mit dem
LLM, die `best-quality`-Profile lassen das LLM jedes Element bewerten, alle Treffer und nicht nur die ersten
`limit`. `curriculum_check` lässt sich auch einzeln setzen. Jedes Element nennt Lehrplan, Land, Schulart, Stufe und
Klasse, `matched_in` (Text oder nur Überschrift) und die Note des LLM; `llm` und `llm_tokens` sagen, was das LLM
tat und kostete.

### Darstellung

Teil 2 beginnt mit einem Satz zur Abdeckung und einer Tabelle Land mal Stufe. Danach folgen die Treffer nach Stufe,
Land und Lehrplan; jede Gruppe ist ein Facettenblock. Seine erste Zeile nennt, woher die Schnipsel darunter kommen
(Jan, D58): Lehrplan mit Link, Land, Bildungsstufe, Schulart und Klasse, eine abgeleitete Stufe oder Klasse mit
ihrer Quelle; der Marker trägt dasselbe maschinenlesbar, dazu den Titel des Lehrplans. Elemente, die nur ihre
Überschrift zum Thema macht, stehen als eine Zeile mit ihrer Zahl und einem Link zum Bereich (B aus M22):

```
#### Bayern

[*LehrplanPLUS: Physik Vorklasse (T, ABU)*](https://lp-bavaria.org/…) · Bayern · Sekundarstufe I · Berufsoberschule · Jahrgangsstufe 10
<!-- f: Bundesland=Bayern; Bildungsstufe=Sek I; Klassenstufe=10; Schulart=Berufsoberschule; Lehrplan=https://lp-bavaria.org/…; Lehrplantitel=Physik Vorklasse (T, ABU) -->

**Grundlagen der Optik**

- „konstruieren Strahlengänge durch Sammellinsen, …“ (Kompetenz) · [Lehrplanelement](https://lp-bavaria.org/…)
- *4 weitere Elemente dieses Bereichs; das Thema steht nur in der Überschrift* · [Bereich im Lehrplan](https://lp-bavaria.org/…)
<!-- /f -->
```

Teil 2 wird nicht gekürzt. Ohne Fachangabe werden breite Themen sehr lang: Demokratie ergab zusammen mit Teil 1
318.080 Zeichen, Elektrischer Strom 311.376 (23.09.2026). Mit dem Fach Politik kam Teil 2 für Demokratie am 17.09.
auf rund 161.000 Zeichen. Die Fächer der Sammlung oder des Knotens, das Fach der Anfrage und eine einstellbare
Obergrenze je Land halten den Teil kürzer.

### Grenzen

- Vier Länder; weitere kommen hinzu, sobald MEM sie veröffentlicht. Der Text sagt, welche Länder erfasst sind.
- Inhaltliche Änderungen kommen spätestens nach einem Monat an; neue oder wegfallende Lehrpläne fallen durch die
  wöchentliche Zählung früher auf.
- Die MEM-Daten sind frei nutzbar: Die FWU stellt den Zugang offen bereit (github.com/FWU-DE/mem-mcp), Jan hat die
  Nutzung am 26.09.2026 ohne Einschränkung freigegeben (D58). Laut mem-mcp führt MEM inzwischen auch Brandenburg;
  der Abzug fragt alle 16 Länder und holt es mit dem nächsten Lauf.
- Treffsicherheit (M22, M32): Vor D58 gehörten rund 60 % der Elemente zum Thema, 11 bis 19 % passten nicht. Mit
  gebündelten Überschriften-Treffern sind von den einzeln gezeigten 70 bis 72 % passend ohne Fach und 77 bis 81 % mit
  Fach, 5 bis 9 % nicht; ein Viertel der passenden steht dann nur in der Bündelzeile. Die LLM-Prüfung zeigt 74 bis
  79 % passende, 5 bis 9 % unpassende und verwirft kein passendes Element, für im Median rund 8.000 bis 10.000
  Tokens und 6 s je Anfrage. Mit den 180.000 Tokens von D59 prüft sie beim breitesten Thema (Demokratie ohne Fach,
  819 Elemente) alle Elemente, auch im Kompendium neben der Zuordnung von 382 Absätzen und dem Schreiben
  (M33). Das Fach kürzt
  Teil 2 und verwirft auch passende Elemente aus beruflichen Lehrplänen, dem Sachunterricht und Nachbarfächern.

## Teil 3: Sammlungsüberblick

Teil 3 fasst zusammen, was die WLO-Sammlung zum Thema enthält: für Menschen als Überblick, für Maschinen als Liste
von Knoten mit nodeId.

### Inhalt

- **Kopf der Sammlung:** Titel mit Link, Fach, Bildungsstufe, Art der Sammlung, Stand, nodeId; die Beschreibung wie
  hinterlegt; eine Zeile Kennzahlen (Inhalte, Untersammlungen, Materialtypen, Bildungsstufen, Fächer, Lizenzen).
- **Inhalte:** je Inhalt eine Zeile mit Titel und Link, erstem Satz der Beschreibung, bis zu fünf Schlagwörtern,
  Materialtyp, Bildungsstufe, Lizenz und nodeId.
- **Untersammlungen** (eine Ebene tief) mit ihren Inhalten, eingerückt.

```
- Inhalt: [**Suchgitter Optik**](https://www.tutory.de/…) · Finde alle optischen Begriffe in diesem Suchgitter zum Thema Optik. · Schlagwörter: Optik, Rätsel, Suchgitter · Arbeitsblatt · Material · Sekundarstufe I · CC BY-SA 4.0 · nodeId: fa68de48-7ef3-4970-942e-e2668e3eb7b7
```

Jede Knotenzeile passt auf den regulären Ausdruck
`^( *)- (Sammlung|Untersammlung|Inhalt): (.*) · nodeId: ([0-9a-f-]{36})$`. Die Sammlung Optik ergab am 23.09.2026
233 solche Zeilen. Werte aus dem Repository können weder eine Knotenzeile noch einen Facettenblock vortäuschen: Zeilenumbrüche
werden zusammengefasst, `<!--` entschärft und Sonderzeichen in Markern kodiert.

### Entstehung und Tempo

Teil 3 entsteht zur Anfragezeit aus edu-sharing: Sammlung, Untersammlungen und Inhalte werden anonym gelesen,
seitenweise und innerhalb der Frist der Anfrage. Reicht die Frist nicht, ist der Teil als unvollständig markiert.
Zwischengespeichert werden Sammlungen eine Stunde, Materialtexte sieben Tage. Auf dem Server kostet Teil 3 allein
aus dem Zwischenspeicher höchstens 0,16 s und beim ersten Abruf bis zu 3,5 s; ein Kompendium mit allen drei Teilen
dauerte 1,3 bis 5,5 s.

### Wissens-Sammlung

Optional kann eine zweite Sammlung (`knowledge_collection_id`) Material als zusätzliche Quelle für Teil 1 liefern.
Wörtlich übernommen werden nur Materialien unter CC0, Public Domain, CC BY oder CC BY-SA, höchstens 30 Materialien
mit je 20.000 Zeichen. Im Release 2.0.0 erreichten nur die Kurzbeschreibungen der Materialien Teil 1, ihre Texte
wurden als Literaturangaben einsortiert. Behoben am 23.09.2026 in Commit `8955312`, noch in keinem Release.

## Vorschlag: Teil 3 live

**Heute** entsteht Teil 3 beim Erzeugen frisch, bis auf den Zwischenspeicher von einer Stunde, und wird vom
Aufrufer zusammen mit dem Kompendium gespeichert. Ändert sich die Sammlung, veraltet der gespeicherte Überblick:
Neue Inhalte fehlen, gelöschte stehen noch drin.

**Vorschlag:**

1. **Kompendium ohne Teil 3 speichern** (`parts: ["world", "curricula"]`). Teil 1 und 2 ändern sich selten und
   können redaktionell geprüft und eingefroren werden.
2. **Teil 3 beim Anzeigen holen.** Das WLO-Frontend oder ein KI-Werkzeug ruft
   `GET /api/v2/collections/{id}/overview` auf (0,16 s aus dem Zwischenspeicher, bis rund 3,5 s beim ersten Abruf)
   und setzt den Teil an seine Stelle. Alternativ zeigt das Frontend die Sammlung ohnehin aus edu-sharing an, dann
   dient der Markdown-Teil 3 nur Sprachmodellen und Suchdiensten.
3. **Zwischenspeicher nach Änderungsdatum** der Sammlung statt nach fester Zeit, damit ein Überblick sofort nach
   einer Änderung neu entsteht und sonst aus dem Speicher kommt.

| Für | Gegen |
|---|---|
| aktuell bis auf den Zwischenspeicher | beim Anzeigen hängt Teil 3 am Dienst und an edu-sharing; Rückfall: der zuletzt geholte Stand |
| Prüfung von Teil 1 und 2 bleibt gültig, wenn sich die Sammlung ändert | Teil 3 ist nicht Teil des geprüften, eingefrorenen Dokuments |
| keine Neuerzeugung des ganzen Kompendiums nötig | ein weiterer Aufruf beim Anzeigen |

## Braucht es spezielle Tags und Strukturen?

Ja, aber wenige, und die meisten gibt es schon:

| Struktur | Zweck | Stand |
|---|---|---|
| YAML-Vorspann | Thema, Teile, Verfahren, Archivstände, KI-Kennzeichnung nach Art. 50 AI Act, Prüfstatus | vorhanden |
| `<!-- kompendium:section id=… status=… facets=… hash=… -->` | Bausteine von Teil 1 erkennen, Prüfstatus tragen, Änderungen am Hash sehen | vorhanden |
| `<!-- f: Name=Wert; … -->` bis `<!-- /f -->` | Facettenblöcke: Bundesland, Stufe, Lehrplan, Sammlung | vorhanden |
| Knotenzeile `- Art: … · nodeId: <id>` | Sammlungen und Inhalte maschinell lesen | vorhanden |
| Klammer um jeden Teil, etwa `<!-- kompendium:part id=collection collection=<nodeId> -->` bis `<!-- /kompendium:part -->` | Teil 3 ersetzen oder live einsetzen, ohne Überschriften zu parsen | Vorschlag |
| `collection_id` und Stand der Sammlung im Vorspann | erkennen, ob der gespeicherte Teil 3 veraltet ist | Vorschlag |
| Knotenliste im JSON der Antwort | Frontends rendern Teil 3 ohne Markdown-Parser; heute enthält das JSON nur Kennzahlen | Vorschlag |

**Grundsätze dafür:**

- **HTML-Kommentare als Marker.** CommonMark-Ansichten wie GitHub zeigen sie nicht an; ein Leser sieht nur den
  Text. Ob eine bestimmte Oberfläche sie ebenso ausblendet, ist vor dem Einsatz dort zu prüfen.
- **Eine Zeile je Knoten statt Zaunblöcken.** Die Zaun-Syntax `::: wlo-material` aus anderen WLO-Projekten war
  erprobt und wurde wieder verworfen. `:::` ist kein CommonMark, viele Ansichten zeigen die Zäune als Text, und
  zeilenweise Begrenzer in Redaktionstext lassen sich leicht vortäuschen oder brechen.
- **Jeder Wert auf einer Zeile, Sonderzeichen kodiert.** So bleibt das Parsen ein einfacher regulärer Ausdruck je
  Zeile.
