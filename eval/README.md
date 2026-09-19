# Evaluation des Slot-Matchings (PLAN.md 4.5)

Der Goldstandard sagt für Textabschnitte (Chunks) echter Kompendium-Korpora, in welchen
SC26-Baustein sie gehören oder dass sie in keinen gehören. Damit lässt sich messen, wie oft der
Matcher richtig liegt, statt nur zu zählen, ob Bausteine gefüllt sind.

## Dateien

| Pfad | Inhalt |
|---|---|
| `gold/<thema>.jsonl` | geprüfte Labels je Thema; erste Zeile `{"_meta": …}` (Thema, Template, Archivstand, wer gelabelt hat), dann ein Label je Zeile |
| `export/<thema>.csv` | Arbeitsdateien zum Labeln (nicht versioniert, `compendium eval export`) |
| `reports/*.json` | Messläufe (`compendium eval run --json`), Baseline und kalibrierte Stände |
| `headings_top.csv` | die 1000 häufigsten H2/H3-Überschriften aus 20.000 Zufallsartikeln des Wikipedia-Dumps (`scripts/harvest_headings.py`), Grundlage für `config/heading_lexicon.yaml` |

Ein Label zeigt per Texthash (`text_hash`, SHA-1 des normalisierten Texts) auf den Chunk; die
Chunk-ID ist nur Rückfall und Lesehilfe. Labels überleben so Änderungen an der Nummerierung; ein
Label, dessen Text nicht mehr vorkommt, wird als „veraltet" gezählt und nicht bewertet.

## Ablauf

```bash
# Chunks eines Themas zum Labeln exportieren (Spalte suggested_slot = Vorschlag der Policy)
uv run compendium eval export --topic "Photosynthese" --zim … --out eval/export/photosynthese.csv
# Spalte gold_slot ausfüllen: Slot-Key, none oder leer (= kein Baustein), dann importieren
uv run compendium eval import eval/export/photosynthese.csv --topic "Photosynthese" --labeled-by "Name" --zim …
# Alle Gold-Dateien bewerten (Standard: lexicon_only, bm25, char_tfidf, hybrid_light)
uv run compendium eval run --gold eval/gold --json eval/reports/lauf.json --zim …
```

Über die API liefert `POST /api/v2/matching/compare` dieselben Metriken für ein Thema und die
Übereinstimmung der Strategien untereinander.

## Metriken

- **Klassifikation vor Budget**: die Entscheidung der Policy je Chunk, bevor die Slot-Budgets die
  Auswahl kürzen. Das ist das Qualitätsmaß.
- **Auswahl**: was nach den Budgets in den Text kommt (Präzision zählt, Recall ist durch die
  Budgets begrenzt).
- Precision, Recall und F1 je Baustein; **macro-F1** über die Bausteine mit Gold-Belegen,
  **micro-F1** über alle Chunks; **fehlbelegt** (falscher Baustein oder Baustein statt keiner),
  **verpasst** (Gold-Baustein, aber nicht zugeordnet); **Halluzinations-Slots** (zugeordnet,
  obwohl das Gold für diesen Baustein keinen Chunk hat); Verwechslungsmatrix `gold>zuordnung`.

## Labelregeln (Stand 2026-09-17)

Die Erstzuordnung stammt vom Entwicklungsteam (LLM-Vorschlag, jede Zeile gelesen); die Redaktion
kann Labels in den JSONL-Dateien korrigieren. Themen: Optik, Photosynthese, Säure-Base-Konzepte,
Bruchrechnung, Barockliteratur, Französische Revolution, Klimawandel, Demokratie,
Programmiersprache, Sinfonie; Hauptartikel je bis 40 Chunks, Nebenartikel je bis 4 (Optik komplett).

- **Themendefinition** nur für den Lead des Hauptartikels, ausdrückliche Definitions- und
  Abgrenzungsabsätze des Themas und den Klexikon-Lead.
- **Systematik**: Teilgebiete, Typen und Varianten des Themas, Einleitungen von Teilgebiets-Artikeln
  (Wellenoptik für Optik), Gliederungen und Typologien.
- **Fachinhalte**: Gesetze, Mechanismen, Begriffe, Rechenregeln, Verlauf eines historischen
  Ereignisses (bei Ereignisthemen), Theorien; der Regelfall für Fließtext des Hauptartikels.
- **Gesellschaftlicher Kontext**: Bedeutung, Alltag, Kritik, Rezeption, Debatten, Politik, Risiken.
- **Entwicklung & Ausblick**: Geschichte des Themas, Forschungsgeschichte, Epochen, Folgen,
  Prognosen; bei Klimawandel die erdgeschichtlichen Klimaereignisse.
- **Beruf & Wirtschaft**, **Bildung**, **Regularien**, **Praxis**, **Querschnitt** gemäß den
  Inklusionen in `app/templates/builtin/sc26.json`.
- **none**: Personen-, Werk- und Autorenlisten (Baustein 6 wird generiert), Formelreste,
  Bildunterschriften, Verweise, Biografie- und Einzelwerk-Absätze, Filmartikel, Listenartikel,
  Absätze ohne Themenbezug.

