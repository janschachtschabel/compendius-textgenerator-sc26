# Zuordnung zu den SC26-Bausteinen

[Übersicht](README.md) · Messaufbau: [Messprotokoll](05-messprotokoll.md), Abschnitte M4 bis M6 und M12 bis M14

## Die Aufgabe

Der Korpus eines Themas besteht aus einigen Dutzend bis 400 Absätzen aus bis zu zwölf Artikeln. Jeder Absatz soll
höchstens einem Baustein des SC26-Templates zugeordnet werden oder keinem. Zehn der 13 Bausteine werden so gefüllt,
drei erzeugt der Dienst selbst:

| Nr. | Baustein | Füllung |
|---|---|---|
| 1 | Themendefinition | zugeordnet; die Einleitung des Hauptartikels gehört immer hierher |
| 2 | Gliederung & Systematik | zugeordnet |
| 3 | Fachinhalte | zugeordnet; zugleich Standardbaustein für themennahe Absätze ohne sichere Zuordnung |
| 4 | Gesellschaftlicher Kontext | zugeordnet |
| 5 | Entwicklung & Ausblick | zugeordnet |
| 6 | Akteure | erzeugt: Personen, Organisationen, Vorhaben aus den Artikeln |
| 7 | Beruf & Wirtschaft | zugeordnet |
| 8 | Bildung | zugeordnet |
| 9 | Regularien & Rahmensetzung | zugeordnet |
| 10 | Praxis | zugeordnet |
| 11 | Querschnitt & Bezüge | zugeordnet |
| 12 | Quellen | erzeugt: Quellenangaben, Belegstellen, weiterführende Literatur |
| 13 | Glossar | erzeugt: erster definierender Satz der Artikel |

Jeder Baustein hat im Template eine Beschreibung, was hineingehört und was nicht, Suchbegriffe, zulässige Facetten
und ein Längenbudget.

## Verfahren im neuen Dienst

Die Zuordnung läuft in drei Stufen:

1. **Überschriften-Lexikon.** Muster für Abschnittsüberschriften je Baustein, gewonnen aus den Überschriften von
   20.000 zufälligen Wikipedia-Artikeln; die häufigsten 1.000 decken 74 % aller Vorkommen ab. „Geschichte“ zeigt
   etwa auf Entwicklung & Ausblick.
2. **Ranker.** Sie vergleichen jeden Absatz mit einer Beschreibung des Bausteins (Titel, Beschreibung, Inhalte,
   Unterpunkte, Suchbegriffe):
   - **BM25** gewichtet gemeinsame Wörter.
   - **Zeichen-TF-IDF** vergleicht Zeichenfolgen von drei bis fünf Buchstaben und erfasst so zusammengesetzte
     Wörter („Lichtbrechung“ und „Brechung“).
   - **Model2Vec** vergleicht Bedeutungen über statische Wortvektoren (`m2v-gte-256-edu`, 256 Dimensionen, 321 MB,
     läuft auf der CPU).
   Die Werte werden gewichtet gemittelt. Einigkeit mehrerer Ranker gibt einen Bonus, und Absätze desselben
   Abschnitts werden zur Hälfte an den Abschnittsmittelwert angeglichen.
3. **Policy.** Feste Regeln machen aus den Werten eine Entscheidung:
   - Einleitungen gehören in Themendefinition, Einleitungen von Unterartikeln in Gliederung & Systematik.
   - Ein Lexikontreffer zählt mindestens 0,9.
   - Wörter aus der Abgrenzung eines Bausteins senken den Wert.
   - Sicher ist eine Zuordnung erst ab 0,65.
   - Unsichere, aber themennahe Absätze gehen in den Standardbaustein Fachinhalte. Themenferne bleiben draußen:
     lieber ein leerer Baustein als ein falscher Absatz.
   - Längenbudgets begrenzen jeden Baustein.

Wählbar sind vier lokale Strategien mit derselben Policy: `hybrid_light` (Standard: Lexikon, BM25, Zeichen-TF-IDF und
Model2Vec), `bm25`, `char_tfidf` und `lexicon_only`. Seit D34, nach v2.0.0, kommt `matcher=llm` hinzu: Ein
Sprachmodell ordnet die Absätze zu, die Standard-Strategie bleibt der Rückfall (siehe unten). Dazu kommt der Schalter
`extraction=llm`, bei dem ein Sprachmodell aus den besten Kandidaten je Baustein die Sätze wählt. Im laufenden Dienst
ist Model2Vec aktiv: Der Server meldet unter `/health` für `hybrid_light` die Bestandteile `bm25`, `char_tfidf` und
`model2vec` (`"embeddings": true`); dort erscheinen nur Bestandteile, die tatsächlich geladen sind.