## Stand

| Lauf (10 Themen, 603 bewertete Chunks) | macro-F1 | micro-F1 |
|---|---|---|
| Baseline Phase 0/1 (`hybrid_light`) | 0,27 | 0,32 |
| Standardbaustein, Teilgebiets-Regel, Fragmentfilter, Lexikon v3 (`hybrid_light`) | 0,39 | 0,63 |
| dazu Model2Vec `JanSchachtschabel/m2v-gte-256-edu` | 0,43 | 0,63 |
| dazu Schwelle 0,65 und Abschnitts-Glättung 0,5 (2026-09-18) | 0,45 | 0,66 |

Das Ziel macro-F1 ≥ 0,70 aus PLAN.md 4.5 ist nicht erreicht. Die großen Bausteine
(Themendefinition 0,67, Systematik 0,60, Fachinhalte 0,69, Entwicklung 0,71) tragen den
micro-Wert; die kleinen (Beruf 0,22, Bildung 0,59, Regularien 0,18, Praxis 0,22, Querschnitt 0,00
mit 2–18 Gold-Chunks) ziehen den macro-Wert. Schwellen (`POLICY_CONFIDENT_SCORE` 0,35/0,45/0,55
→ 0,41/0,43/0,43) wurden auf demselben Gold gemessen, es gibt keine Hold-out-Menge.

### Nachschärfung vom 2026-09-18: Schwelle 0,65 und Abschnitts-Glättung

Geprüft und verworfen (alle im Rauschen um macro-F1 0,43 oder schlechter): zentrierte Model2Vec-Ähnlichkeiten,
Überschriften-Embedding als eigener Ranker, Lexikontreffer nur in themennahen Artikeln, Füllregel für leere
Bausteine, Mindestlänge für den Standardbaustein, Schwellen je Baustein (Leave-one-topic-out gelernt), gelernte
Zuordnung per logistischer Regression auf den Gold-Labels (Leave-one-topic-out macro-F1 höchstens 0,35).

Übernommen: `POLICY_CONFIDENT_SCORE` 0,65 statt 0,45 und `POLICY_SECTION_SMOOTHING` 0,5 (jeder Score wird zur
Hälfte mit dem Mittel seines Abschnitts für denselben Baustein verrechnet).

| Maßstab | vorher | nachher |
|---|---|---|
| Gold, alle 10 Themen: macro-F1 / micro-F1 / fehlbelegt | 0,430 / 0,632 / 212 | 0,447 / 0,656 / 189 |
| Gold, gedruckte Absätze: richtig / falsch | 66 / 63 | 67 / 43 |
| Gold, Leave-one-topic-out: Trefferquote der gedruckten Absätze | 51 % | 59 % |
| Blinder Richter, 4 fremde Themen: klar / teilweise / falsch | 46 / 9 / 23 | 46 / 7 / 14 |
| Blinder Richter: Bausteine mit Volltreffer | 20 | 17 |

Die fremden Themen (Plattentektonik, Ökosystem, Atommodell, Industrielle Revolution) waren weder im Gold noch
an der Abstimmung beteiligt. Preis der Änderung: weniger belegte Bausteine (22 statt 31 auf den fremden Themen,
drei Volltreffer weniger); von zehn dort aussortierten Absätzen bewertete der Richter sieben als falsch. Das Band
0,45 bis 0,65 geht in den Hybridmodi weiter an den LLM-Router (`DOUBT_FLOOR`; seit D33 entfallen, die LLM-Extraktion
bietet solche Absätze als Kandidaten an). Die Materialregel der
Wissens-Sammlung startet jetzt an der konfigurierten Schwelle statt fest bei 0,5.

## Vergleich mit den Matchern der Testapp (2026-09-18)

Anlass: Der Testbericht der Testapp (`kompendium-test`) empfiehlt `model2vec` bzw. `bm25_static` (BM25 + Model2Vec)
und misst den Cross-Encoder mit 95 bis 97 % „didaktischer Präzision“. Gemessen wurde mit den Original-Matchern der
Testapp (deren venv, offline) auf den Chunks dieses Projekts, gegen drei Maßstäbe. Skripte: `mc_*.py` im Scratchpad
der Sitzung; bei Bedarf ins Repo übernehmen.

| Verfahren | Gold macro-F1 | Gold richtige Auswahl | Testapp-Metrik F1 | Richter: klar passend | Richter: falsch | Bausteine mit Volltreffer |
|---|---|---|---|---|---|---|
| hier `hybrid_light` + Model2Vec (Standard) | 0,43 | 51 % | 79 | 60 % | 23 % | 5,3 von 10 |
| hier BM25 + Model2Vec unter derselben Policy | 0,43 | 49 % | 79 | 60 % | 25 % | 6,0 |
| hier Model2Vec allein unter derselben Policy | 0,41 | 46 % | 75 | 59 % | 28 % | 6,3 |
| Testapp `model2vec` | 0,24 | 35 % | 87 | 54 % | 32 % | 7,0 |
| Testapp `bm25_static` | 0,20 | 31 % | 87 | 55 % | 33 % | 7,3 |
| Testapp `m2v_cross_encoder` (3 Themen) | 0,17 | 44 % | 93 | 41 % | 41 % | 5,3 |
| Testapp `cross_encoder` (3 Themen) | 0,19 | 27 % | 96 | 31 % | 54 % | 4,0 |
| Testapp `extractive_qa` (3 Themen) | 0,16 | 57 % | 68 | 56 % | 24 % | 4,0 |