### Welche Daten in die Zuordnung eingehen

Die Ranker vergleichen nicht nur Überschriften, sondern **Überschriftenpfad und Text** jedes Absatzes. Nur das
Lexikon schaut allein auf die Überschriften.

| Datum | Wofür | Code |
|---|---|---|
| Überschriftenpfad des Absatzes, etwa „Teilbereiche der Optik > Wellenoptik“; ohne Artikeltitel, bei der Einleitung „Einleitung“ | Lexikon; zusammen mit dem Text Eingabe der Ranker; die ersten zwei Ebenen bilden den Abschnitt für die Glättung | `app/matching/lexicon.py`, `app/matching/base.py` |
| Text des Absatzes (ganzer Absatz, eine Liste oder Tabelle als Einheit) | Eingabe der Ranker; Suche nach Abgrenzungswörtern | `chunk_representation` in `app/matching/base.py` |
| Baustein: Titel, Beschreibung, „gehört hinein“, Unterpunkte, Suchbegriffe | Anfrage, gegen die die Ranker jeden Absatz vergleichen | `slot_representation` in `app/matching/base.py` |
| Baustein: „gehört nicht hinein“ (Abgrenzung) | nur als Abwertung in der Policy, nie Teil der Anfrage der Ranker | `app/matching/policy.py` |
| Rolle der Quelle: Hauptartikel, dasselbe Thema aus Klexikon, Unterartikel, Personen- oder Werkartikel | Regeln der Policy | `app/matching/policy.py` |
| Stellung im Artikel: Einleitung, erster Absatz unter einer Zwischenüberschrift | Regeln der Policy | `app/matching/policy.py` |
| Projekt der Quelle (Wikipedia, Klexikon, …) | bevorzugte Quellen je Baustein | `app/matching/policy.py` |

### Wie die Kandidaten zusammengeführt werden

Ein eigenes Reranking mit einem weiteren Modell gibt es nicht. Die Kandidaten werden über ihre Werte zusammengeführt
und dann nach Regeln neu bewertet:

1. **Kandidaten je Ranker.** BM25, Zeichen-TF-IDF und Model2Vec bewerten jeden Absatz gegen jeden Baustein. Jeder
   Ranker teilt seine Werte durch seinen besten Wert im ganzen Lauf und gibt je Baustein seine 15 besten Kandidaten
   weiter; Model2Vec nur solche mit einer Kosinus-Ähnlichkeit über 0,1.
2. **Zusammenführen.** Die Kandidaten aller Ranker werden vereinigt und ihre Werte gewichtet gemittelt: BM25 1,0,
   Zeichen-TF-IDF 0,7, Model2Vec 1,0. Ein Ranker, der einen Absatz nicht unter seinen 15 hat, zählt dabei mit 0.
   Jeder weitere Ranker, der denselben Absatz nennt, gibt 10 % Bonus. Danach wird auf den besten Wert 1,0 normiert.
   Verrechnet werden die Werte, nicht nur die Ränge: Bei einem reinen Rangverfahren (RRF) stünde ein Absatz, der über
   ein einziges schwaches Wort auf Platz 1 kommt, gleichauf mit einem, der über viele starke Wörter dorthin kommt.
   Weil die Werte über den ganzen Lauf normiert sind, bleibt zudem sichtbar, wenn zu einem Baustein nichts gut passt.
3. **Glättung.** Jeder Wert wird zur Hälfte an den Mittelwert seines Abschnitts angeglichen.
4. **Neubewertung durch die Policy** mit den Regeln oben. Danach kommt jeder Absatz nur in den Baustein, in dem er
   am höchsten liegt. Sicher ist die Zuordnung ab 0,65; Längenbudgets begrenzen jeden Baustein.

Ob ein Cross-Encoder als echtes Reranking der Kandidaten hilft, zeigt die Messung unten.

## Verfahren der Testapp

Die Testapp `kompendium-test` bietet zehn Matcher:

| Matcher | Prinzip | Modell |
|---|---|---|
| `model2vec` | statische Wortvektoren; Standard der Testapp | `m2v-gte-256-edu` |
| `bm25_static` | BM25 und Model2Vec kombiniert | `m2v-gte-256-edu` |
| `bm25` | gemeinsame Wörter | – |
| `char_tfidf` | Zeichenfolgen | – |
| `e5_onnx` | Satzvektoren; trotz des Namens weder E5 noch ONNX | `paraphrase-multilingual-MiniLM-L12-v2` |
| `cross_encoder` | ein Modell bewertet jedes Paar aus Baustein und Absatz | `msmarco-MiniLM-L6-en-de-v1` |
| `m2v_cross_encoder` | Model2Vec wählt Kandidaten, der Cross-Encoder sortiert neu | beide |
| `extractive_qa` | eine Frage je Baustein, ein Frage-Antwort-Modell sucht die Antwort im Absatz | MiniLM-L12, `electra-base-de-squad2` |
| `hybrid_ensemble` | BM25, Zeichen und Model2Vec vereint, dann Cross-Encoder und Frage-Antwort-Modell | mehrere |
| `llm_router` | ein Sprachmodell ordnet zu | über die b-api |

Die Testapp arbeitet in einem anderen Ablauf:

- Jeder Matcher nimmt je Baustein die zwei bis drei besten Absätze und füllt damit fast jeden Baustein, auch wenn
  nichts richtig passt.
- Absätze bekommen einen Bonus, wenn ihre Überschriften-Kategorie zum Baustein passt.
- In die Bausteinbeschreibung fließen auch die Abgrenzungen ein, sodass ein Vektormodell Absätze zu ausgeschlossenen
  Themen eher für passend hält.

Ihre eigenen Kennzahlen stammen aus einer Metrik, die genau diese Kategorien prüft. Mit dem Dienst sind sie nicht
vergleichbar und stehen nicht in dieser Dokumentation. Für den Vergleich unten wurden stattdessen die **Modelle** der
Testapp in den Ablauf des Dienstes eingesetzt: Model2Vec, die MiniLM-Satzvektoren hinter `e5_onnx`, der Cross-Encoder
und das Frage-Antwort-Modell. Sie sehen dieselben Absätze und dieselbe Bausteinbeschreibung, laufen durch dieselbe
Zusammenführung, Glättung und Policy und werden gegen denselben Goldstandard gemessen. Statt des `llm_router` wurde
ein eigener LLM-Zuordner mit `gpt-5.6-luna` gemessen; er ist als `matcher=llm` in den Dienst übernommen.

## Maßstab: der Goldstandard

Alle Verfahren werden auf denselben Daten gemessen: dem Goldstandard des Dienstes. Er umfasst zehn Themen aus zehn
Fächern. Für ausgewählte Absätze, 603 der 1.632 Absätze im heutigen Korpus, ist ein Soll-Baustein oder „keiner“
festgelegt; weitere 40 Labels passen zu keinem heutigen Absatz mehr. Gemessen werden:

- **macro-F1:** Mittel der F1-Werte über die Bausteine, jeder Baustein zählt gleich.
- **micro-F1:** über alle gelabelten Absätze.
- **richtig unter Top 2:** Anteil richtig sitzender Absätze unter den zwei besten je Baustein, also das, was im
  Text ganz vorn stünde.
- **belegte Bausteine:** wie viele der zehn Inhaltsbausteine überhaupt etwas bekommen.

Einschränkungen: Die Labels hat Claude mit Blick auf die Vorschläge der Policy vorgeschlagen und Zeile für Zeile
gelesen; eine Redaktion hat sie noch nicht geprüft. Die Policy wurde an diesem Gold abgestimmt, das Gold begünstigt
sie.

Als **Gegenprobe** bewertet ein blinder LLM-Richter (`gpt-5.6-luna`) auf vier anderen Themen, an denen nichts
abgestimmt wurde, die zwei besten Absätze je Baustein, ohne das Verfahren zu kennen. Das sind andere Daten als der
Goldstandard und kleine Stichproben (38 bis 49 Absätze je Verfahren); Unterschiede unter rund zehn Prozentpunkten
sind nicht belastbar. Für den LLM-Zuordner entfällt die Gegenprobe, weil Richter und Zuordner dasselbe Modell wären.

## Ergebnisse (23. und 24.09.2026)

M4 bis M6 liefen mit dem Code-Stand 2.0.0, M12 und M13 mit dem Stand nach D36, M14 mit D39. Die Rohdaten und lesbare
Zusammenfassungen liegen in `messung/ergebnisse/` (Übersicht dort in der README).

### Auf einen Blick: die wählbaren Verfahren

Güte am Goldstandard, Zeit auf dem Entwicklungsrechner, für die fünf Werte von `matcher`:

| `matcher` | macro-F1, gelabelte Absätze | macro-F1, alle Absätze | Zuordnung je Thema | Teil 1 je Kompendium | Tokens je Kompendium |
|---|---|---|---|---|---|
| `llm` (D36, D39) | 0,72 und 0,69 (zwei Läufe) | nicht gemessen | 10,8 s (M13), 22,2 s (M14) | 12,0 s (M13), 22,7 s (M14) | im Mittel 34.500 (18.800 bis 45.900) |
| **`hybrid_light` (Standard)** | 0,43 | 0,45 | 0,30 s | 1,20 s | 0 |
| `char_tfidf` | 0,40 | 0,42 | 0,25 s | – | 0 |
| `bm25` | 0,36 | 0,37 | 0,03 s | – | 0 |
| `lexicon_only` | 0,35 | 0,35 | 0,02 s | – | 0 |