Gold und Testapp-Metrik: 10 Themen, voller Kandidatenpool (Cross-Encoder und QA: Optik, Photosynthese, Demokratie).
Richter: blinde Bewertung der je Baustein gewählten Top-2-Absätze durch `gpt-5.6-luna` (2 = passt klar, 1 = teilweise,
0 = passt nicht), 3 Themen, 271 bewertete Paare, rund 64.000 Tokens. Je Verfahren nur rund 50 Absätze: Unterschiede
unter etwa 10 Prozentpunkten sind nicht belastbar.

Lesart:
- Die Testapp-Metrik misst Slot-Abdeckung und ob die Überschriften-Kategorie des Chunks zum Slot passt. Dieselbe
  Kategorie nutzen die Testapp-Matcher als Bonus; `lexicon_only` erreicht dort 99 bis 100 % Präzision. Sie belohnt
  also Überschriften-Treue, nicht inhaltliche Passung. Der Cross-Encoder glänzt dort und fällt beim Richter durch.
- Der Goldstandard dieses Projekts entstand mit Blick auf Vorschläge der eigenen Policy und begünstigt sie.
- Der Richter liegt dazwischen: Die Policy hier wählt treffsicherer aus (weniger falsche Absätze), die Testapp belegt
  jeden Baustein und landet deshalb öfter mindestens einen Volltreffer (vor allem Systematik, Beruf, Entwicklung).
- Der Ranker ist unter derselben Policy fast egal (macro-F1 0,41 bis 0,43). BM25 + Model2Vec ist so gut wie die
  Dreierkombination und rund dreimal schneller (108 statt 313 ms je Thema), weil das Zeichen-TF-IDF entfällt.
- Mit den Slot-Texten der Testapp statt denen dieses Templates schneiden deren Matcher auf dem Gold nicht besser ab
  (macro-F1 0,21 und 0,18).

## LLM-Extraktion (D33, 2026-09-19)

`compendium eval run --llm-extraction` bewertet zusätzlich, was `extraction=llm` auf der Standardstrategie druckt
(`hybrid_light+llm`): Das LLM (`gpt-5.6-luna`) wählt je Baustein Sätze unter bis zu acht Kandidaten-Absätzen. Ein
Absatz zählt für den Baustein, der die meisten seiner Sätze druckt. Weil diese Auswahl keine Klassifikation vor dem
Budget kennt, ist der faire Vergleich „gedruckt gegen gedruckt“; der Bericht führt seit dem 2026-09-19 beide Sichten
getrennt (`aggregate` = Klassifikation, `printed` = gedruckt).

| Verfahren (10 Themen, 603 Labels) | gedruckt | richtig | falsch | davon Gold „none“ | macro-F1 | micro-F1 |
|---|---|---|---|---|---|---|
| `hybrid_light` + Model2Vec (Produktion) | 110 | 67 | 43 | – | 0,277 | 0,214 |
| `hybrid_light` ohne Model2Vec | 107 | 63 | 44 | 14 | 0,214 | 0,202 |
| `hybrid_light+llm` (ohne Model2Vec) | 131 | 77 | 54 | 7 | 0,273 | 0,238 |

Berichte: `reports/d33_llm_extraction.json` (LLM-Lauf; dort ist `aggregate.hybrid_light+llm` die gedruckte
Auswahl, `aggregate.hybrid_light` noch die Klassifikation), `reports/d33_rules_printed.json` und
`reports/d33_rules_printed_m2v.json` (Regeln in beiden Sichten). Kosten des LLM-Laufs: 189.975 Tokens, 87 s für
alle zehn Themen. Der LLM-Lauf entstand ohne Model2Vec (lokal war `MODEL2VEC_PATH` leer), die Kandidaten kamen also
aus der schwächeren Rangfolge; der Vergleich mit der Produktion ist deshalb nur ein Anhaltspunkt.

Lesart:
- Gegen dieselbe Konfiguration (ohne Model2Vec) druckt das LLM 14 richtige Absätze mehr bei gleicher Präzision
  (0,59) und halbiert die Absätze, die in keinen Baustein gehören (14 zu 7).
- Die großen Bausteine gewinnen an Präzision (Fachinhalte 0,60 zu 0,77, Systematik 0,62 zu 0,67, Entwicklung 0,73
  zu 0,79); die kleinen füllt das LLM mit falschen Absätzen (Querschnitt 7 gedruckt, keiner richtig; Bildung und
  Beruf schlechter). Der Prompt erlaubt eine leere Auswahl; wie oft das Modell sie nutzt, zeigt je Kompendium
  `audit.llm.extraction.emptied`, der Eval-Bericht erfasst es nicht.
- Der Goldstandard begünstigt die Policy (siehe oben); ein Richter-Vergleich der gedruckten Texte steht aus.