- **Zuordnung je Thema:** Die lokalen Verfahren sind im Mittel über die zehn Goldthemen mit allen Absätzen gemessen
  (M4). Für `llm` gilt der Median über fünf ganze Kompendien, vor D39 (M13) und mit D39 an fünf anderen Themen (M14);
  `hybrid_light` brauchte dort 0,27 und 0,51 s. In M14 antwortete die b-api langsamer: Themen mit drei Stapeln, die
  nie warten, brauchten 15 bis 17 s statt 11 bis 12 s; Themen ab fünf Stapeln warten seit D39 auf eine zweite Runde
  (22 bis 25 s).
- **Teil 1 je Kompendium:** Median über dieselben fünf Kompendien (M13, M14). Ohne die Zuordnung dauert Teil 1 rund
  0,9 s. Die übrigen lokalen Verfahren liegen deshalb knapp unter `hybrid_light`; eigens gemessen wurden sie nicht.
- **Tokens bei `llm`:** Budget 60.000 Tokens je Anfrage. Vor D39 fielen bei drei der fünf Themen die letzten Stapel
  auf `hybrid_light` zurück, zusammen 18 % der Absätze, im Mittel 29.400 Tokens (M13). Seit D39 warten diese Stapel;
  in M14 entschied das LLM alle 1.005 Absätze, im Mittel 34.500 Tokens je Kompendium, rund 172 je Absatz.
- **Abwägung:** `llm` ordnet klar besser zu (113 statt 201 Fehlzuordnungen auf denselben Absätzen), braucht für
  Teil 1 aber zehnmal so lange und je Kompendium mehr Tokens als der ganze alte Dienst. `hybrid_light` bleibt
  deshalb Standard, `llm` ist je Anfrage wählbar (D38).

### Alle Verfahren im Ablauf des Dienstes

Goldstandard, voller Kandidatenpool: alle 1.632 Absätze der zehn Themen. Jedes Verfahren läuft durch dieselbe
Zusammenführung, Glättung und Policy.

| Verfahren | macro-F1 | micro-F1 | richtig unter Top 2 | belegte Bausteine (von 10) | Rechenzeit je Thema |
|---|---|---|---|---|---|
| nur Überschriften-Lexikon (`lexicon_only`) | 0,35 | 0,65 | 64 % | 5,1 | 0,02 s |
| BM25 (`bm25`) | 0,37 | 0,65 | 62 % | 5,6 | 0,03 s |
| Zeichen-TF-IDF (`char_tfidf`) | 0,42 | 0,64 | 56 % | 7,1 | 0,25 s |
| Model2Vec allein | 0,45 | 0,62 | 54 % | 7,3 | 0,04 s |
| MiniLM-Satzvektoren allein (Modell aus `e5_onnx`) | 0,37 | 0,60 | 48 % | 7,3 | 4,1 s |
| Cross-Encoder allein (Modell der Testapp) | 0,30 | 0,53 | 36 % | 8,8 | 73,3 s |
| Frage-Antwort-Modell (wie `extractive_qa`, MiniLM-Kandidaten) | 0,38 | 0,65 | 56 % | 6,1 | 29,8 s |
| BM25 + Model2Vec | 0,44 | 0,65 | 63 % | 5,9 | 0,05 s |
| `hybrid_light` ohne Model2Vec (BM25 + Zeichen-TF-IDF) | 0,39 | 0,65 | 61 % | 6,0 | 0,26 s |
| **`hybrid_light` + Model2Vec (Standard)** | 0,45 | 0,66 | 67 % | 6,0 | 0,30 s |
| Standard, Kandidaten vom Cross-Encoder umsortiert | 0,35 | 0,51 | 38 % | 8,6 | 14,9 s |
| Standard + Cross-Encoder als vierter Ranker | 0,37 | 0,64 | 58 % | 6,5 | 73,6 s |

Rechenzeit: Zuordnung je Thema auf einem Entwicklungsrechner, nur CPU.

- **Ranker des Dienstes:** Mittelwert über die zehn Themen, mit Aufwärmlauf.
- **Modelle der Testapp:** Median der Zeit, mit der sie ihre Paare aus Baustein und Absatz bewerten. Der
  Cross-Encoder bewertet alle Paare, das Frage-Antwort-Modell nur die 15 besten MiniLM-Kandidaten je Baustein. Über
  alle Paare brauchte das Frage-Antwort-Modell für ein einziges Thema 746 s.
- **Umsortieren:** der Standard plus 46,8 ms je Kandidatenpaar, im Median rund 310 Paare je Thema.

### LLM als Zuordner (`matcher=llm`)

Ein Sprachmodell, `gpt-5.6-luna`, bekommt die Bausteine mit Beschreibung, „gehört hinein“ und „gehört nicht hinein“,
dazu die Zuordnungsregeln aus dem Template; sie entsprechen den Labelregeln des Goldstandards. Je Absatz sieht es den
Artikel und dessen Rolle, den Überschriftenpfad und den Text, gekürzt auf 700 Zeichen, 25 Absätze je Aufruf; seit
D36 sind es 400 Zeichen und 50 Absätze. Es antwortet je Absatz mit einem Baustein oder „keiner“ und einer Sicherheit.
Gemessen wurde zweimal auf denselben 603 gelabelten Absätzen: zuerst mit einem Skript, dann im Dienst als
`matcher=llm` über `CompendiumService.match` (D34). Die Tabelle zeigt alle Verfahren auf diesen Absätzen; die Zeilen
für D36 stammen aus M12 und liefen auf 597 davon, weil sich ein Korpus seitdem geändert hat (Sperrliste, M10):

| Verfahren | macro-F1 | micro-F1 | richtig unter Top 2 | falsch zugeordnet | Tokens, zehn Themen | Zeit je Thema |
|---|---|---|---|---|---|---|
| **`matcher=llm`, 50 Absätze zu 400 Zeichen je Aufruf (D36, M12, zwei Läufe)** | **0,72 und 0,69** | **0,82 und 0,82** | nicht gemessen | 113 von 550 in beiden | 105.727 und 103.368 | 9,2 und 7,2 s |
| `matcher=llm`, 25 Absätze zu 700 Zeichen (M12, zweiter Lauf mit anderen Stapeln) | 0,73 | 0,83 | nicht gemessen | 110 von 550 | 144.758 | 7,8 s |
| `matcher=llm` im Dienst, 25 Absätze zu 700 Zeichen | 0,66 | 0,79 | 75 % | 125 von 547 | 144.486 | Zwischenspeicher |
| `gpt-5.6-luna`, erste Messung mit Skript | 0,63 | 0,79 | 73 % | 128 von 547 | 144.596 | 7,5 s |
| nur Überschriften-Lexikon (`lexicon_only`) | 0,35 | 0,65 | 63 % | 184 von 518 | 0 | 0,01 s |
| BM25 (`bm25`) | 0,36 | 0,63 | 60 % | 203 von 536 | 0 | 0,01 s |
| Zeichen-TF-IDF (`char_tfidf`) | 0,40 | 0,61 | 51 % | 223 von 551 | 0 | 0,09 s |
| Model2Vec allein | 0,41 | 0,57 | 43 % | 260 von 566 | 0 | 0,02 s |
| MiniLM-Satzvektoren allein (Modell aus `e5_onnx`) | 0,37 | 0,57 | 42 % | 254 von 562 | 0 | – |
| Cross-Encoder allein (Modell der Testapp) | 0,29 | 0,45 | 31 % | 327 von 570 | 0 | – |
| Frage-Antwort-Modell (wie `extractive_qa`, MiniLM-Kandidaten) | 0,37 | 0,64 | 54 % | 196 von 531 | 0 | – |
| BM25 + Model2Vec | 0,43 | 0,64 | 58 % | 208 von 546 | 0 | 0,02 s |
| `hybrid_light` ohne Model2Vec (BM25 + Zeichen-TF-IDF) | 0,38 | 0,63 | 57 % | 207 von 543 | 0 | 0,11 s |
| **`hybrid_light` + Model2Vec (Standard)** | 0,43 | 0,64 | 61 % | 205 von 546 | 0 | 0,11 s |
| Standard, Kandidaten vom Cross-Encoder umsortiert | 0,32 | 0,43 | 35 % | 345 von 584 | 0 | – |
| Standard + Cross-Encoder als vierter Ranker | 0,36 | 0,63 | 53 % | 214 von 546 | 0 | – |

- **Zwei Läufe:** Der Prompt im Dienst ist Zeichen für Zeichen der des ersten Laufs. Für acht Themen beantwortete
  die b-api die wortgleichen Aufrufe aus ihrem Zwischenspeicher. In Optik und Sinfonie antwortete das Modell neu:
  Der Dienst hält dort je einen Absatz für das Akteursverzeichnis zurück, wie die Policy auch, dadurch verschieben
  sich die Stapel. In diesen beiden Themen wichen 17 von 154 Entscheidungen vom ersten Lauf ab. Die Streuung des
  Modells ist damit nur an zwei Themen gemessen.
- **Top 2:** „Richtig unter Top 2“ zählt im Dienst wie bei allen anderen Verfahren nach den Längenbudgets. Der erste
  Lauf kannte keine Budgets.
- **Zeit je Thema:** Wandzeit der Zuordnung für die rund 60 gelabelten Absätze eines Themas, im Mittel über die zehn
  Themen; beim LLM laufen vier Aufrufe parallel. Für ein ganzes Kompendium gelten die Werte aus M13 oben. Die Modelle
  der Testapp bewerten ihre Paare vorab, ihre Zeit ist nur für alle Absätze gemessen (Tabelle davor). Der Lauf im
  Dienst kam für acht Themen aus dem Zwischenspeicher der b-api; seine Zeit ist keine Modellzeit.
- **Kosten:** 144.486 Tokens für 601 Absätze laut b-api, rund 240 je Absatz. Im ersten Lauf dauerte ein Aufruf im
  Median 5,5 s, ein Thema 7,5 s. Mit 50 Absätzen zu 400 Zeichen (D36) sind es 105.727 Tokens für 597 Absätze, rund
  177 je Absatz.
- **Ganzes Kompendium (M13):** Fünf Themen ohne Zwischenspeicher brauchten mit D36 je Kompendium 19.000 bis 38.000
  Tokens, im Mittel 29.400, und Teil 1 dauerte im Median 12,0 statt 1,2 s; die Zuordnung selbst 10,8 statt 0,3 s.
  Das ist mehr als der ganze alte Dienst mit rund 7.900 Tokens. Je Anfrage erlaubt der Dienst 60.000 Tokens
  (`LLM_MAX_TOKENS_PER_REQUEST`), und das reicht bei großen Themen nicht: Jeder Stapel reserviert vorab rund 13.000
  Tokens und verbraucht rund 8.000, parallele Stapel erschöpfen das Budget, bevor die ersten abrechnen. Bei 3 von 5
  Themen blieben so die letzten ein bis zwei Stapel bei der Standard-Strategie, 18 % der Absätze. Mit 171 Tokens je
  entschiedenem Absatz kostet ein Kompendium, dessen Absätze das LLM alle entscheidet, hochgerechnet rund 36.000
  Tokens. Seit D39 warten solche Stapel, bis laufende abgerechnet sind.
- **Ohne Rückfall (D39, M14):** An fünf neuen Themen mit 1.005 Absätzen entschied das LLM alle Absätze; ohne Warten
  wären 151 zurückgefallen (nachgerechnet mit `mc_budget_nachrechnung.py`, die für M13 genau die 194 ergibt). Ein
  Kompendium kostete im Mittel 34.500 Tokens (18.800 bis 45.900), rund 172 je Absatz. Teil 1 dauerte im Median 22,7 s:
  Die b-api antwortete langsamer als in M13, und Themen ab fünf Stapeln warten auf eine zweite Runde, 22 bis 25 s für
  die Zuordnung statt 15 bis 17 s bei drei Stapeln im selben Lauf. Ein höheres Budget spart die zweite Runde.
- **Größere Stapel, kürzere Texte (D36, M12):** Im ersten Lauf ordneten 50 Absätze zu 400 Zeichen in jedem Baustein
  mindestens so gut zu wie 25 zu 700. Ein zweiter Lauf mit gedrehter Reihenfolge, also anderen Stapeln und ohne
  Zwischenspeicher, drehte das Ergebnis um (0,69 gegen 0,73). Die großen Bausteine bleiben zwischen den Läufen stabil
  (Fachinhalte 0,84 bis 0,86), die kleinen springen um bis zu 0,4 (Praxis 0,34 bis 0,73). Gleich gut also, aber 27
  bis 29 % billiger; deshalb gilt 50 und 400.
- **Vorbehalt:** Die Goldlabels hat ebenfalls ein Sprachmodell vorgeschlagen, Claude. Ein LLM als Zuordner teilt
  womöglich dessen Sicht, und es kennt die Labelregeln. Die Gegenprobe mit dem Richter entfällt, weil Richter und
  Zuordner dasselbe Modell wären.

### Gegenprobe: blinder Richter auf vier anderen Themen

| Verfahren | bewertete Absätze | klar | falsch | belegte Bausteine (von 10) |
|---|---|---|---|---|
| **Standard** | 39 | 62 % | 28 % | 5,5 |
| BM25 + Model2Vec | 39 | 62 % | 26 % | 5,3 |
| `hybrid_light` ohne Model2Vec | 38 | 63 % | 26 % | 5,3 |
| Zeichen-TF-IDF | 42 | 60 % | 29 % | 5,8 |
| BM25 | 38 | 63 % | 26 % | 5,3 |
| nur Überschriften-Lexikon | 38 | 63 % | 24 % | 5,3 |
| Model2Vec allein | 49 | 49 % | 33 % | 7,0 |

Die Varianten mit Lexikon und lexikalischen Rankern liegen dicht beieinander. Model2Vec allein belegt mehr Bausteine,
wählt aber öfter falsch.

### Sprachmodell als Satzauswahl

`extraction=llm`, Goldstandard, 19.09.2026: Der Lauf entstand ohne Model2Vec. Gegenüber derselben Konfiguration ohne
LLM (107 gedruckte Absätze, 63 richtig) druckte das LLM 131 Absätze, davon 77 richtig: 14 richtige mehr bei gleicher
Präzision von 59 %. Gegenüber dem heutigen Standard (110 und 67, also 61 %) ist das nur ein Anhaltspunkt. Große
Bausteine gewinnen, kleine füllt das LLM oft falsch: In Querschnitt landeten 7 Absätze, keiner davon richtig. Kosten
14.000 bis 22.400 Tokens je Thema; ein Richtervergleich der Texte steht aus.

## Warum `hybrid_light` mit Model2Vec der Standard ist

1. **Bester Kompromiss unter den lokal laufenden Verfahren.** Höchster macro-F1 (0,45, gleichauf mit Model2Vec
   allein) und die meisten richtigen Absätze unter den besten zwei (67 %), in 0,3 s auf der CPU und ohne Tokens.
2. **Model2Vec trägt, die lexikalischen Ranker schärfen.** Model2Vec allein erreicht denselben macro-F1 und belegt
   mehr Bausteine (7,3), wählt aber unsicherer: 54 % richtige Spitzenabsätze, beim Richter 49 % klar und 33 % falsch.
   Zusammen mit BM25 und Zeichen-TF-IDF steigt der Anteil auf 67 %.
3. **Die Ranker holen die kleinen Bausteine.** Gegenüber dem reinen Überschriften-Lexikon steigt macro-F1 von 0,35
   auf 0,45, fast nur in Bausteinen, zu denen Artikel selten eine passende Überschrift haben: Bildung von 0,00 auf
   0,50, Regularien von 0,00 auf 0,33, Beruf von 0,17 auf 0,31. Große Bausteine bleiben gleich, etwa Fachinhalte
   0,70 gegen 0,71.
4. **Schwerere Modelle bringen nichts.** Im selben Ablauf kommen die MiniLM-Satzvektoren auf 0,37, das
   Frage-Antwort-Modell auf 0,38 und der Cross-Encoder auf 0,30, bei 4 bis 73 s je Thema. Als Umsortierung der
   Kandidaten verschlechtert der Cross-Encoder den Standard deutlich: 0,35 statt 0,45, 38 % statt 67 % richtige
   Spitzenabsätze. Als vierter Ranker kommt er auf 0,37. Das Modell ist auf Suchrelevanz trainiert, also darauf, ob
   ein Absatz eine Suchanfrage beantwortet, nicht darauf, ob er in einen Baustein passt.
5. **Robust ohne Überschriften.** Klexikon-Artikel und Materialtexte haben kaum Überschriften; dort trägt allein
   der Ranker.
6. **Mögliche Vereinfachung:** BM25 + Model2Vec erreicht fast dasselbe (0,44 und 63 %, beim Richter gleichauf) in
   0,05 statt 0,30 s.
7. **Das LLM ist besser, aber spürbar langsamer und teuer.** Rund 0,7 statt 0,43 auf den gelabelten Absätzen (0,66
   bis 0,73 in vier Läufen). Dafür dauert Teil 1 im Median 12,0 statt 1,2 s (M13), an einem Tag mit langsamerer
   b-api 22,7 statt 1,8 s (M14), und ein Kompendium kostet im Mittel 29.400 Tokens mit Rückfällen am Budget (M13),
   seit D39 ohne sie 34.500 (M14). Am 24.09.2026 entschieden: `hybrid_light` bleibt Standard, `matcher=llm` bleibt je
   Anfrage wählbar (D38).

## Das LLM als wählbare Strategie

Das LLM ist das einzige gemessene Verfahren, das klar besser zuordnet: rund 0,7 statt 0,43 macro-F1 und 113 statt 201
Fehlzuordnungen auf denselben Absätzen (D36, M12). Als Standard kommt es wegen der Kosten nicht in Frage. Seit D34
steht es je Anfrage als `matcher=llm` bereit; das kam nach v2.0.0 hinzu und steht noch in keiner Version mit Tag.

- **Wie gemessen:** Das Modell ordnet jeden Absatz zu, mit demselben Prompt.
- **Rückfall je Absatz:** Die Standard-Strategie läuft vorher. Absätze, für die das Modell nicht entscheidet (b-api,
  Budget, Zeit, unlesbare Antwort, unbekannter Baustein), behalten ihre Regelzuordnung. Ohne nutzbares LLM gilt die
  Standard-Strategie ganz, und der Vorspann nennt `matcher_requested: llm`.
- **Budgets:** Die Längenbudgets der Bausteine schneiden wie bei der Policy, geordnet nach der Sicherheit des Modells.
- **Kennzeichnung:** Bausteine mit Absätzen, die das Modell zugeordnet hat, tragen den Status `ki-ausgewählt`. Der
  Vorspann kennzeichnet die Auswahl als KI-gestützt. `audit.llm.matching` zählt entschiedene und zurückgefallene
  Absätze, und die Metrik der Anfragen zählt `matcher=llm` wie einen LLM-Schalter.
- **Gemessen und verworfen (M12):** das LLM nur über die Absätze entscheiden lassen, die die Policy ohne sicheres
  Signal zuordnet oder weglässt (278 von 597, 71.173 Tokens): macro-F1 0,54 und so viele Fehlzuordnungen wie die
  Regeln. Die Policy liegt auch bei ihren sicheren Absätzen zu 39 % falsch, dort hilft das LLM dann nicht.
- **Nicht umgesetzt, weil nicht gemessen:** das LLM nur über die Kandidaten der Ranker entscheiden lassen (Median 109
  von 162 Absätzen).

Der Schalter `extraction=llm` geht einen anderen Weg und lässt sich mit `matcher=llm` kombinieren: Er lässt die
Zuordnung stehen und das LLM Sätze aus den besten Kandidaten wählen. Beide teilen sich das Tokenbudget der Anfrage.
Offen ist eine Gegenprobe der LLM-Zuordnung durch ein anderes Modell auf fremden Themen, weil auch die Goldlabels von
einem Sprachmodell stammen.

## Grenzen und nächste Hebel

Das Ziel macro-F1 0,70 erreicht nur das LLM, und nur in manchen Läufen (0,66 bis 0,73, M5 und M12); die lokalen
Verfahren bleiben bei 0,43 bis 0,45. Beim Standard gelingen große Bausteine, kleine kaum:

| Baustein | Gold-Absätze | F1 |
|---|---|---|
| Themendefinition | 22 | 0,68 |
| Gliederung & Systematik | 55 | 0,60 |
| Fachinhalte | 276 | 0,71 |
| Gesellschaftlicher Kontext | 38 | 0,40 |
| Entwicklung & Ausblick | 83 | 0,74 |
| Beruf & Wirtschaft | 11 | 0,31 |
| Bildung | 8 | 0,50 |
| Regularien & Rahmensetzung | 2 | 0,33 |
| Praxis | 18 | 0,20 |
| Querschnitt & Bezüge | 3 | 0,00 |

- **Mehr und geprüftes Gold.** Kleine Bausteine haben nur 2 bis 18 Belege; ihre Werte schwanken stark. Eine
  redaktionelle Prüfung der Labels steht aus.
- **Abdeckung statt eines anderen lokalen Rankers.** Enzyklopädische Artikel enthalten zu Beruf, Bildung oder Praxis
  wenig. Mehr versprechen Quellen, die solche Inhalte haben. Wikibooks und Wikiversity über ihre Volltextsuche
  brachten in M11 fast nichts: +1 gefüllter Baustein in 20 Themen. Aus guten Unterrichtsseiten wie
  *Physikunterricht/ Optik* oder *Kurs:Optik* druckte der Standard keinen Absatz, dafür aus Randtreffern wie
  *Arbeiten mit .NET*. Materialien einer Wissens-Sammlung bleiben der aussichtsreichere Weg.
- **Schärfere Bausteinbeschreibungen (M12):** lokal kein Gewinn (0,448 statt 0,447), mit dem LLM +0,013 innerhalb der
  Streuung; nicht übernommen.
- **Schon verworfen, weil gemessen schlechter oder nicht besser:** am 18.09.2026 gelernte Zuordnung per
  logistischer Regression (macro-F1 höchstens 0,35 bei Kreuzvalidierung über Themen), Schwellen je Baustein,
  zentrierte Embeddings, ein Embedding der Überschriften, eine Füllregel für leere Bausteine; am 23.09.2026
  MiniLM-Satzvektoren, Frage-Antwort-Modell und Cross-Encoder als Ranker sowie der Cross-Encoder als Umsortierung.
