# Entscheidungsvorlage: Verfahren und Schalter von Teil 1

[Übersicht](README.md) · Stand 09.10.2026, Release 2.17.0 · Zahlen: [Messprotokoll](05-messprotokoll.md), M1 bis
M90; Rohdaten und Zusammenfassungen in [messung/ergebnisse](messung/ergebnisse/README.md); Methoden und Werte von
`/entities`: [Entitäten und Kennungen](08-entitaeten-und-kennungen.md); alle Schritte mit ihren Methoden, Güte, Zeit
und Tokens je Profil: [Methoden, Messwerte und Profile](09-methoden-und-profile.md)

Teil 1 des Kompendiums, das Weltwissen, entsteht in fünf Schritten. An vier davon lässt sich ein Sprachmodell (LLM)
zuschalten. Diese Vorlage zeigt je Schritt, welche Verfahren es gibt, wie man sie im Dienst wählt, was sie leisten und
was sie an Zeit und Tokens kosten. Fünf Profile bündeln sie (D53, D69); der Schalter `preset` wählt eines. „Standard“
heißt: Das gilt, wenn die Anfrage nichts anderes verlangt. Standard ist das Profil `best-quality-generated`
(`PRESET_DEFAULT`, D82), ohne konfiguriertes LLM `llm-free` (D68); jedes Profil außer `llm-free` braucht ein LLM,
sonst ist die Anfrage ein 503. Die Profile wählen auch das Verfahren der QA-Paare (D54, D55, D57).

## Die fünf Profile auf einen Blick

| | `llm-free` | `balanced` | `best-quality` | `best-quality-generated` (Standard) | `best-coverage-generated` |
|---|---|---|---|---|---|
| Hauptartikel (`article_choice`) | `rule-based` | `llm` | `llm-thorough` | `llm-thorough` | `llm-thorough` |
| Korpus | 12 Artikel, Volltexttreffer nur mit Link zum Hauptartikel | statt verlinkter Unterartikel und Volltexttreffer die Artikel, die das LLM als Übersicht und Teile nennt (D63); ohne Antwort wie `llm-free` mit Prüfung der Nebenartikel | wie `balanced` | wie `balanced` | wie `balanced` |
| Zuordnung (`matcher`) | `hybrid_light` | `hybrid_light` | `llm` | `llm` | `llm` |
| Thema in den Prompts (D72) | keine Prompts | das angefragte Thema | das angefragte Thema | das angefragte Thema; ist es ein Text oder kommt ein Knoten oder eine Sammlung ohne Thema, formuliert das LLM es zuerst | wie `best-quality-generated` |
| Text (`generation`, `enrichment`) | wörtlich | wörtlich | wörtlich | vom LLM zum angefragten Thema geschrieben, ergänzt um Modellwissen (höchstens die Hälfte), ein Baustein ohne Belege aus Modellwissen (D72) | vom LLM vollständig zum angefragten Thema geschrieben: aus den Belegen, wo sie das Thema treffen, sonst aus Modellwissen (D69) |
| Hinweis in der Prüfung (`audit.lint`, `topic-scope`; V3, D73), wenn der Text einen anderen Artikel behandelt als das angefragte Thema | ja; die Wörter des Themas entscheiden | ja; die Frage N sagt, ob ihre Übersicht das Thema deckt | wie `balanced` | nein: der Text handelt vom angefragten Thema | wie `best-quality-generated` |
| Prüfung des Modellwissens (`model_knowledge_check`, Punkt 12a, D73) | – | – | – | `rule-based` (Schalter `llm`: ein zweiter Aufruf je Baustein streicht oder berichtigt Sätze aus Modellwissen) | wie `best-quality-generated`; in M53 brachte `llm` leichte Fehler je Text 1,1 statt 1,6 für rund 27.000 Tokens und 5 s mehr (D74: aus) |
| QA-Paare (`/qa`, `method`) | `rule-based` | `rule-based` | `llm` | `llm` | `llm` |
| Lehrplanbezüge (Teil 2, `curriculum_check`) | Regeln, Überschriften-Treffer gebündelt | wie `llm-free` | dazu LLM-Prüfung jedes Elements | dazu LLM-Prüfung jedes Elements | dazu LLM-Prüfung jedes Elements |
| Entitäten (`/entities`, `methods`) | `ner` (spaCy) und `dictionary` (Artikeltitel) | `llm`: das LLM nennt sie mit Artikeltitel | wie `balanced` | wie `balanced` | wie `balanced` |
| Kennungen der Entitäten (Wikidata, GND, DBpedia; M43) | aus lokalen Daten zum verknüpften Artikel, in allen Profilen gleich (D65): Wikidata Präzision 0,29, Recall 0,55; GND 0,31 und 0,57; DBpedia über den englischen Artikel bei 88 % | ebenso, auf den Artikeln des LLM: Wikidata 0,70 und 0,89; GND 0,70 und 0,88; englischer Artikel bei 96 % | wie `balanced` | wie `balanced` | wie `balanced` |
| Hauptartikel richtig, 94 Goldanfragen (M82; mit `llm-thorough` in M35 und M59 93) | 87 | 91 | 91 | 91 | 91 |
| Material ohne `topic`: Hauptartikel-F1, zwei Stichproben (M25) | 0,56 und 0,63 | 0,98 und 0,88 | wie `balanced` | wie `balanced` | wie `balanced` |
| gedruckte Absätze aus unpassenden Artikeln, 20 Themen (M25) | 12 von 352 | 5 von 346 vor D63 | nicht gemessen | nicht gemessen | nicht gemessen |
| gedruckte Absätze aus passenden Artikeln, 25 Sammel- und 20 gewöhnliche Themen (M37, M39) | 43 % und 71 % | 87 % und 93 % seit D63 (vorher 45 und 73 %) | wie `balanced` (derselbe Korpus, nicht eigens gemessen) | wie `balanced` | wie `balanced` |
| Zuordnung, macro-F1 der gelabelten Absätze (M82; M27, M19) | 0,455 | 0,455; den Korpus mit N deckt das Gold nur zu zwei Dritteln ab (M39) | 0,661 und 0,675 in zwei Läufen (M19: 0,70) | wie `best-quality` | wie `best-quality` |
| Lesbarkeit für Lehrkräfte, 1 bis 5, zwei Gutachter (M28) | wörtlich wie `best-quality` | wörtlich wie `best-quality` | 2,5 | 4,0; im Mittel 5 Füllsätze je Thema, mit dem ersten Prompt 12 (M31) | nicht gemessen; in M52 4,2 |
| Passung zum angefragten Thema an neun Themen, zwei Gutachter (M82, Release 2.17.0): einfach, Sammelthema, mit Aspekt | 3,3, 1,2, 1,0 | 4,0, 2,0, 1,3 | 4,5, 2,5, 1,8 | 4,8, 4,0, 3,8 | 5,0, 5,0, 5,0 |
| Nutzen, Vollständigkeit, Lesbarkeit an denselben neun Themen (M82) | 1,7, 1,2, 2,1 | 2,0, 1,4, 1,9 | 2,7, 2,1, 2,1 | 3,8, 3,7, 3,6; 0,1 schwere und 1,2 leichte Fehler je Text | 4,7, 5,0, 4,1; keine schweren und 0,7 leichte Fehler je Text |
| Teil 1 und 2 mit 30.000 Zielzeichen im Container des Entwicklungsrechners, nachts, Median (M82) | 2,6 s, 0 Tokens, 9.718 Zeichen | 4,6 s, 314 Tokens, 11.146 Zeichen | 12,6 s, 59.335 Tokens, 12.914 Zeichen | 23,2 s, 63.117 Tokens, 24.711 Zeichen, 51 % Modellwissen | 27,3 s, 87.225 Tokens (50.637 aus dem Prompt-Cache), 54.309 Zeichen, 82 % Modellwissen |
| Themen mit Aspekt („OER-Förderungen“), acht Themen, zwei Gutachter (M47): Passung, Nutzen, Vollständigkeit von 1 bis 5 | nicht gemessen | nicht gemessen | nicht gemessen | 1,81, 2,12, 1,69: der Text handelt vom Artikel | 4,81, 4,81, 5,00; keine schweren Fehler |
| QA-Paare mangelfrei bei beiden Gutachtern (M30, M34); Note von 0 bis 2 an sechs Themen à fünf Paare (M82) | 58 von 95 seit D60 (vorher 48 von 96); Note 0,8; 0,49 s an rund 26.500 Zeichen (M82) | wie `llm-free` | 99 von 120; Note 1,4; 5,8 s und 8.209 Tokens an rund 26.500 Zeichen (M82) | wie `best-quality` | wie `best-quality` |
| Lehrplanelemente passend, 20 Themen, zwei Gutachter (M32) | 70 bis 81 %, 5 bis 9 % unpassend, ein Viertel der passenden nur gebündelt | wie `llm-free` | 74 bis 79 %, 5 bis 9 % unpassend, kein passendes verloren; seit D81 rund 2,5 s neben der Zuordnung und im Median rund 4.000 Tokens mehr (M82) | wie `best-quality` | wie `best-quality` |
| Entitäten: F1 an 40 Materialtexten, zwei Gutachter, durch den Endpunkt (M36, D62) | 0,38, Präzision 0,29; 2,4 s an 1.500 Zeichen (M82) | 0,78, Präzision 0,70; 5,8 s und 1.214 Tokens an 1.500 Zeichen (M82) | wie `balanced` | wie `balanced` | wie `balanced` |
| Teil 1 und 2 auf dem Server (M45, Release 2.2.2) | 2,3 s ohne LLM | die Schritte ohne LLM etwa halb so lange wie im Container, die des LLM gleich lang | wie `balanced` | wie `balanced` | wie `balanced` |
| Budget je Anfrage (D59, D102) | 60.000 | 60.000 | 200.000 | 200.000 | 200.000 |
| Bausteinbudget beim Zuschnitt (`BLOCK_BUDGET_FACTOR`, D102) | das Zehnfache der Vorlage | wie `llm-free` | wie `llm-free` | wie `llm-free` | wie `llm-free` |
| Kompendien je Million Tokens (M82, vor D102) | ohne Grenze | rund 3.200 | rund 17 | rund 16 | rund 11 |
| so wählt man es | `preset: llm-free`; ohne LLM gilt es auch ohne `preset` (D68) | `preset: balanced` | `preset: best-quality` | Standard, `preset: best-quality-generated` | `preset: best-coverage-generated` |

![Fünf Profile an drei Arten von Themen (M48)](bilder/profilvergleich.svg)

Güte, Zeit und Kosten aller fünf Profile mit Release 2.17.0 (M82), Tabelle und Lesart auf
[Methoden, Messwerte und Profile](09-methoden-und-profile.md#die-fünf-profile-im-überblick-güte-zeit-und-kosten-m82),
dort auch [welches Profil wofür](09-methoden-und-profile.md#welches-profil-wofür):

![Die fünf Profile: Güte, Zeit und Kosten (M82)](bilder/profiluebersicht.svg)

![Die vier Profile vor D69 im Vergleich (das fünfte steht in der Tabelle)](bilder/kombinationen.svg)

- **`llm-free`** ist das Beste, was ohne Sprachmodell geht: die geschärften Regeln der Artikelwahl, für ein Material
  ohne `topic` die Regeln über Titel und Beschreibung (D47), Volltexttreffer nur mit Link zum Hauptartikel (D48),
  `hybrid_light` mit Model2Vec als bestes lokales Zuordnungsverfahren, wörtlicher Text und QA-Paare aus den Regeln über
  den spaCy-Parse (D55), aufgefüllt mit Glossar und Akteuren (D60): 58 von 95 bei beiden Gutachtern mangelfrei, in
  0,3 s je Text (M34). Entitäten (`/entities`) erkennt es mit spaCy und dem Wörterbuch der Artikeltitel: F1 0,38 an
  40 Materialtexten, weil das Wörterbuch auch Allerweltswörter verknüpft (M36). Keine Tokens, keine Abhängigkeit von
  der b-api; das Profil für einen Dienst ohne LLM.
- **`balanced`** war bis D82 der Standard. Die LLM-Artikelwahl ist der billigste Hebel mit messbarer Wirkung: fünf richtige
  Hauptartikel mehr von 94, 5 statt 12 gedruckte Absätze aus unpassenden Artikeln und bei einem Material ohne `topic`
  ein Hauptartikel-F1 von 0,88 bis 0,98 statt 0,56 bis 0,63, damals für rund 1,5 bis 2 s und 900 Tokens (M25, M27).
  Seit D63 nennt das LLM dazu Übersicht und Teile des Themas: 87 statt 43 % passende Absätze bei Sammelthemen (M39);
  ein Kompendium mit Teil 1 und 2 kostet so rund 4,6 s und 310 Tokens (M82; auf dem Server 6,9 s und 576 Tokens in
  M45, vor D81). Die Zuordnung bleibt die von `llm-free`
  (0,45): Das LLM wirkt vor ihr, nicht in ihr (M27). Die QA-Paare kommen seit D57
  aus denselben Regeln wie in `llm-free` (Jan: der Standard fragt schnell und ressourcenschonend): 0,3 s, keine
  Tokens, kein zusätzliches Modell. Die zwei kleinen Modelle, die hier bis D57 fragten, waren in M30 die schwächste
  und langsamste Stufe (25 von 120 mangelfrei, rund 25 s je Text) und sind entfernt. In `/entities` nennt das LLM die
  Entitäten mit ihrem Artikeltitel (D62): F1 0,78 statt 0,38, von 269 Verknüpfungen meinte eine etwas anderes, rund
  800 Tokens und 4 s je Text (M36, durch den Endpunkt nachgemessen).
- **`best-quality`** nimmt dazu das LLM als Zuordner: 0,66 bis 0,70 statt 0,45 macro-F1, für rund 13 s und 59.000
  Tokens je Kompendium mit Teil 2 (M82, nachts; am Nachmittag 15 s, M78): rund 160 Tokens je Absatz, dazu die Prüfung
  der Lehrplanelemente. Sinnvoll, wo Qualität zählt und Zeit nicht, etwa beim Vorbereiten eines Kompendiums für die
  Redaktion. Der Text bleibt wörtlich und belegt. Die QA-Paare schreibt das LLM: 99 von 120 mangelfrei, rund
  2.400 Tokens und 4 bis 7,5 s je Text (M30). Die Lehrplanelemente von Teil 2 prüft das LLM ebenfalls (D58): 74 bis
  79 % passend, kein passendes verworfen, im Median rund 6 s und 8.000 bis 10.000 Tokens mehr (M32); seit D81 fragt
  die Prüfung ohne Denken und läuft neben der Zuordnung, im Median rund 4.000 Tokens (M82). `/entities`
  arbeitet wie in `balanced`: Eine zweite LLM-Prüfung jeder Verknüpfung hob die Präzision auf 0,94, verwarf aber ein
  Drittel der passenden Entitäten (F1 0,76 statt 0,78); sie bleibt ein eigener Schalter (`link_check: llm`, D62).
- **`best-quality-generated`**, seit D82 der Standard, lässt das LLM zusätzlich jeden Baustein schreiben und eigenes
  Wissen ergänzen, ohne Belegnummer und gekennzeichnet (D56; sichtbar als `[Modellwissen]` seit D76 nur auf Wunsch):
  rund 23 s und 63.000 Tokens je Kompendium mit Teil 2 (M82, nachts; am Nachmittag 30 s, M78). Zwei
  blinde Gutachter zogen den geschriebenen Text in 11 von 12 Urteilen dem wörtlichen vor (Lesbarkeit 4,0 statt 2,5 von
  5, Zusammenhang 4,0 statt 2,4), bei ähnlich vielen Fachfehlern, die meist schon in den Quellen stehen (M28). Mit dem
  ersten Prompt bestand das ergänzte Modellwissen zu zwei Dritteln aus Füllsätzen; der zweite verlangt eine prüfbare
  Sachaussage oder nichts: 50 statt 82 ergänzte Sätze, davon 13 statt 50 Füllsätze und 32 statt 27 fachliche, keiner
  falsch nach beiden Gutachtern (M31). `/entities` wie in `balanced`. Seit D70 darf das Modellwissen bis zur Hälfte
  eines Bausteins füllen; genutzt hat es in M48 im Median 28 %. Seit D72 schreibt es leere Bausteine ganz aus
  Modellwissen: in M52 62 %, in M82 51 % des Textes. Ein Thema ohne eigenen Artikel behandelt das Profil
  als den Artikel der Artikelwahl: Passung 3,0 bei Sammelthemen, 1,7 bei Themen mit Aspekt (M48).
- **`best-coverage-generated`** (D69) schreibt wie `best-quality-generated`, aber jeden Baustein vollständig über das
  Thema, wie es angefragt ist: Belege, wo sie das Thema treffen, sonst gesichertes Modellwissen, sichtbar
  gekennzeichnet, auch für einen Baustein ohne Belege; die Ziellänge ist Untergrenze. Für Themen mit Aspekt wie
  „OER-Förderungen“, die die Artikelwahl auf einen Oberbegriff auflöst: Passung 4,81 statt 1,81, Nutzen 4,81 statt
  2,12, Vollständigkeit 5,0 statt 1,7, keine schweren Fehler (M47); Teil 1 rund 28 s und 91.000 bis 99.000 Tokens,
  rund ein Drittel aus dem Prompt-Cache (M46). Den größten Teil des Textes schreibt das Modell aus eigenem Wissen.
  M48 an allen drei Arten von Themen: Passung 5,0, Nutzen 4,5, Vollständigkeit 4,8, Lesbarkeit 4,1, keine schweren
  Fehler, 0,8 leichte je Text, sechs der acht im Modellwissen; mit 30.000 Zielzeichen rund 37 s, 101.000 Tokens und
  57.000 Zeichen, denn die Ziellänge ist hier Untergrenze (Punkt 13). M82, Release 2.17.0: Passung und
  Vollständigkeit 5,0 bei allen drei Arten, Teil 1 und 2 in rund 27 s mit 87.000 Tokens, 54.000 Zeichen, 82 %
  Modellwissen.

Zeiten und Tokens in der Tabelle oben: M82 (09.10.2026, Release 2.17.0, `gpt-6-luna` über OpenAI), Teil 1 und 2 an
neun Themen im Container des Entwicklungsrechners, nachts; die Profile im Text nennen daneben die Werte zur Zeit ihrer
Entscheidung. Die Werte vor D58 und D63 stehen in M27, die von Release 2.2.2 in M45
([Methoden, Messwerte und Profile](09-methoden-und-profile.md)).

## Die Profile: `preset`

`preset` setzt alle Schalter von Teil 1 und die Lehrplanprüfung von Teil 2 auf eines der fünf Profile (D41, D53,
D58, D69). Einen Schalter, den die Anfrage selbst
setzt, lässt es stehen. Ohne `preset` gilt `PRESET_DEFAULT`, ausgeliefert `best-quality-generated` (D82; davor
`balanced`, D53, und bis dahin `llm-free`, D40); es ersetzt die Vorgaben der Einzelschalter (`MATCHER_DEFAULT`,
`LLM_ARTICLE_CHOICE_DEFAULT` und die übrigen). Jedes Profil außer `llm-free` braucht ein LLM: Ohne `LLM_ENABLED` und
`B_API_KEY` ist eine Anfrage, die ein solches Profil nennt, ein 503, der die Schalter nennt, die ein LLM brauchen; eine
Anfrage ohne `preset` läuft dann mit `llm-free` (D68).

| `preset` | `article_choice` | `matcher` | `extraction` | `generation` | `enrichment` | `curriculum_check` |
|---|---|---|---|---|---|---|
| `llm-free` | `rule-based` | `hybrid_light` | `rule-based` | `rule-based` | `sources-only` | `rule-based` |
| `balanced` | `llm` | `hybrid_light` | `rule-based` | `rule-based` | `sources-only` | `rule-based` |
| `best-quality` | `llm-thorough` | `llm` | `rule-based` | `rule-based` | `sources-only` | `llm` |
| `best-quality-generated` | `llm-thorough` | `llm` | `rule-based` | `llm` | `model-knowledge` | `llm` |
| `best-coverage-generated` | `llm-thorough` | `llm` | `rule-based` | `llm` | `model-knowledge-full` | `llm` |

Wo man es findet: in `/docs` am Feld `preset` von `POST /api/v2/compendium` (mit Güte, Zeit und Tokens je Profil) und in
fünf Beispielen, eines je Profil; `POST /api/v2/knowledge` und `POST /api/v2/qa` nehmen `preset` ebenfalls an
(`/knowledge` übernimmt daraus nur `article_choice`, `/qa` nur das Verfahren der Paare, D55); auf der Kommandozeile
`compendium generate --preset balanced`. Die Antwort nennt das wirksame Profil in `audit.preset`, was tatsächlich lief
in `audit.llm`. Ist die b-api nur gerade nicht erreichbar, laufen die Regeln, und `audit.llm` sagt warum.
`best-quality-generated` schaltet `generation` und `enrichment` ein (Jan, 25.09.2026), ebenso `best-coverage-generated`
mit `enrichment: model-knowledge-full` (D69, siehe die Empfehlung unten): Das LLM
schreibt jeden Baustein und darf eigenes Wissen ergänzen, ohne Belegnummer und sichtbar gekennzeichnet mit
`[Modellwissen]` (D56); `extraction` bleibt regelbasiert, weil es am Goldstandard nichts gewann (Schritt 4). Gemessen in
M27, M28, M31, M45 und M82: rund 23 s und 63.000 Tokens je Kompendium mit Teil 2 (M82, nachts; am Nachmittag
30 s, M78); zwei blinde Gutachter zogen den geschriebenen Text in 11
von 12 Urteilen dem wörtlichen vor (Lesbarkeit 4,0 statt 2,5 von 5, Zusammenhang 4,0 statt 2,4), bei ähnlich vielen
Fachfehlern, die meist schon in den Quellen stehen. Mit dem ersten Prompt waren zwei Drittel des ergänzten Modellwissens
Füllsätze; mit dem zweiten (D56) sind es 13 von 50 ergänzten Sätzen statt 50 von 82, und keiner ist nach beiden
Gutachtern falsch (M31).

## Die Profile je Endpunkt

| Endpunkt | `llm-free` | `balanced` | `best-quality` | `best-quality-generated` | `best-coverage-generated` |
|---|---|---|---|---|---|
| `POST /api/v2/compendium`, Teil 1 und 2 (M82) | Regeln; 2,6 s, keine Tokens | das LLM nennt Übersicht und Teile des Themas (D63) und entscheidet unsichere Artikel; 4,6 s, 314 Tokens | dazu LLM-Zuordnung und die Prüfung der Lehrplanelemente; 12,6 s, 59.335 Tokens | dazu Text vom LLM (Standard); 23,2 s, 63.117 Tokens | dazu schreibt das LLM jeden Baustein vollständig zum angefragten Thema; 27,3 s, 87.225 Tokens |
| `POST /api/v2/knowledge` | Regeln; 0,57 s | dieselben Artikel wie das Kompendium: Übersicht und Teile vom LLM (D63); 1,8 s, 313 Tokens | dazu prüft das LLM auch sichere Artikel; 3,6 s, 751 Tokens | wie `best-quality` | wie `best-quality` |
| `POST /api/v2/qa` mit `text` | `rule-based`: 0,49 s an rund 26.500 Zeichen (M82), 10 bis 20 von 20 Paaren, 58 von 95 mangelfrei (M34) | wie `llm-free` (D57) | `llm`: 5,8 s und 8.209 Tokens für 20 Paare an rund 26.500 Zeichen (M82; an 5.000 bis 12.000 Zeichen rund 2.400, M30), 99 von 120 mangelfrei | wie `best-quality` | wie `best-quality` |
| `POST /api/v2/qa` mit `topic` oder `node_id` | Teil 1 ohne LLM wie in `llm-free`, dann die Paare wie mit `text`; die Regeln lesen dazu Glossar und Akteure | ebenso; nur bei einem Material-Knoten wählt das LLM den Artikel (D47) | ebenso | ebenso; auch hier fragen die Paare den wörtlichen Teil 1 ab | ebenso |
| `GET /api/v2/lehrplan/search` | Regeln finden und bewerten, 0,02 s (M82); `mode=topic` löst wie Teil 2 auf, 0,57 s, keine Tokens | wie `llm-free`; mit `mode=topic` wählt das LLM den Artikel wie in Teil 2, 2,3 s und 313 Tokens | dazu bewertet das LLM jedes gefundene Element (D59): 2,7 s und 4.533 Tokens bei 14 bis 181 Treffern (M82); Demokratie ohne Fach: 819 Elemente, 75.016 Tokens, 9,5 s (M33) | wie `best-quality` | wie `best-quality` |
| `GET /api/v2/nodes/{id}` | Regeln, in allen Profilen gleich: zeigt, was ein Knoten mitbringt | wie `llm-free` | wie `llm-free` | wie `llm-free` | wie `llm-free` |
| `POST /api/v2/entities` | spaCy und Wörterbuch der Archive, ohne LLM; F1 0,38; 2,4 s an 1.500 Zeichen (M82) | das LLM nennt die Entitäten mit ihrem Artikeltitel; F1 0,78; 5,8 s und 1.214 Tokens an 1.500 Zeichen (M82, D62) | wie `balanced` | wie `balanced` | wie `balanced` |
| `GET /api/v2/collections/{id}/overview` | Teil 3, ohne LLM; ohne Cache 0,8 bis 6,1 s, mit Cache unter 0,05 s (M82) | wie `llm-free` | wie `llm-free` | wie `llm-free` | wie `llm-free` |

`/knowledge`, `/qa`, `/lehrplan/search` und seit D62 `/entities` nehmen `preset` wie das Kompendium; ohne es gilt
`PRESET_DEFAULT`. Bei `/qa` wählt es nur das Verfahren der Paare, Teil 1 eines Themas entsteht immer ohne LLM (D55);
bei `/entities` die Wege der Erkennung (`methods`). `/nodes` und der Sammlungsüberblick kennen kein LLM und kein
Profil. Die drei Profile ab `best-quality` rechnen in jedem Endpunkt mit 200.000 Tokens je Anfrage, die anderen mit
60.000 (D59, D102). Zeiten und Tokens: M45, ohne LLM auf dem Server, mit LLM im Entwicklungscontainer, das Kompendium
als Server plus die Schritte des LLM; die Güte aus M30, M32, M34 und M36.

## Der Ablauf

![Ablauf von Teil 1](bilder/prozess.svg)

Dieselben Schritte mit allen Optionen, ihrer Güte, Zeit und ihren Tokens, im Stand von Release 2.2.2 mit den vier
Profilen vor D69 (die heutigen Werte je Schritt auf [Methoden, Messwerte und Profile](09-methoden-und-profile.md)); die
Quadrate zeigen, welches Profil welche Option nutzt:

![Jeder Schritt mit seinen Optionen](bilder/prozess_optionen.svg)

Teil 2 (Lehrplanbezüge) und Teil 3 (Sammlungsüberblick) laufen daneben; ein LLM prüft nur in den `best-quality`-Profilen
die Lehrplanelemente von Teil 2 (D58). Die Schritte 1 bis 4 laufen bei jeder Anfrage, Schritt 5 in den beiden
schreibenden Profilen, seit D82 also auch ohne Angabe eines Profils. Ein LLM steht nur bereit, wenn es konfiguriert ist:
`LLM_ENABLED=true` und `B_API_KEY`, Modell `gpt-6-luna` (`B_API_MODEL`, seit D44). Die LLM-Zahlen seit M19 stammen, wo
nicht anders genannt, von `gpt-6-luna`, ältere wie die der Text-Schalter vom 18. und 19.09.2026 von `gpt-5.6-luna`;
`gpt-6-luna` erreicht dieselbe Güte mit gleich bis 12 % mehr Tokens zum halben Preis je Token, antwortet aber je Aufruf
ein Viertel bis drei Viertel langsamer (M19). Ohne LLM oder bei einem Ausfall der b-api laufen alle Schritte
regelbasiert, und das Audit der Antwort nennt den tatsächlich genutzten Weg.

## Schritt 1: Hauptartikel finden

Der Dienst bereinigt das Thema („Physik: Optik in Klasse 7“ wird zu *Optik* mit dem Fach Physik als Kontext) und
sucht dann den Artikel, um den sich der Korpus dreht.

| Verfahren | Wie es arbeitet |
|---|---|
| v2.0.0 (nur zum Vergleich) | exakter Titel oder Weiterleitung; bei einer Begriffsklärung zählt, wie oft die Wörter der Anfrage wörtlich im Anfang jeder Bedeutung stehen; sonst Titelvorschläge und Volltextsuche. Nicht mehr wählbar. |
| **Regeln** (`rule-based`) | wie v2.0.0, aber mit den Kontextwörtern des Fachs aus `config/subjects.yaml`, Wortanfängen statt ganzer Wörter, dreifach gewertetem Titel, Personen und Werken erst zuletzt und Regeln für gebeugte Formen und Genitivwendungen. Sie melden, ob sie sich sicher sind (`method`, `confident`). |
| **Regeln und LLM** (`llm`) | erst die Regeln; nur wenn sie unsicher sind, wählt das LLM unter ihren Kandidaten oder nennt einen Titel, der nur zählt, wenn das Archiv ihn als Artikel hat. |
| **Regeln und LLM, gründlich** (`llm-thorough`) | wie `llm`, und das LLM prüft auch eine sichere Auflösung eines Wortes mit mehreren Bedeutungen (D61, Punkt 5). |
| laya (nur zum Vergleich) | ein kleines lokales Entscheidungsmodell (mmBERT-base, 322 Mio. Parameter) wählt an der Stelle des LLM unter den Kandidaten der Regeln. Ohne Nachtraining gemessen; nicht eingebaut (D42). |
| alter Weg (v0.2.0, nur zum Vergleich) | ein LLM nennt bei jeder Anfrage bis zu zehn Begriffe mit vermutetem Wikipedia-Titel, jeder wird nachgeschlagen; einen Hauptartikel wählt er nicht. Nicht eingebaut. |

**Profile:** `llm-free` nimmt `rule-based`, `balanced` `llm` (D53), die drei Profile ab `best-quality`
`llm-thorough` (D61, D69).

| Einstellung | Werte | Standard |
|---|---|---|
| Anfrage: `article_choice` (Kompendium, `POST /api/v2/knowledge` und `/qa`) | `rule-based`, `llm`, `llm-thorough` | aus dem Profil; bei `/qa` mit `topic` `rule-based` in allen Profilen (D55) |
| Anfrage: `preset` | `llm-free` setzt `rule-based`, `balanced` `llm`, die `best-quality`-Profile `llm-thorough` | `PRESET_DEFAULT` |
| Umgebung: `PRESET_DEFAULT` | die fünf Profile | `balanced` (D53); ein Dienst ohne LLM setzt `llm-free` |

| 94 Anfragen in drei Goldsätzen (M9, M16, M17) | v2.0.0 | Regeln | Regeln und LLM | Regeln und laya | alter Weg |
|---|---|---|---|---|---|
| Hauptartikel richtig | 66 (70 %) | 86 (91 %) | 91 (97 %) | 81 (86 %) | 55 (59 %) an erster Stelle, 58 bis 78 unter bis zu zehn Artikeln |
| Zeit | rund 0,03 s | rund 0,03 s | +1,0 bis 2,7 s, nur bei unsicheren Themen | +0,45 s bei unsicheren Themen, 22 bis 61 s Laden und 1,7 GB je Worker | 6 bis 8 s bei jeder Anfrage |
| Tokens | 0 | 0 | rund 950 je Aufruf | 0 | 1.300 bis 1.500 je Anfrage |

![Hauptartikel richtig je Art der Anfrage](bilder/artikelwahl.svg)

**Beobachtungen**

- Gewonnen wird fast nur bei schwierigen Anfragen: mehrdeutige Wörter mit Fach von 19 auf 31 und mit LLM auf 35 von
  38, Anfragen ohne gleichnamigen Artikel von 3 auf 9 von 9. Normale Themen und Klassenzusätze trafen alle Verfahren
  immer.
- Die Selbsteinschätzung der Regeln trägt: Wo sie sich sicher sind, liegen sie 73 von 76 Mal richtig, bei den 18
  unsicheren nur 13 Mal. Das LLM entscheidet genau diese 18 und trifft alle; einen richtigen Artikel der Regeln hat es
  nie verworfen. Die Zeit fällt deshalb selten an: in M13 bei 5 von 30 Themen.
- Die drei übrigen Fehler sind sichere Fehler der Regeln, das LLM wird dort nicht gefragt: „Physik: Leiter“,
  „Physik: Strom“ (beide landen beim allgemeinen Physikartikel) und „Informatik: Netzwerk“. „Physik: Strom“ traf
  v2.0.0 noch, es ist die einzige Anfrage, die schlechter wurde.
- Validierungs- und Testsatz sind nicht mehr unabhängig; unabhängig gemessen ist nur der erste Lauf des Testsatzes,
  7, 8 und 9 von 12.
- Neuere Läufe am selben Gold (M35): Die Regeln treffen 87, `llm` 91 und `llm-thorough` 93 von 94. Behoben wurde
  dazwischen ein Thema, dessen Titel auf einen Abschnitt weiterleitet; `llm-thorough` prüft auch sichere Auflösungen
  mehrdeutiger Wörter (Punkt 5).
- Ein kleines lokales Entscheidungsmodell statt des LLM hilft nicht: laya-multilingual traf ohne Nachtraining 8 der
  18 unsicheren Anfragen, weniger als die Regeln (mit ihnen 81 von 94), und trennte die Volltexttreffer nicht besser
  als Zufall; auf der CPU braucht es 1,7 GB und rund 0,5 s je Entscheidung (M16). Es müsste erst auf unsere
  Entscheidungen trainiert werden und ist nicht eingebaut (D42).
- Der alte Weg über Begriffe vom LLM ersetzt die Artikelwahl nicht (M17): Der richtige Hauptartikel steht 55 Mal an
  erster Stelle und 58 bis 78 Mal unter bis zu zehn Artikeln, bei jeder Anfrage für 6 bis 8 s und rund 1.400 Tokens.
  Er fand aber zwei der drei sicheren Fehler der Regeln, *Elektrischer Strom* und *Rechnernetz*.

**Ein Material als Eingang (D47):** Mit `node_id` ohne `topic` ist der Titel eines Materials nur der Anfang der Suche,
weil er oft ein Format nennt. Ohne LLM nehmen die Regeln den Artikel des Titels, wenn die Begriffe aus Titel und
Beschreibung ihn auch nennen, sonst den ersten Begriff, wenn der Titel ihn nennt, sonst keinen (404 mit der Bitte um
ein `topic`); mit `article_choice=llm` nennt das LLM den Artikel. Mit `topic` und `node_id` zusammen führt das Thema,
und mit `llm` hört eine Frage beides. Zahlen unter 6.

## Schritt 2: Korpus bauen

Aus dem Hauptartikel wird der Korpus: höchstens 12 Artikel und 400 Absätze, im Median 10,5 Artikel.

| Quelle | Wie sie in den Korpus kommt |
|---|---|
| Hauptartikel | immer, als erste Quelle |
| derselbe Artikel aus Klexikon | wenn es ihn gibt, als einfacher Einstieg |
| verlinkte Unterartikel | Links des Hauptartikels, gereiht nach Themenwort im Titel, Treffern in den Überschriften und Häufigkeit der Erwähnung; Jahre, Länder, Maßeinheiten und Listen sind gesperrt; mindestens 350 Zeichen Text |
| Volltexttreffer je Baustein | drei Plätze sind reserviert: je Baustein eine Suche nach Titel und drei Suchbegriffen des Bausteins, bis zu vier Treffer, die das Thema in Titel oder Einleitung nennen und mit dem Hauptartikel verlinkt sein müssen (D48) |
| Artikel eines Materials | mit `topic` und `node_id` zusammen: wenn er ein anderer ist als der Hauptartikel und mit ihm verlinkt, als eigene Quelle ohne Themenfilter (D47) |
| Materialien einer Sammlung (optional) | `knowledge_collection_id`: bis zu 30 Materialien gleich unter welcher Lizenz (D70), je ihre Beschreibung, mit `knowledge_fulltext` ihr Volltext bis 20.000 Zeichen, mit `knowledge_depth` auch aus den Untersammlungen; Bildung und Praxis bevorzugen sie. Am Goldstandard nicht gemessen. |

Artikel ohne das Themenwort im Titel geben nur die Absätze ab, die das Thema nennen. Mit `article_choice=llm` nennt
das LLM seit D63 zuerst den Übersichtsartikel des Themas und bis zu acht Artikel zu seinen Teilen; die davon im Archiv
stehen, kommen an die Stelle der verlinkten Unterartikel und Volltexttreffer, ohne Themenfilter (Punkt 9, M39). Nur
ohne brauchbare Antwort bleibt der Korpus wie oben, und dann benotet das LLM alle Korpusartikel in einem Aufruf, und
Volltexttreffer und verlinkte Unterartikel mit der Note 0 fallen heraus (D48); ohne solche Nebenartikel wird es nicht
gefragt.

| Einstellung | Werte | Standard |
|---|---|---|
| Anfrage: `max_articles` | 1 bis 50 | `CORPUS_MAX_ARTICLES` = 12; Hauptartikel und Klexikon-Zwilling immer |
| Umgebung: `CORPUS_MAX_CHUNKS` | 20 bis 5.000 Absätze | 400 |
| Umgebung: `ZIM_PROFILE` | `compact` (Top-Artikel, 1,4 GB), `standard` (ganze Wikipedia und Klexikon), `extended` (dazu Wikibooks und Wikiversity; nicht empfohlen, D99) | `standard` |
| Anfrage: `knowledge_collection_id` | nodeId einer Sammlung | keine |
| Anfrage: `knowledge_fulltext` | `true`, `false` | `false`: nur die Beschreibungen |
| Anfrage: `knowledge_depth` | 0 bis 5 Ebenen Untersammlungen | 0: nur die Sammlung |
| Übersicht und Teile vom LLM, sonst Prüfung der Nebenartikel | über `article_choice` | an, wo `article_choice` `llm` oder `llm-thorough` gilt (D63) |

| 20 Themen (M25, gpt-6-luna) | gedruckt aus passenden, verwandten, unpassenden Artikeln | gefüllte Inhaltsbausteine | LLM-Aufrufe, Tokens je Thema |
|---|---|---|---|
| bis D48 ohne LLM | 252, 80, 25 | 122 | – |
| **LLM-frei: ohne unverlinkte Volltexttreffer** | 263, 77, 12 | 118 | – |
| bis D48 mit Trefferprüfung | 257, 81, 17 | 120 | 15, 697 |
| **ausgewogen: ohne unverlinkte, dann Prüfung der Nebenartikel** | 264, 77, 5 | 117 | 20, 752 |

Auf 30 neuen Themen kostet `balanced` damit im Median 2,0 s und 935 Tokens mehr als die Regeln (M25; M13 mit
gpt-5.6-luna: 1,7 s und 930).

![Artikel im Korpus nach Herkunft](bilder/korpus.svg)

**Beobachtungen**

- Hauptartikel und Klexikon passen immer; verlinkte Unterartikel zu 9 % nicht, Volltexttreffer zu rund einem
  Drittel. Unverlinkte Volltexttreffer sind zu 10 von 16 unpassend, verlinkte zu 4 von 28 (M25); seit D48 fallen die
  unverlinkten weg und prüft das LLM auch die verlinkten Unterartikel.
- Einfache Filter trennen sie nicht: Das Themenwort in Titel oder erstem Satz zu verlangen verwirft 14 der 16
  unpassenden Treffer, aber auch 7 der 15 zentralen; die Model2Vec-Ähnlichkeit ist bei unpassenden Treffern so hoch
  wie bei guten. Das LLM trennt sie nur, wenn es alle Artikel eines Themas zugleich sieht; die Treffer allein benotet
  es zu mild (6 von 16). Die Verlinkung mit dem Hauptartikel trennt besser als jeder dieser Filter und fängt, was
  gpt-6-luna übersieht: Als Prüfer erkennt es nur 7 der 14 unpassenden Treffer (M25; gpt-5.6-luna 11 von 16).
- Die zwei Bausteine, die mit der Trefferprüfung leer werden, trugen bei „Atommodell“ nur Absätze aus *Kernwaffe*.
- Wikibooks und Wikiversity (`extended`) bringen nichts: Mit ihrer Volltextsuche kam in 20 Themen ein gefüllter Baustein
  dazu (mit Trefferprüfung drei), und aus guten Unterrichtsseiten wie *Physikunterricht/ Optik* druckte der Standard
  keinen Absatz (M11). Dasselbe gilt für Wiktionary, Wikisource, Wikiquote und Wikivoyage: Sie mischten Tabellen, Zitate
  und Listen in den Text (M84, D99, Punkt 16).
- Die Artikel, die N nennt, haben selten eine andere Bedeutung: 16 von 3.309 an den 100 Anfragen von M82, 61 von
  12.447 gedruckten Absätzen (M88). Sie kommen über Weiterleitungen, gleichnamige Artikel, die Übersicht ohne
  Klammerzusatz oder weil N selbst ein anderes Fach nennt; den Artikelanfang oder die Verlinkung zu prüfen kostete 16-
  bis 86-mal so viele passende Artikel (Punkt 18).

## Schritt 3: Absätze zuordnen

Jeder Absatz des Korpus kommt in höchstens einen der zehn Inhaltsbausteine des Templates SC26 oder in keinen. Die
drei übrigen Bausteine (Akteure, Quellen, Glossar) erzeugt der Dienst selbst.

| Verfahren | Wie es arbeitet |
|---|---|
| `lexicon_only` | nur das Überschriften-Lexikon: Ein Absatz bekommt einen Baustein, wenn seine Überschrift ihn nennt („Geschichte“ zeigt auf Entwicklung & Ausblick). |
| `bm25` | BM25 allein: gemeinsame Wörter von Absatz und Bausteinbeschreibung, gewichtet nach Seltenheit. |
| `char_tfidf` | Zeichenfolgen von drei bis fünf Buchstaben; erfasst zusammengesetzte Wörter („Lichtbrechung“ und „Brechung“). |
| **`hybrid_light`** | Lexikon, BM25, Zeichen-TF-IDF und Model2Vec-Vektoren zusammen; eine Regel-Policy entscheidet je Absatz, themenferne Absätze bleiben draußen. |
| `llm` | Das LLM ordnet jeden Absatz einem Baustein oder keinem zu, 50 Absätze zu je 400 Zeichen je Aufruf; wo es nicht antwortet, entscheidet `hybrid_light`. |

**Profile:** `llm-free` und `balanced` nehmen `hybrid_light` (D38), `best-quality` und `best-quality-generated` `llm`
(D53); wo das LLM nicht antwortet, entscheidet `hybrid_light`.

| Einstellung | Werte | Standard |
|---|---|---|
| Anfrage: `matcher` | `hybrid_light`, `bm25`, `char_tfidf`, `lexicon_only`, `llm` | aus dem Profil |
| Anfrage: `preset` | `llm-free` und `balanced` setzen `hybrid_light`, `best-quality` und `best-quality-generated` `llm` | `PRESET_DEFAULT` |
| Umgebung: `MODEL2VEC_PATH` | Pfad des Modells | im Image `/models/m2v`; ohne Model2Vec fällt `hybrid_light` auf 0,38 |
| Umgebung: `LLM_MAX_TOKENS_PER_REQUEST`, `LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY` | Tokens je Anfrage in `llm-free` und `balanced`, in den `best-quality`-Profilen | 60.000: vier Stapel zugleich, weitere warten (D39); 200.000 (D59, D102): gut dreimal so viele |
| Umgebung: `BLOCK_BUDGET_FACTOR` | Faktor auf die Absätze, die ein Baustein beim Zuschnitt behält, und die Zeichen, ab denen er schließt; 1 bis 100 | 10 (D102): am Gold Recall 0,56 und 0,69 statt 0,16 und 0,22, Precision gleich (M86) |

| Verfahren | macro-F1, gelabelte Absätze | macro-F1, alle Absätze | Zuordnung je Thema | Teil 1 | Tokens |
|---|---|---|---|---|---|
| `llm` | 0,72 und 0,69 (zwei Läufe) | nicht gemessen | 10,8 und 22,2 s | 12,0 und 22,7 s | im Mittel 34.500 (18.800 bis 45.900) |
| **`hybrid_light`** | 0,43 | 0,45 | 0,30 s | 1,2 und 1,8 s | 0 |
| `char_tfidf` | 0,40 | 0,42 | 0,25 s | – | 0 |
| `bm25` | 0,36 | 0,37 | 0,03 s | – | 0 |
| `lexicon_only` | 0,35 | 0,35 | 0,02 s | – | 0 |

Zwei Zeitwerte bei `llm` und `hybrid_light`: M13 und M14, an verschiedenen Themen und Tagen. In M14 antwortete die
b-api langsamer, und Themen ab fünf Stapeln (rund 200 Absätze) brauchten eine zweite Runde. Teil 1 der übrigen
lokalen Verfahren wurde nicht eigens gemessen; ohne die Zuordnung dauert er rund 0,9 s. Mit `gpt-6-luna` kam das LLM
auf 0,70 (M19); im Kompendium kostet es rund 170 Tokens je Absatz und im Median rund 11 s (M27). `hybrid_light` kommt
mit dem Code vom 25.09.2026 auf 0,447 bei den gelabelten und 0,459 bei allen Absätzen, `balanced` auf 0,450 und
0,460 (M27); die übrigen Zeilen stammen aus M15.

![Güte gegen Zeit der Zuordnung](bilder/zuordnung_guete_zeit.svg)

![F1 je Baustein](bilder/zuordnung_bausteine.svg)

**Beobachtungen**

- **Unterschiede nur in bestimmten Bausteinen.** Bei den großen Bausteinen liegen alle lokalen Verfahren gleichauf:
  Themendefinition 0,68 bei allen vier, Fachinhalte 0,69 bis 0,70, Entwicklung & Ausblick 0,70 bis 0,74, Gliederung
  & Systematik 0,57 bis 0,60. Der ganze Abstand von 0,35 auf 0,43 entsteht in drei kleinen Bausteinen, zu denen
  Artikel selten eine passende Überschrift haben: Bildung (0,00 bis 0,50), Regularien & Rahmensetzung (0,00 bis 0,25)
  und Beruf & Wirtschaft (0,15 bis 0,27), zusammen 21 der 597 Gold-Absätze. Bei Gesellschaftlichem Kontext und Praxis
  liegt das reine Lexikon sogar leicht vorn (M15).
- **Das LLM hebt fast jeden Baustein**, am stärksten die, an denen die lokalen Verfahren scheitern: Beruf &
  Wirtschaft von 0,27 auf 0,80, Gesellschaftlicher Kontext von 0,41 auf 0,78 bis 0,80, Praxis von 0,19 auf 0,58 bis
  0,69, Regularien von 0,25 auf 0,67. Auch die großen gewinnen: Fachinhalte 0,70 auf 0,86. Nur Querschnitt & Bezüge
  (3 Gold-Absätze) trifft niemand verlässlich.
- **Kleine Bausteine streuen.** Mit 2 bis 18 Gold-Absätzen springt ihr F1 zwischen zwei LLM-Läufen um bis zu 0,4
  (Praxis 0,58 und 0,69, Themendefinition 0,91 und 0,76); die großen bleiben stabil.
- **Schwerere Modelle helfen nicht.** Im selben Ablauf kamen MiniLM-Satzvektoren auf 0,37, ein Frage-Antwort-Modell
  auf 0,37 und ein Cross-Encoder auf 0,29, bei 4 bis 73 s je Thema; als Umsortierung verschlechtert der Cross-Encoder
  den Standard auf 0,32 (M4, M5).
- **Das LLM nur für unsichere Absätze** (47 % der Absätze, halbe Tokens) brachte 0,54 und so viele Fehlzuordnungen
  wie die Regeln; die Policy liegt auch bei ihren sicheren Absätzen zu 39 % falsch (M12). Verworfen.
- **Mögliche Vereinfachung ohne Qualitätsverlust:** BM25 mit Model2Vec erreicht 0,43 (alle Absätze 0,44) in 0,05 statt
  0,30 s. Als Strategie ist das nicht wählbar.
- **Das Budget je Baustein verwirft gute Absätze.** Mit doppeltem bis zehnfachem Budget bleibt die Precision des
  Gedruckten am Gold gleich (Regeln 0,64, LLM 0,75 bis 0,77), der Recall steigt von 0,16 auf 0,56 und von 0,21 auf 0,66
  (M86, Punkt 17). Seit D102 gilt darum das Zehnfache (`BLOCK_BUDGET_FACTOR`).

## Schritt 4: Text bauen und optional umformulieren

Der Text entsteht immer erst extraktiv: Je Baustein übernimmt der Dienst die zugeordneten Absätze wörtlich, ihre
ersten Sätze bis zum Längenbudget, jeden mit Belegnummer; dazu erzeugt er Akteure, Quellen und Glossar. Darauf setzen
drei Schalter auf.

| Schalter | Werte | Standard | Was er tut |
|---|---|---|---|
| `extraction` | `rule-based`, `llm` | `rule-based` in allen Profilen | `llm`: Das LLM wählt je Baustein Sätze aus den Absätzen, die ihm die Zuordnung gibt, aufgefüllt mit den nächstbesten bis acht (`LLM_EXTRACTION_CANDIDATES`); der Wortlaut bleibt der der Quelle. Die Auswahl schließt beim Zeichenbudget der Vorlage, ohne `BLOCK_BUDGET_FACTOR`; mit dessen Vorgabe 10 bekommt sie bis zu zehnmal so viele Kandidaten (D102, nicht gemessen). |
| `generation` | `rule-based`, `llm-fast`, `llm` | `llm` in `best-quality-generated` und `best-coverage-generated`, sonst `rule-based` | `llm-fast`: Das LLM schreibt Themendefinition und Querschnitt & Bezüge neu (`LLM_FAST_SECTIONS`); `llm`: alle Inhaltsbausteine. |
| `enrichment` | `sources-only`, `model-knowledge`, `model-knowledge-full` | `model-knowledge` in `best-quality-generated`, `model-knowledge-full` in `best-coverage-generated`, sonst `sources-only` | `model-knowledge`: Das schreibende LLM darf eigenes Wissen ergänzen, ohne Belegnummer und im Markup gekennzeichnet, sichtbar als `[Modellwissen]` nur mit `model_knowledge_label` (D56, D76); nur mit `generation` `llm` oder `llm-fast`. `model-knowledge-full` (D69): Das LLM schreibt jeden Inhaltsbaustein vollständig über das angefragte Thema, Belege nur, wo sie es treffen, sonst Modellwissen, auch ohne Belege; die Ziellänge ist Untergrenze. |
| `target_length` | 2.000 bis 60.000 Zeichen | 30.000 in jedem Profil (D70, bis dahin 12.000) | steuert die Länge über Budgets je Baustein; eine Richtgröße, keine Obergrenze |
| `empty_slot_policy` | `omit`, `note` | aus dem Template, bei SC26 `omit` | leere Bausteine weglassen oder mit Hinweis zeigen |

**Kombinierbar:** `extraction` und `generation` lassen sich zusammen einschalten, `enrichment` wirkt nur mit
`generation`. Ein Schalter der Anfrage geht dem Profil vor: `extraction=llm` lässt sich in jedem Profil zuschalten,
in der Prüfansicht mit dem Kästchen „KI wählt die Sätze“ beim Profil (D103). Alle LLM-Schalter teilen sich das Budget je Anfrage (`LLM_MAX_TOKENS_PER_REQUEST`, 60.000, in den
`best-quality`-Profilen `LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY`, 200.000, D59, D102) und, wenn gesetzt, ein
Tagesbudget (`LLM_DAILY_TOKEN_BUDGET`; die Vorgabe 0 setzt keine Grenze, D67). Ein geschriebener Satz bleibt nur, wenn
er eine gültige Belegnummer trägt und mindestens 20 % seiner Inhaltswörter im zitierten Absatz stehen; sonst wird er
gestrichen (`LLM_UNSUPPORTED_SENTENCES=drop`) oder als Schlussfolgerung markiert (`mark`).

| Schalter | Zeit | Tokens | Güte |
|---|---|---|---|
| extraktiv (ohne LLM) | 1,1 s auf dem Server, samt Akteuren, Quellen, Glossar | 0 | jeder Satz wörtlich im zitierten Absatz (432 von 432) |
| `extraction=llm` | rund 11 s | 14.000 bis 22.400 | 14 richtige Absätze mehr bei gleicher Präzision (59 %) gegenüber derselben Konfiguration ohne LLM; kleine Bausteine oft falsch |
| `extraction=llm` beim zehnfachen Bausteinbudget (M89) | rund 6 s mehr | rund 31.000 bis 33.000 mehr | Texte ein Drittel so lang, lesbarer, weniger Fehler, aber Nutzen 3,1 statt 3,8 (`balanced`) und 3,4 statt 4,2 (`best-quality`); Punkt 19 |
| `generation=llm-fast` | 9 bis 15 s | 2.300 bis 4.000 | flüssiger Einstieg; Belegprüfung |
| `generation=llm` | 16 bis 20 s | 10.500 bis 14.500 | flüssiger Text; Belegprüfung, im Median 73 % der Inhaltswörter im zitierten Absatz |
| beide auf `llm` | 18 s (Optik) | 27.205 (Optik) bis rund 37.000 | |
| `best-quality-generated` gegen `best-quality` (M27, M28, gpt-6-luna) | rund 8,8 s mehr | 4.300 bis 11.600 mehr | Lesbarkeit 4,0 statt 2,5, in 11 von 12 Urteilen vorgezogen; im Mittel 12 Füllsätze je Thema, mit Prompt v2 5 (M31) |

![Zeit und Tokens der Text-Schalter](bilder/text_schalter.svg)

**Beobachtungen**

- Für Maschinen, also Suche, KI-Assistenten und Weiterverarbeitung, ist der extraktive Text der beste: Jeder Satz
  steht wörtlich in seiner Quelle. Für Menschen liest er sich wie eine geordnete Sammlung von Auszügen; dafür ist
  `generation` gedacht.
- `extraction=llm` wurde am 19.09.2026 ohne Model2Vec gemessen. Gegenüber dem heutigen Standard (110 gedruckte Absätze,
  67 richtig, 61 %) sind 131 und 77 (59 %) nur ein Anhaltspunkt; in Querschnitt & Bezüge landeten 7 Absätze, keiner
  richtig. Keine Empfehlung. Mit dem zehnfachen Bausteinbudget maß M89 den Schalter neu: kürzer, lesbarer, weniger
  nützlich (Punkt 19).
- Die übrigen Werte der Text-Schalter stammen vom 18. und 19.09.2026 an vier Themen bzw. an Optik (gpt-5.6-luna). Die
  Lesbarkeit maß M28 an sechs Themen, blind von zwei Gutachtern: Der geschriebene Text liest sich besser (4,0 statt 2,5
  von 5, in 11 von 12 Urteilen vorgezogen), trug aber im Mittel 12 Füllsätze je Thema; zwei Drittel des ergänzten
  Modellwissens waren Füllsätze. Der zweite Prompt (D56) senkt das auf 13 von 50 ergänzten Sätzen und 5 Füllsätze je
  Thema (M31).

## Kosten und Kapazität

| Profil | Tokens je Kompendium mit Teil 1 und 2, Median (Spanne), M82 | Zeit, Median | Kompendien je Million Tokens |
|---|---|---|---|
| `llm-free` | 0 | 2,6 s | ohne Grenze |
| `balanced` | 314 (307 bis 1.234) | 4,6 s | rund 3.200 |
| `balanced` mit `generation=llm-fast` | rund 2.900 bis 4.600 (M45, addiert) | – | rund 220 bis 340 |
| `best-quality` | 59.335 (29.663 bis 73.304) | 12,6 s | rund 17 |
| `best-quality-generated` (Standard) | 63.117 (48.758 bis 92.436) | 23,2 s | rund 16 |
| `best-coverage-generated` | 87.225 (63.683 bis 115.269) | 27,3 s | rund 11 |

M82 maß jedes Profil an den neun Themen von M52 mit Release 2.17.0, nachts im Einmal-Container. Am Nachmittag des
08.10. (M78, nach D93) waren es 313 Tokens und 4,4 s in `balanced`, 56.700 und 15,1 s in `best-quality`, 67.900 und
29,8 s in `best-quality-generated` und 91.800 und 36,7 s in `best-coverage-generated`, vor D93 (M75) 320 und 5,1 s,
48.500 und 20,4 s, 75.600 und 33,9 s und 90.100 und 37,3 s; M45 (Release 2.2.2) maß jedes LLM-Profil auf sechs eigenen
Themen, 576, 49.019 und 60.357 Tokens. Die Tokens folgen der Größe des Korpus, die von Lauf zu Lauf streut; wohin Zeit
und Tokens gehen und was sich daran sparen ließ: Punkt 15.

Große Themen kosten mehr: Wikinger mit 400 Absätzen brauchte in `best-quality` 65.116 Tokens, Transistor in
`best-quality-generated` 134.766 (M45); M27 maß vor D58 und D63 noch 26.267 und 35.376. Mit Teil 2 kommt die Prüfung der
Lehrplanelemente dazu: Demokratie ohne Fach (382 Absätze, 819 Elemente) kostete 137.398 Tokens in `best-quality` und
152.197 in `best-quality-generated` (M33), seit D93 140.600 in `best-quality-generated` und 160.900 in
`best-coverage-generated` (M79). Mit dem zehnfachen Bausteinbudget (D102) brauchte Teil 1 von Demokratie 109.100 Tokens
in `best-quality-generated` und 132.100 in `best-coverage-generated` (M86). Eine Anfrage dieser Profile darf bis 200.000
Tokens ausgeben (D59, D102), die der anderen 60.000, die Prüfung von Teil 2 dazu bis 400.000 aus einem eigenen Budget
(D94); die Grenzen schützen vor Ausreißern, die meisten Anfragen bleiben weit darunter. Ein Tagesbudget
(`LLM_DAILY_TOKEN_BUDGET`) gilt, wenn gesetzt, für alle Anfragen und Worker zusammen; ist es aufgebraucht, fallen
LLM-Schalter bis zum nächsten Tag auf die Regeln zurück. Die Vorgabe 0 setzt keine Grenze (D67).

## Die Empfehlungen im Einzelnen

### `llm-free`: das Optimum ohne Sprachmodell

Anfrage: `{"topic": "Optik", "preset": "llm-free"}`; ein Dienst ohne LLM stellt es als Vorgabe ein:

```
PRESET_DEFAULT=llm-free                 # ausgeliefert ist balanced (D53)
MODEL2VEC_PATH=/models/m2v              # im Image gesetzt; ohne Model2Vec 0,38 statt 0,43
ZIM_PROFILE=standard
CORPUS_MAX_ARTICLES=12
```

Ergebnis: 87 von 94 Hauptartikeln (M35), 12 von 352 gedruckten Absätzen aus unpassenden Artikeln (M25), macro-F1 0,45,
Teil 1 und 2 in 1,6 s ohne Tokens (M27), QA-Paare aus den Regeln über den spaCy-Parse, 58 von 95 mangelfrei in 0,3 s je
Text (M34). Bei einem Material ohne `topic` trifft sie den Hauptartikel mit F1 0,56 bis 0,63; findet sie keinen, fragt
der 404 nach einem `topic`. Keine andere lokale Einstellung war besser: Die übrigen Verfahren verlieren in kleinen
Bausteinen, weitere Archive von Kiwix bringen nichts (M11, M84), schwerere Modelle schaden. `/entities` erkennt mit
`ner` (spaCy) und `dictionary` (Artikeltitel der Archive): an 40 Materialtexten F1 0,38 bei einer Präzision von 0,29 und
einem Recall von 0,55, in rund 0,25 s (M36); allein kommt `ner` auf 0,30, `dictionary` auf 0,35.

### `balanced`: Zeit und Kosten optimiert bei guter Qualität

Anfrage: `{"topic": "Optik", "preset": "balanced"}`. Dafür muss ein LLM konfiguriert sein:

```
LLM_ENABLED=true
B_API_KEY=…                             # aus dem Geheimnisspeicher, nie im Repository
PRESET_DEFAULT=balanced                 # ausgeliefert
```

Ergebnis: 91 von 94 Hauptartikeln. Seit D63 nennt das LLM den Übersichtsartikel und die Teile jedes Themas: 87 statt
45 % der gedruckten Absätze aus passenden Artikeln bei 25 Sammelthemen wie „deutsche Dichter“, 93 statt 73 % bei 20
gewöhnlichen Themen (M39); Teil 1 und 2 rund 4,2 s und 480 Tokens (M39; vorher 3,4 s und 905 Tokens, M27). Bei einem
Material ohne `topic` F1 0,88 bis 0,98. Die Zuordnung maß vor D63 macro-F1 0,45 wie `llm-free` (M27); den Korpus mit
N deckt das Gold nicht mehr ab (M39). QA-Paare aus denselben Regeln wie `llm-free`,
58 von 95 mangelfrei in 0,3 s je Text (M34, D57, D60). `/entities` lässt das LLM die Entitäten mit ihrem
Artikeltitel nennen (`methods: llm`, D62): F1 0,78 bei einer Präzision von 0,70 und einem Recall von 0,89, rund 800
Tokens und 4 s je Text; durch den Endpunkt nachgemessen mit denselben Artikeln wie im Versuch (M36). Ohne `preset`
gilt auch dort dieses Profil, auf einem Server ohne LLM also ein 503. Wer einen lesbaren Einstieg braucht, ergänzt
`"generation": "llm-fast"`: 9 bis 15 s und 2.300 bis 4.000 Tokens mehr für Themendefinition und Querschnitt
(gpt-5.6-luna, 18.09.2026).

### `best-quality`

Anfrage: `{"topic": "Optik", "preset": "best-quality"}`, mit konfiguriertem LLM wie oben. Das Profil rechnet
mit einem eigenen, größeren Budget je Anfrage (D59, D102), ausgeliefert:

```
LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY=200000   # rund dreimal so viele Stapel der Zuordnung zugleich wie bei
                                                 # 60.000 und Platz für das zehnfache Bausteinbudget, auch beim
                                                 # breitesten Thema (D102, M86)
```

Ergebnis: 93 von 94 Hauptartikeln - das LLM prüft auch sichere Auflösungen mehrdeutiger Wörter (M35, D61) -,
macro-F1 0,70 (M19, gpt-6-luna), Teil 1 und 2 rund 14 s (11 bis 16 s), im Median 26.267 Tokens, rund 170 je Absatz
(M27); ein geprüftes Wort kostet rund 800 Tokens und 1 s mehr. Seit D63 nennt das LLM auch hier Übersicht und Teile
jedes Themas wie in `balanced`; Zuordnung, Zeit und Tokens dieses Profils sind vorher gemessen. Der Text bleibt wörtlich und belegt. QA-Paare vom LLM, 99 von 120 mangelfrei
(M30). `/entities` wie `balanced` (F1 0,78). Die zusätzliche Prüfung jeder Verknüpfung durch das LLM (`link_check:
llm`) ist in keinem Profil voreingestellt: Präzision 0,94 statt 0,70, aber Recall 0,64 statt 0,89 und F1 0,76, rund
820 Tokens und 2 s mehr (D62) - für Aufrufer, die eine kurze, sichere Liste brauchen.

### `best-quality-generated` (Standard)

Anfrage: `{"topic": "Optik"}` genügt, seit D82 der Standard, mit LLM und Budget wie bei `best-quality`.

Ergebnis: wie `best-quality`, dazu schreibt das LLM jeden Baustein und darf eigenes Wissen ergänzen, sichtbar
gekennzeichnet mit `[Modellwissen]`; rund 24 s (19 bis 28 s) und im Median 35.376 Tokens (M27), mit dem zweiten Prompt
rund 3 % mehr (M31). Zwei blinde Gutachter zogen den geschriebenen Text in 11 von 12 Urteilen dem wörtlichen vor
(Lesbarkeit 4,0 statt 2,5 von 5, Zusammenhang 4,0 statt 2,4), bei ähnlich vielen Fachfehlern, die meist schon in den
Quellen stehen (M28). Mit dem zweiten Prompt (D56) sind 13 von 50 ergänzten Sätzen Füllsätze statt 50 von 82, 32 statt
27 fachlich und keiner nach beiden Gutachtern falsch; im Mittel bleiben 5 Füllsätze je Thema statt 12, und v2 wurde in 8
von 12 Urteilen vorgezogen (M31). Wer den geschriebenen Text ohne Modellwissen will, setzt `"enrichment":
"sources-only"`; dann bleibt jeder Satz belegt. `/entities` wie `balanced`.

### `best-coverage-generated`

Anfrage: `{"topic": "OER-Förderungen", "preset": "best-coverage-generated"}`, mit LLM und Budget wie bei
`best-quality`.

Ergebnis: wie `best-quality-generated`, aber das LLM schreibt jeden Inhaltsbaustein über das Thema, wie es angefragt
ist, mit seinem Aspekt (`enrichment: model-knowledge-full`, D69): Belege nur, wo sie das Thema treffen, sonst
gesichertes Modellwissen, sichtbar gekennzeichnet, auch für einen Baustein ohne Belege; die Ziellänge ist Untergrenze,
und Überschrift und `topic` nennen das angefragte Thema. An acht Themen mit Aspekt bewerteten zwei blinde Gutachter
die Passung mit 4,81 statt 1,81, den Nutzen mit 4,81 statt 2,12 und die Vollständigkeit mit 5,0 statt 1,7 von 5,
ohne schwere Fehler; auf zwei Kontrollthemen blieb es beim Thema und war nützlicher, mit 2,25 statt 1,0 leichten
Fehlern je Text, vier von neun schon aus den Quellen (M47). Teil 1 kostet rund 28 s und 91.000 bis 99.000 Tokens,
rund ein Drittel davon aus dem Prompt-Cache (M46), und wird mit rund 30.000 Zeichen zweieinhalbmal so lang. Den
größten Teil schreibt das Modell aus eigenem Wissen (im Median 123 gekennzeichnete Sätze gegen 34 Belegnummern);
für Texte, die die Redaktion prüft. Mit `"matcher": "hybrid_light"` kostet es rund 35.000 Tokens und 16 s, bei
Passung 4,56 und Nutzen 4,31.

## Was die Zahlen nicht sagen

- Die Goldlabels hat ein Sprachmodell vorgeschlagen (Claude), eine Redaktion hat sie nicht geprüft. Ein LLM als
  Zuordner teilt womöglich dessen Sicht; eine Gegenprobe mit einem anderen Modell auf fremden Themen steht aus.
- Kleine Bausteine haben 2 bis 18 Gold-Absätze; ihre Werte streuen zwischen Läufen um bis zu 0,4.
- Die Zeiten stammen vom Entwicklungsrechner (M13, M14, M27) oder vom Server (M1, M3), die LLM-Zeiten hängen am Tag:
  Die b-api antwortete in M14 langsamer als in M13. Denselben Prompt beantwortet ihr Zwischenspeicher in
  Zehntelsekunden; deshalb misst M27 die Zeit jedes Profils auf eigenen Themen.
- Die Profile sind an je sechs Themen gemessen (M27, M30, M31); Lesbarkeit, Modellwissen und QA-Paare haben zwei
  Claude-Gutachter blind bewertet (M28 bis M31), keine Redaktion. Das Maß schwankt zwischen zwei Läufen: Dieselben 29
  Paare aus dem Parse hielten beide Gutachter in M29 bei 1, in M30 bei 9 für mangelfrei; die LLM-Paare und das
  Modellwissen des ersten Prompts bewerteten sie beide Male fast gleich (M30, M31).
- Die Artikel von Materialien (D47) sind an 80 Materialien gemessen, die Claude beschriftet hat; ob der Artikel eines
  Materials neben einem Thema das Kompendium besser macht, ist nur auf Artikelebene gemessen.

## Zu entscheiden

1. **Vorgabe im Betrieb:** entschieden (D53): `balanced`, seit D82 `best-quality-generated`; ohne LLM läuft eine
   Anfrage ohne Profil mit `llm-free` (D68). Vor dem nächsten Deployment brauchen die Server `LLM_ENABLED` und den
   Produktivschlüssel in `B_API_KEY`.
2. **Beste Qualität als eigener Weg:** entschieden (D53) als Profil `best-quality`, rund 26.000 Tokens und 14 s je
   Kompendium (M27).
3. **Lesefassung:** entschieden (D53) als Profil `best-quality-generated`; gemessen in M28: Der geschriebene Text liest
   sich besser (4,0 statt 2,5 von 5, in 11 von 12 Urteilen vorgezogen). Das Modellwissen ist seit D56 im Text sichtbar
   gekennzeichnet (`[Modellwissen]`, Jan), und der zweite Prompt verlangt eine prüfbare Sachaussage oder nichts: 13
   statt 50 Füllsätze bei 50 statt 82 ergänzten Sätzen (M31). Rhetorische Fragen sind seit D60 raus:
   Eine Frage ist keine prüfbare Sachaussage, ohne Beleg fällt sie weg statt als Modellwissen markiert zu bleiben -
   in M31 drei der 13 übrigen Füllsätze.
4. **Goldstandard prüfen lassen:** Alle Gütezahlen hängen an Labels, die eine Redaktion noch nicht gesehen hat.
5. **Sichere Fehler der Regeln:** entschieden und gebaut (D61, Jan: „mehrdeutige Wörter prüfen“). Mit
   `article_choice=llm` prüft das LLM nur unsichere Auflösungen. Prüft es auch sichere Auflösungen mehrdeutiger
   Wörter - über eine Begriffsklärung oder als exakter Titel, zu dem es eine Begriffsklärungsseite gibt -, kommt die
   Artikelwahl am Gold auf 93 statt 91 von 94 (nur Begriffsklärungen: 92), und keine der 44 richtigen Auflösungen, die
   es zusätzlich sah, wird falsch (M35). Der Preis: Das LLM wird bei 64 statt 18 von 94 Anfragen gefragt, je
   zusätzlicher Frage rund 800 Tokens und 1 s. Eingebaut als `article_choice: llm-thorough`, eingeschaltet wie
   vorgeschlagen in den beiden `best-quality`-Profilen, wo 800 Tokens neben 26.000 kaum zählen; `balanced` bleibt bei
   `llm` (dort hieße es im Mittel rund 450 Tokens und 0,5 s mehr je Anfrage für zwei Treffer auf 94), eine Anfrage kann
   `llm-thorough` einzeln setzen. Dabei behoben (`20aaca4`): Ein Thema,
   dessen Titel im Archiv auf einen Abschnitt weiterleitet („Gedicht“, „Nenner“), baute auf eine fast leere Seite.
6. **QA-Verfahren je Profil:** entschieden (D57). `llm-free` und `balanced` fragen mit den Regeln, die beiden
   `best-quality`-Profile mit dem LLM; die zwei kleinen Modelle (in M30 25 von 120 mangelfrei, rund 25 s je Text,
   1,3 GB je Worker) und `parse-based` sind aus Code und Image entfernt. Die vier alten Vorlagen bleiben nur als
   Rückfall, wenn das spaCy-Modell fehlt.
7. **Regeln der QA verbessern:** umgesetzt (D60, Jan: gibt ein Text wenig her, füllen Glossar und Akteure auf).
   Drei Sperren ohne Modell - der Satz endet vor einem zweiten, mit „und“ angehängten Verb, ein Maßverb fragt nicht
   „Was“ oder „Worauf“, eine Frage braucht ein Nomen, einen Namen oder eine Zahl ihres Satzes -, und Glossar und
   Akteure füllen auf, bevor ein Satz zweimal gefragt wird. Nachgemessen an den Texten und Bögen von M30 (M34): 58
   statt 46 von 95 Paaren mangelfrei bei beiden Gutachtern. Die meisten übrigen Mängel sind Fragen, die ohne den Text
   nicht zu verstehen sind („Wo befinden sich die Kurszentren?“), und Nachbar-Personen, die die Gutachter trivial
   nennen („Wer war Immanuel Kant?“ zu Ernst Abbe).
8. **Budget je Anfrage für `best-quality`:** entschieden (D59, Jan): Die beiden `best-quality`-Profile (seit D69 auch
   `best-coverage-generated`) rechnen mit 180.000 Tokens je Anfrage, seit D102 mit 200.000
   (`LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY`), in jedem Endpunkt, auch in der Lehrplansuche, die seither die Profile
   nimmt; `llm-free` und `balanced` bleiben bei 60.000. Jan wollte zuerst 120.000; damit prüfte das Kompendium mit Teil
   1 und 2 beim breitesten Thema (Demokratie ohne Fach, 382 Absätze, 819 Elemente) nur 579 Elemente. Ohne Grenze
   brauchte es 137.398 Tokens in `best-quality` und 152.197 in `best-quality-generated` (M33); Jan gab frei, das Budget
   zu erhöhen, und bei 180.000 prüften beide alle 819.
9. **Sammel- und Mischthemen („deutsche Dichter“):** entschieden und gebaut (D63; Jan, 26. und 27.09.2026): `llm-free`
   bleibt ohne LLM, die neue Frage N stellt das konfigurierte Modell (`gpt-6-luna`) ab `balanced` in allen höheren
   Profilen (Option C), nachgemessen in M39. Ohne großes LLM ist ihre Wirkung nicht erreichbar, weder mit spaCy und
   dem Archiv (M38) noch mit kleinen lokalen Modellen (M40), und `llm-free` bleibt, wie es ist (Jan nach M40, Weg (a)
   am Ende dieses Punkts).

   *Ausgangslage vor D63.* Der Dienst sucht zu jedem Thema genau einen Hauptartikel - über den Titel (genau, gebeugt,
   als Weiterleitung, über eine Begriffsklärung), sonst über Titelvorschläge und die Volltextsuche - und baut um ihn
   den Korpus: den Klexikon-Zwilling, die Unterartikel, auf die er verlinkt, und die mit ihm verlinkten
   Volltexttreffer. `balanced` und die `best-quality`-Profile lassen das LLM entscheiden, wo die Regeln unsicher sind,
   und unpassende Nebenartikel verwerfen. Ein Thema, das kein eigener Artikel ist - eine Gruppe wie „deutsche Dichter“
   oder die Verbindung zweier Themen wie „Klimawandel und Landwirtschaft“ -, erkennt keiner dieser Schritte als
   solches.

   *Die vier gemessenen Wege*, je Teil 1 im Ablauf des Dienstes mit wörtlichem Text, am Beispiel „deutsche Dichter“:
   - R, `llm-free` wie heute: „deutsche Dichter“ ist in der Wikipedia eine Weiterleitung auf *Liste deutschsprachiger
     Lyriker*, die Regeln halten das für sicher. Gedruckt werden die Liste, eine Liste von Anthologien, *Gedicht* und
     drei wenig bekannte Lyriker.
   - B, `balanced` wie heute: dasselbe, denn das LLM wird nur bei unsicheren Treffern gefragt. Bei unsicheren Gruppen
     hilft es („Philosophen der Aufklärung“: *Philosophes* statt *Böse Philosophen*), bei Verbindungen nicht
     („Klimawandel und Landwirtschaft“ bleibt bei *American Farm Bureau Federation*).
   - A, der Weg der alten App: ein Aufruf mit dem Prompt ihres Entitäten-Linkers, wortgleich - bis zu zehn Entitäten
     mit ihrem genauen Wikipedia-Titel, dazu eine lange Liste von Bildungsaspekten. Die gefundenen Artikel sind der
     Korpus, der erste ist der Hauptartikel. „deutsche Dichter“: Goethe, Schiller, Heine, Rilke, Hölderlin, Brecht,
     Droste-Hülshoff und zuletzt *Deutschsprachige Literatur*; Hauptartikel wird Goethe.
   - N, eine neue Frage: Das LLM nennt zuerst den Übersichtsartikel - bei einer Gruppe die Epoche, Gattung oder den
     Oberbegriff, ausdrücklich keine Liste - und dann bis zu acht Artikel zu den wichtigsten Vertretern, Teilen oder
     Aspekten. Der Übersichtsartikel wird Hauptartikel, die anderen kommen ganz in den Korpus, an Stelle der
     Unterartikel und Volltexttreffer. „deutsche Dichter“: *Deutschsprachige Literatur* mit Walther von der
     Vogelweide, Opitz, Schiller, Goethe, Heine, Droste-Hülshoff, Rilke und Brecht.

   A und N bauen den Korpus beide aus Artikeln, die das LLM nennt; der Unterschied ist die Frage. A fragt nach
   Entitäten ohne Rangfolge, und der erste Name wird Hauptartikel - oft ein Vertreter oder ein Nachbarbegriff
   (*Barock* statt *Barockliteratur*). N fragt nach der Übersicht und ihren Teilen.

   *Gemessen* wurde an 25 Sammel- und Mischthemen und zur Kontrolle an 20 gewöhnlichen Themen (M1). Jeden Artikel, aus
   dem ein Weg druckte, benoteten zwei Gutachter blind: 2 gehört zum Thema, 1 verwandt, 0 passt nicht. Gezählt wird
   der Anteil der gedruckten Absätze aus Artikeln mit Note 2; brauchbar ist ein Kompendium, bei dem es mindestens die
   Hälfte ist.

   | Weg | 25 Sammel- und Mischthemen | 20 gewöhnliche Themen | LLM je Thema |
   |---|---|---|---|
   | R `llm-free` heute | 43 %, 11 brauchbar | 71 %, 16 brauchbar | - |
   | B `balanced` heute | 45 %, 10 | 73 %, 18 | Artikelwahl und Prüfung der Nebenartikel, 900 bis 1.400 Tokens |
   | A alte App | 63 %, 16 | 70 %, 13 | 1.516 Tokens, 5,6 s |
   | N neue Frage | 87 %, 21 | 93 %, 19 | 493 Tokens, 3,5 s |

   N füllt dabei nicht weniger Bausteine (9,2 statt 8,5 bei den Sammelthemen, 8,8 statt 8,4 bei den gewöhnlichen).
   Bei gewöhnlichen Themen nennt N als Übersicht immer den Artikel, den auch die Regeln nehmen; dort kommt der
   Gewinn allein aus den Teilen, die die oft nur verwandten Unterartikel und Volltexttreffer ersetzen. Verbindungen
   zweier Themen bleiben auf jedem Weg schwach (N 53 %): Einen Artikel über beide Hälften gibt es selten.

   *Mögliche Änderungen je Profil*, als Anteil passender Absätze bei Sammelthemen / gewöhnlichen Themen. Die Zahlen
   der Optionen sind aus denselben Läufen nachgerechnet: je Thema der Weg, den die Option nähme.

   | Option | `llm-free` | `balanced` | `best-quality`, `best-quality-generated` |
   |---|---|---|---|
   | A: nichts ändern | 43 % / 71 % | 45 % / 73 % | Korpus wie `balanced` |
   | B: N nur, wo die Regeln kein Thema treffen (Titelvorschlag, Volltexttreffer, Listenseite) | bleibt | 74 % / 74 %; fragt bei 19 von 25 Sammelthemen, 1 von 20 gewöhnlichen und 5 von 94 Gold-Anfragen | wie `balanced` |
   | C: N bei jedem Thema; den Hauptartikel ersetzt N nur, wo B fragen würde | bleibt | 87 % / 93 %; je Kompendium rund 2 s mehr (3,5 s Frage statt 1,4 s Prüfung der Nebenartikel), rund 500 statt 900 Tokens | wie `balanced` |
   | D: B in `balanced`, C in den `best-quality`-Profilen | bleibt | 74 % / 74 % | 87 % / 93 % |

   `llm-free` bleibt in jeder Option, wie es ist: Ohne LLM nennt niemand Übersicht und Teile. Denkbar, aber nicht
   gemessen, wäre eine Regel, die bei einer Listenseite Einträge als Teile nimmt; die Archive kennen allerdings keine
   Rangfolge, nach der die wichtigen Einträge zu erkennen wären. Wo B nicht fragt, nennt N denselben Hauptartikel wie
   die Regeln (6 von 6 Sammelthemen, 19 von 19 gewöhnlichen), deshalb reicht es in C, den Hauptartikel nur dort zu
   ersetzen. Die `best-quality`-Profile wurden an diesen Themen nicht eigens gemessen: Ihr Korpus entsteht wie der
   von `balanced`, die Zuordnung der Absätze macht dort das LLM.

   Vorschlag, nach dem Nachrechnen geändert: C statt D. B trifft zu wenig - die sechs Sammelthemen mit eigenem Artikel
   lösen es nicht aus (*Edelgase* druckt dann weiter aus *Q-Phase (Meteoriten)*), und bei gewöhnlichen Themen fragt
   es fast nie, obwohl N gerade dort die Nebenartikel verbessert. C hebt `balanced` auf 87 und 93 %, kostet rund 2 s
   je Kompendium und spart Tokens. Vor dem Bau zu prüfen: die Artikelwahl an den fünf Gold-Anfragen, bei denen N den
   Hauptartikel ersetzen würde, und die Zuordnung am Gold (macro-F1), deren Absätze aus dem heutigen Korpus stammen.
   Sind die 2 s in `balanced` zu viel, bleibt D.

   *Geht es ohne großes LLM? (M38)* Jan entschied C, fragte aber zuerst, ob spaCy, ein anderes Verfahren ohne LLM oder
   ein kleines, schnelles Modell (höchstens 2 bis 3 s) dieselbe Wirkung erreicht. Gemessen an denselben Themen und mit
   derselben Skala:

   | Weg | Sammelthemen | gewöhnliche Themen | Zeit für die Artikel |
   |---|---|---|---|
   | heute (`llm-free` / `balanced`) | 43 / 45 % | 71 / 73 % | – |
   | ohne LLM: spaCy-Parse und Links des Archivs | 38 % | 71 % | im Median 3,1 s, bis 8,2 s |
   | N mit `meta-llama-3.1-8b-instruct` | 63 % | 63 % | 0,7 s |
   | N mit `qwen3-30b-a3b-instruct-2507` | 88 % | 83 % (zweite Noten 75 %) | 0,6 s |
   | N mit `gpt-6-luna` (M37) | 87 % | 93 % | 3,5 s |

   Die Entitätenerkennung von spaCy findet in einem Sammelthema fast nichts („deutsche“ in „deutsche Dichter“). Parse
   und Archivstruktur finden die Teile nicht: Ohne Wissen darüber, wer wichtig ist, nehmen sie die Links in der
   Reihenfolge der Seite (bei „deutsche Dichter“ Minnesänger vor Goethe), und das Lesen vieler Einleitungen sprengt
   den Zeitrahmen. `llm-free` bleibt deshalb, wie es ist. Ein kleines Modell reicht bei Sammelthemen:
   `qwen3-30b-a3b-instruct-2507` (academiccloud über die b-api, rund 3 Mrd. aktive Parameter) beantwortet die Frage in
   0,6 s ebenso gut wie `gpt-6-luna` in 3,5 s, erfand aber bei zwei Themen alle Titel (dann zählt der Rückfall) und
   liegt bei gewöhnlichen Themen zwischen heute und `gpt-6-luna`. Das 8B-Modell reicht nicht.

   *Entschieden (Jan, 27.09.2026):* Die Frage stellt das konfigurierte Modell (`gpt-6-luna`) in `balanced` und den
   `best-quality`-Profilen; die kleineren Modelle der b-api waren nicht gemeint. Gebaut als D63 (Option C), durch den
   Dienst nachgemessen (M39): in allen 45 Themen derselbe Hauptartikel wie beim Prototyp, 87 statt 45 % passende
   Absätze bei Sammelthemen und 93 statt 73 % bei gewöhnlichen, die Artikelwahl am Gold unverändert bei 91 und 93 von
   94 („Lichtlehre“ wird *Optik*, „Ursachen des Ersten Weltkriegs“ *Julikrise*). Die Frage kostet im Median 3,6 s und
   480 Tokens, ein Kompendium mit Teil 1 und 2 brauchte in `balanced` 4,2 s. Das Gold der Zuordnung deckt den neuen
   Korpus nicht mehr ab: 243 statt 62 der 643 Labels veralten, weil ihre Absätze in den ersetzten Nebenartikeln stehen.

   *Kann `llm-free` besser werden? (M40)* Jan: mit Modellen, die im Dienst selbst laufen - extrahierenden wie GLiNER,
   Flair oder GBERT-Feintunes, generativen wie LFM2, LFM2.5 und Qwen3 0.6B -, in höchstens 2 bis 3 s. Gemessen wurden
   die generativen (Jan gab nur sie frei; die extrahierenden finden Namen in einem Text, wissen aber nicht, welche zu
   einem Sammelthema gehören), mit derselben Frage, denselben Themen und derselben Skala:

   | Weg | Sammelthemen: passend | Absätze | gewöhnliche Themen: passend | Frage auf 4 Threads, Median |
   |---|---|---|---|---|
   | `llm-free` heute | 43 % | 351 | 71 % | – |
   | nur Hauptartikel und Zwilling (`max_articles: 2`) | 76 % | 214 | 94 % | – |
   | N mit LFM2-700M | 59 % | 290 | 92 % | 4,4 s |
   | N mit LFM2.5-1.2B | 61 % | 285 | 74 % | 4,8 s |
   | N mit Qwen3-0.6B | 55 % | 277 | 94 % | 6,3 s |
   | N mit `gpt-6-luna` (`balanced` seit D63) | 87 % | 504 | 93 % | 3,6 s über die b-api |

   Die kleinen Modelle kennen die Vertreter nicht: Von rund neun genannten Titeln hatte das Archiv im Mittel 0,3 bis 2,
   bei 5 bis 18 der 25 Sammelthemen keinen; meist nannten sie das Thema selbst als Übersicht und erfanden den Rest
   („Dichter der deutschen Literatur“, als Komponisten der Klassik „Bach, Johann“ und „Dürer, Martin“). Ihr Gewinn
   kommt aus dem kleineren Korpus, und ohne Modell ist er größer: Nur Hauptartikel und Zwilling bringen 76 und 94 % -
   für ein Drittel weniger Absätze und rund zwei gefüllte Bausteine weniger. In 2 bis 3 s blieben 2 der 135 Fragen.
   Kleine lokale Modelle verbessern `llm-free` also nicht.

   Wege für `llm-free` nach M40:
   - (a) nichts ändern: `llm-free` bleibt der schnelle, freie Weg; wer Sammelthemen braucht, nimmt `balanced`.
   - (b) ein kleinerer Korpus in `llm-free`, etwa `max_articles` 2 oder ohne Volltexttreffer: mehr passende Absätze
     (76 statt 43 % und 94 statt 71 %), aber weniger Text und Bausteine, und die Vertreter einer Gruppe fehlen weiter
     („deutsche Dichter“ bleibt auf der Liste). Gemessen ist nur die Grenze 2; eine Anfrage kann sie schon heute mit
     `max_articles` setzen.
   - (c) N vorab: `gpt-6-luna` beantwortet die Frage einmal für bekannte Themen - die Sammlungen und Themenseiten der
     WLO, die Themen der Lehrpläne -, der Dienst liefert die Antworten als Daten mit, und `llm-free` schlägt dort nach,
     ohne ein LLM zu rufen. Für diese Themen die Wirkung von N, für freie Eingaben nichts; die Liste muss mit neuen
     Archiven erneuert werden, und es wären Daten eines LLM in einem Profil ohne LLM. Nicht gemessen.

   Entschieden: (a) (Jan, 27.09.2026). (b) ändert, was ein Kompendium in `llm-free` ist, und hilft den Sammelthemen
   nicht; (c) lohnte sich erst, wenn die meisten Anfragen aus WLO-Sammlungen kämen. Beide sind nicht gebaut.
10. **Profile für `/entities`:** entschieden und gebaut (D62, Jan: „angemessene Zuordnung der Methoden auf die
    Profile gemäß der Ergebnisse“). Der Endpunkt erkannte ohne LLM (spaCy und ein Wörterbuch der Artikeltitel) und
    nahm kein Profil. An den Texten von 40 echten Materialien kommt das auf F1 0,38 bei einer Präzision von 0,29: Das
    Wörterbuch verknüpft Allerweltswörter („Woche“, „Frage“, „Ich“), und 65 von 394 Verknüpfungen meinen etwas anderes
    als der Text oder haben nichts mit ihm zu tun. Nennt das LLM die Entitäten selbst, mit dem genauen Titel ihres
    Artikels, sind es F1 0,78 bei einer einzigen unpassenden Verknüpfung (rund 800 Tokens, 4 s). Jedes Wort, das das
    LLM nannte, steht im Text, seine Stelle lässt sich also wie bisher angeben.

    Gebaut ist `methods: llm` (dieselbe Frage wortgleich), dazu `preset`: `llm-free` nimmt `ner` und `dictionary`,
    `balanced` und beide `best-quality`-Profile `llm`. Durch den Endpunkt nachgemessen, mit den Noten von M36: `llm-free`
    in allen 40 Texten wie vorher, das LLM wieder F1 0,78 (38 von 40 Texten mit denselben Artikeln; die zwei übrigen
    verknüpft der Endpunkt, wie seit D43, mit der Weiterleitung auf einen Abschnitt statt mit dem Artikel dahinter).
    Die Prüfung durch einen zweiten Aufruf (`link_check: llm`) war im Versuch vorgeschlagen, weil sie dort F1 0,80 bei
    einer Präzision von 0,91 erreichte - der Versuch zeigte ihr aber alle Verknüpfungen eines Textes, auch den Beifang
    der Regeln. Im Endpunkt sieht sie nur, was das LLM nannte, und benotet strenger: Präzision 0,94, aber ein Drittel
    der passenden Entitäten fällt weg, F1 0,76 statt 0,78; rund 820 Tokens und 2 s mehr. Sie bringt den
    `best-quality`-Profilen also keinen Gewinn und steht in keinem Profil; wer eine kurze, sichere Liste will, setzt
    sie selbst. Folge, wie vorgeschlagen: Wie die anderen Endpunkte folgt `/entities` PRESET_DEFAULT (`balanced`) und
    braucht ohne `preset` ein LLM - auf einem Server ohne LLM ein 503, bis der Aufrufer `preset: llm-free` setzt.
11. **Kennungen für Wikidata, DBpedia und die GND (M41 bis M43, D64, D65):** entschieden und gebaut, (a) und (b)
    (D65; Jan: „wenn de.dbpedia.org dauerhaft nicht antwortet dann sollten wir dbpedia.org nehmen“, die GND-Abzüge für
    den Container freigegeben). Jan: `/entities` soll neben Wikipedia möglichst
    genau und treffsicher auch Wikidata-, DBpedia- und DNB-Entitäten vorhersagen, möglichst lokal ohne API, mit den
    Profilen, gemessen, und neue Installationen sollen die Daten bekommen. Seit D43 nennt der Endpunkt zu jedem
    verknüpften Wikipedia-Artikel dessen Kennungen, alle aus lokalen Daten: GND, Art und VIAF aus dem Normdaten-Block
    im ZIM, die Wikidata-Nummer aus dem lokalen Index, die DBpedia-URI aus dem Titel gebildet. Die Kennungen folgen also
    der Verknüpfung, und die wählt das Profil (D62). Gemessen an den Texten der 40 Materialien aus M36 (M41):

    | Profil | Wikidata, DBpedia: Präzision / Recall / F1 | GND: Präzision / Recall / F1 |
    |---|---|---|
    | `llm-free` (Regeln) | 0,29 / 0,55 / 0,38 | 0,33 / 0,61 / 0,43 |
    | `balanced`, `best-quality` (LLM nennt) | 0,70 / 0,89 / 0,78 | 0,69 / 0,88 / 0,77 |
    | mit `link_check: llm` | 0,94 / 0,64 / 0,76 | 0,92 / 0,60 / 0,72 |

    Falsch ist dabei der Artikel, nie die Nummer (M18: 30 von 30 GND-, 29 von 30 Wikidata-Nummern gehören zu ihrem
    Artikel). Das Vorgehen passt also für Wikidata (alle 188 richtigen Artikel haben eine Nummer) und im Kern für die
    GND. Drei Stellen passen nicht oder nur teilweise:

    - *Neue Installationen:* Der Wikidata-Index war Handarbeit. Seit D64 baut ihn der Sidecar `wikidata-updater`
      selbst (echter Lauf auf frischen Volumes: 6 min 16 s, davon rund 2 min Download, danach die Dumps gelöscht), und
      die API übernimmt ihn ohne Neustart. Das ZIM kann die Wikipedia-Dumps nicht ersetzen: 14 der 188 Seiten verlinken
      ihr Wikidata-Objekt, keine hat Sprachlinks.
    - *GND-Lücke:* 49 der 188 richtigen Artikel haben keinen Normdaten-Block. Aus den GND-Abzügen der DNB (CC0,
      270 MB, zweimal im Jahr) bekommen 22 einen Vorschlag, 21 davon richtig (M42 a); 160 statt 139 trügen eine GND.
    - *DBpedia:* `de.dbpedia.org` antwortet nicht mehr, die gebildeten URIs führen ins Leere. DBpedia vergibt seine
      lebenden Kennungen nach dem englischen Artikel; den nennt `langlinks` (329 MB, derselbe Lauf wie der Index) für
      96 % der Artikel, die `balanced` verknüpft (M42 b).

    *Ein lokaler Verknüpfer für `llm-free`?* DBpedia Spotlight (lokal in Docker, Modell von 2022, 4,4 GB RAM)
    verknüpfte dieselben Texte nicht besser als die Regeln: bei gleicher Menge F1 0,37 statt 0,38, aber doppelt so
    oft etwas ganz anderes, meist Namensvettern (140 statt 65, M42 c). `llm-free` bleibt bei den Regeln; wer genaue
    Kennungen braucht, nimmt `balanced` oder setzt zusätzlich `link_check: llm` (Präzision 0,94).

    Nicht lokal machbar oder nicht lohnend: Entitäten ohne Artikel in der deutschen Wikipedia bräuchten die deutschen
    Namen aus Wikidata (Dump 71,6 GB, 17 Mio. deutsche Namen, viele mehrdeutig) oder die ganze GND als Namensliste
    (1,8 GB, 10 Mio. Sätze); fertige Verknüpfer für Wikidata auf Deutsch sind groß, alt oder nicht frei (mGENRE
    CC-BY-NC, BELA 22 GB und archiviert, entity-fishing 11 GB ohne deutsche Messwerte). GND-Schlagwörter für einen
    ganzen Text, wie die DNB sie vergibt, wären eine eigene Aufgabe: Annif mit freien GND-Modellen der finnischen
    Nationalbibliothek (1,8 GB, trainiert auf Titeln und Abstracts der TIB; die DNB erreicht mit eigenen
    Annif-Modellen F1 0,47), nicht gemessen.

    Mögliche Schritte, alle lokal und in allen Profilen gleich, weil keiner ein LLM braucht:
    - (a) GND-Lücke schließen: der Sidecar lädt auch die GND-Abzüge (Sachbegriffe, Geografika, Körperschaften), der
      Endpunkt nimmt die GND aus dem Normdaten-Block und sonst aus dem Abzug, zuerst über Wikidata-`sameAs`, dann über
      den eindeutigen Namen, und sagt, woher sie stammt (`gnd_source`).
    - (b) DBpedia-URI über den englischen Artikel: der Sidecar lädt auch `langlinks`, der Index kennt den englischen
      Titel, `dbpedia` wird `http://dbpedia.org/resource/<englischer Titel>`; ohne englischen Artikel keine URI
      (oder, als Variante, weiter die nicht erreichbare deutsche).
    - (c) nichts ändern.

    Vorschlag: (a) und (b). Beide machen die Kennungen treffsicherer, ohne ein Profil langsamer oder teurer zu machen;
    der Sidecar lädt dann statt 420 MB rund 1 GB, wenn ein neues Archiv kommt. (b) ändert, was Aufrufer im Feld
    `dbpedia` bekommen.

    Entschieden: (a) und (b), in allen Profilen gleich (Jan, 27.09.2026). Gebaut (D65): Der Wikidata-Sync lädt
    `langlinks` mit (zusammen rund 750 MB), `dbpedia` ist `http://dbpedia.org/resource/<englischer Titel>` und ohne
    englischen Artikel weiter die deutsche IRI; der Sidecar `gnd-updater` baut den GND-Index aus Sachbegriffen und
    Geografika (rund 65 MB; die Körperschaften brachten in M42 keinen Vorschlag), der Endpunkt nimmt die GND aus dem
    Normdaten-Block, sonst aus dem Index, und sagt unter `gnd_source`, woher. Nennt der Block eine Art (Person, Werk),
    muss der Satz aus dem Index sie haben. Im Dienst nachgemessen (M43), nachdem ein Blick in den echten Abzug zeigte,
    dass die DNB lange Namenslisten umbricht und der Leser diese Namen verlor (behoben, 1.072.074 statt 933.131
    eindeutige Namen):

    | Profil | Wikidata: Präzision / Recall / F1 | GND: Präzision / Recall / F1 | englischer Artikel für DBpedia |
    |---|---|---|---|
    | `llm-free` | 0,29 / 0,55 / 0,38 | 0,31 / 0,57 / 0,40 (M41: 0,43) | 348 von 394 (88 %) |
    | `balanced`, `best-quality` | 0,70 / 0,89 / 0,78 | 0,70 / 0,88 / 0,78 (M41: 0,77) | 259 von 269 (96 %) |
    | mit `link_check: llm` | 0,94 / 0,64 / 0,76 | 0,93 / 0,62 / 0,75 (M41: 0,72) | 139 von 142 (98 %) |

    160 statt 139 der 188 richtigen Artikel tragen eine richtige GND. An den 139 bekannten Nummern führten der
    Wikidata-Weg in 107 von 109 und der Namensweg in 90 von 91 Fällen zur selben Nummer. In `llm-free` sinkt die
    GND-F1 leicht, weil der Index auch dem Beifang der Regeln eine GND gibt (die Buchstaben „C“ und „M“, „Liste“):
    Die Kennungen folgen der Verknüpfung. Der Wikidata-Sync braucht mit einem Vorfilter für `langlinks` 619 statt
    1.271 s, der GND-Sync 78 s. Methoden und Werte aller Profile stehen auf der Seite
    [Entitäten und Kennungen](08-entitaeten-und-kennungen.md).

    Quellen der Recherche (27.09.2026): data.dnb.de/opendata (GND-Abzüge und ihre Größen), dumps.wikimedia.org
    (Läufe und Tabellen der deutschen Wikipedia), databus.dbpedia.org und downloads.dbpedia.org (Releases, Modell von
    Spotlight), wikidata.org (Statistik der Namen und von P227), huggingface.co/NatLibFi (Annif-Modelle),
    liberquarterly.eu/article/view/19422 (Erschließungsmaschine der DNB).

12. **KI-Stufen über `best-coverage-generated` hinaus** (Jan, 01.10.2026: „das neue profil kann nochmal ki nutzen -
    wir brauchen da eine sinnvolle hochstufung der ki nutzung“): (c) und (e) umgesetzt, (a) gebaut und in M53 gemessen
    (D73), (b) und (d) offen.

    Die Leiter heute, Teil 1 im Median an neun Themen (M52, Stand D72):

    | Profil | was das LLM zusätzlich tut | Tokens | Zeit | Modellwissen im Text | Passung: einfach, Sammelthema, Aspekt |
    |---|---|---|---|---|---|
    | `llm-free` | nichts | 0 | 1,7 s | 0 | 3,0, 1,5, 1,0 |
    | `balanced` | wählt unsichere Artikel, nennt Übersicht und Teile des Themas | 530 | 5,0 s | 0 | 3,7, 2,8, 1,2 |
    | `best-quality` | ordnet jeden Absatz zu, prüft auch sichere Artikelwahlen, prüft die Lehrplanelemente | 59.900 | 16 s | 0 | 4,2, 3,8, 1,7 |
    | `best-quality-generated` | schreibt jeden Baustein zum angefragten Thema, einen ohne Belege ganz aus eigenem Wissen | 84.000 | 30 s | 62 % | 4,8, 4,7, 4,2 |
    | `best-coverage-generated` | schreibt jeden Baustein vollständig zum angefragten Thema | 103.300 | 38 s | 83 % | 5,0, 5,0, 5,0 |

    Drei Befunde aus M48 sagen, wo eine weitere Stufe ansetzen sollte:

    - In `best-coverage-generated` stammen 84 % des Textes aus Modellwissen, und dort stehen sechs der acht leichten
      Fehler (Daten, Gremien, Zuschreibungen); schwere fanden die Gutachter keine. Gegen Quellen geprüft ist nur der
      belegte Rest.
    - Teuer ist die Zuordnung (61.060 Tokens, 12 s), nicht das Schreiben. In `best-coverage-generated` bedient sie nur
      das Sechstel des Textes mit Belegen; mit `matcher: hybrid_light` blieb die Passung in M47 bei 4,56 statt 4,81,
      der Nutzen bei 4,31 statt 4,81, für rund 56.000 Tokens und 11 s weniger.
    - Die Zuordnung durch das LLM verlor in vier von 27 Läufen einen Stapel von 50 Absätzen an eine unlesbare Antwort,
      und die Artikelwahl streut zwischen zwei Läufen: Zwei von drei Sammelthemen bekamen in `best-quality` und
      `best-quality-generated` verschiedene Hauptartikel.

    Vorschlag, in `best-coverage-generated` selbst (dasselbe Profil, mehr KI dort, wo der Text entsteht):

    - (a) **Prüfung des Modellwissens:** Nach dem Schreiben prüft je Baustein ein zweiter Aufruf nur die Sätze mit
      `[Modellwissen]` auf Daten, Namen, Gremien und Zuschreibungen und streicht oder berichtigt, was er für falsch
      hält; die Kennzeichnung bleibt. Das zielt auf die Fehler, die M48 fand. Geschätzt 2.000 bis 3.500 Tokens je
      Baustein, zusammen 20.000 bis 35.000, und 5 bis 10 s, weil die Bausteine parallel laufen. Messen: dieselben neun
      Themen, Fehler je Text vorher und nachher.
    - (b) **Themenplan vor dem Schreiben:** Ein Aufruf legt je Baustein die Kernpunkte des angefragten Themas fest, bei
      Sammelthemen die Vertreter, bei Aspekten die Teilaspekte; alle Bausteine schreiben danach. Der Plan steht in der
      System-Nachricht, für die übrigen Bausteine kommt er aus dem Prompt-Cache. Gegen Wiederholungen zwischen den
      Bausteinen und für die Lesbarkeit (4,1). Geschätzt rund 20.000 Tokens und 5 bis 8 s.
    - (c) **Unlesbare Antworten neu fragen:** Eine unlesbare Antwort der Zuordnung einmal neu stellen, statt 50 Absätze
      den Regeln zu überlassen; seit D70 bekommt die zweite Frage eine frische Antwort. Rund 9.000 Tokens je Fall, in
      allen Profilen mit `matcher: llm`.
    - (d) **Kosten ausgleichen, zur Wahl:** `best-coverage-generated` ordnet mit `hybrid_light` zu und steckt die
      gesparten rund 56.000 Tokens in (a) und (b), mit etwa so vielen Tokens wie heute. Oder es behält `matcher: llm`
      (Jan: höchste Qualität) und kommt mit (a) und (b) auf rund 150.000 Tokens, unter dem Budget von 180.000.
    - (e) **Profil empfehlen:** Löst die Artikelwahl ein Thema auf einen anderen Artikel auf, einen Oberbegriff oder
      einen Vertreter, sagt das die Prüfung des Kompendiums und nennt `best-coverage-generated`, ohne zusätzliche
      Tokens. In M48 betraf das sechs der neun Themen.

    Empfehlung: (c) gleich, weil es einen Fehlerweg schließt; (a) als nächste Stufe, mit Messung; (e) als Hilfe bei der
    Wahl des Profils; (b) und (d) nach den Zahlen von (a).

    **Entschieden (D73, Jan, 02.10.2026: „die offenen punkte beheben“, zu (a) „bauen und messen“):** (c) ist V4 und (e)
    ist V3 aus Punkt 14, beide umgesetzt. (a) ist gebaut als Schalter `model_knowledge_check` (`rule-based`, `llm`;
    Prompt `model_knowledge_check` v1): Nach dem Schreiben liest ein zweiter Aufruf je Baustein dessen Sätze aus
    Modellwissen mit dem Baustein als Zusammenhang und streicht, was er für falsch oder erfunden hält, oder berichtigt
    eine falsche Angabe, die er sicher kennt; die Kennzeichnung bleibt, und ein Baustein nur aus Modellwissen, der jeden
    Satz verliert, fällt auf die Regeln zurück. Gemessen in M53 an den neun Themen, dieselben Läufe vor und nach der
    Prüfung: leichte Fehler je Text 1,1 statt 1,6, Passung, Nutzen und Vollständigkeit gleich, Lesbarkeit 3,9 statt
    4,0, der einzige schwere Fehler blieb; jede Berichtigung stimmte danach, gestrichene Sätze waren aber meist richtig
    oder unklar; rund 27.000 Tokens und 5 s mehr je Text. Nach der vereinbarten Regel kam die Prüfung in
    `best-coverage-generated` auf `llm` (2.6.0). **Revidiert (D74, Jan, 02.10.2026):** „die prüfung scheint nicht viel
    zu bringen … wahrscheinlich sollten wir da erstmal keine ressourcen weiter rein stecken“ - kein Profil prüft, der
    Schalter bleibt für Anfragen, die es wollen. (b) und (d) sind offen.
13. **Länge in `best-coverage-generated`:** entschieden (D70) sind 30.000 Zeichen in allen Profilen. Weil die Ziellänge
    dort Untergrenze ist, schreibt `best-coverage-generated` im Median 57.378 Zeichen (53.000 bis 64.000, M48), fast
    das Doppelte; Zeit und Tokens blieben im Rahmen (37 s, 101.150 Tokens, keine Rückfälle). Wer rund 30.000 Zeichen
    will, gibt dem Profil 15.000 als Vorgabe (`PRESET_TARGET_LENGTH`); eine Anfrage kann es jederzeit mit
    `target_length`. Entschieden (Jan, 02.10.2026): so lassen; wer rund 30.000 Zeichen will, setzt `target_length`.

14. **Die anderen Profile an den Problemstellen von M48** (Jan, 02.10.2026: „bitte vorschlagen, testen und
    empfehlen“): gemessen in M49 am Prototyp; V2 entschieden und erweitert (D72), V1a, V3 und V4 übernommen, V1b nicht
    (D73). Ursache bei den Sammelthemen: Fehlt die Übersicht, die das LLM
    nennt, im Archiv, wird ein Vertreter der Gruppe Hauptartikel (Walther von der Vogelweide, Immanuel Kant).

    | Vorschlag | Wirkung (M49) | Kosten | Empfehlung |
    |---|---|---|---|
    | V3: Hinweis in der Prüfung auf das passende Profil, wenn der Text einen anderen Artikel behandelt als das angefragte Thema | kein Hinweis bei 46 Themen mit eigenem Artikel (Frage N) und bei 35 Goldanfragen mit eigenem Artikel (Wortregel); alle 6 Themen mit Aspekt erkannt, Sammelthemen dort, wo die Übersicht die Gruppe nicht trägt (Frage N: 3 von 6; Wortregel: 3 von 3) | ab `balanced` rund 10 Tokens in der Frage N, in `llm-free` keine | übernehmen |
    | V4: eine unlesbare Antwort der Zuordnung einmal neu fragen | schließt den Fehlerweg, der in M48 vier von 27 Läufen einen Stapel von 50 Absätzen kostete | nur im Fall, rund 9.000 Tokens | übernehmen |
    | V1a: eine Übersicht auch ohne Klammerzusatz suchen („Aufklärung (Philosophie)“ → „Aufklärung“) | derselbe Artikel statt eines Vertreters | keine | übernehmen |
    | V1b: drei Übersichtstitel in Rangfolge | jede Übersicht gefunden (50 statt 38 von 50 Sammelthemen), aber breitere: nach den Noten von M37 gehört der Vertreter eher zum Thema als die Ersatz-Übersicht (2 statt 1) | rund 210 Tokens je Frage N | nicht ohne Textmessung |
    | V2: `best-quality-generated` schreibt über das angefragte Thema, höchstens die Hälfte Modellwissen | Passung bei Sammelthemen 3,33 statt 2,83, bei Aspekten 2,17 statt 1,50; `best-coverage-generated` 4,83 | gleich | wahlweise: hebt das Profil wenig, ändert aber, wovon es handelt |

    Kurz: Für Sammelthemen und Themen mit Aspekt bleibt `best-coverage-generated` das Profil (Passung 4,8 bis 5,0); V3
    sagt das dem Nutzer im Kompendium selbst. V4 und V1a sind kleine Fehlerbehebungen ohne Nebenwirkung. V2 ist eine
    Frage der Ausrichtung: Soll `best-quality-generated` über den gefundenen Artikel schreiben (überwiegend aus
    Quellen) oder über das angefragte Thema (mit weniger Quellenstoff)? Der Prototyp liegt auf dem lokalen Zweig
    `m49-proben`; nach Jans Entscheidung kommen die gewählten Teile mit ihren Tests auf `main`.

    **Entschieden (D72, Jan, 02.10.2026):** „das thema im prompt sollte bei best-quality generated auch das
    angefragte thema und nicht der gefundene artikel sein - das sollte eigentlich für alle profile gelten“ und „bei
    best quality generated sollten auch leere bausteine aus modellwissen geschrieben werden“. Gebaut auf `main`:
    Jeder Prompt aller Profile hört das angefragte Thema; `best-quality-generated` schreibt darüber, nennt es als
    Überschrift und füllt einen Baustein ohne Belege aus Modellwissen. Dazu (Jan: „wenn das thema zu lang ist oder
    eine texteingabe war sollte in den beiden profilen die ki das thema passend zum input formulieren“; ein Knoten
    kann das Thema ersetzen oder begleiten): In den beiden schreibenden Profilen formuliert das LLM das Thema aus
    einem Text oder den Metadaten eines Knotens. Gemessen in M51 (zwei blinde Gutachter, neun Themen): Passung bei
    Themen mit Aspekt 4,00 statt 1,50, bei Sammelthemen 3,83 statt 2,83, bei einfachen 4,83 statt 4,67; Nutzen,
    Vollständigkeit und Lesbarkeit steigen um 0,7 bis 1,5 Noten, zum gleichen Preis (84.016 Tokens, 30 s). Das
    Modellwissen steigt auf 62 statt 27 %, vor allem aus den Bausteinen ohne Belege. Die Zuordnung lässt bei einem
    Aspekt Absätze über den Oberbegriff weg; der wörtliche Text von `best-quality` wird dort kürzer.

    **Entschieden (D73, Jan, 02.10.2026):** V1a, V3 und V4 wie empfohlen übernommen, V1b nicht. Ein wörtlicher Text
    behält den gedruckten Artikel als Überschrift (D12); der Hinweis V3 nennt das angefragte Thema und die beiden
    schreibenden Profile (Jan: „Artikel + Hinweis“; revidiert mit D75: Die Überschrift nennt in jedem Profil das
    angefragte Thema, Jan: „ich hatte vorher kommuniziert das dies in allen profilen ein problem wäre, wenn das thema
    verfälscht wird“; der Hinweis bleibt und sagt, welcher Artikel darunter steht). Die Frage N fragt dafür in Version 2
    nur nach `deckt_ab`, nicht nach
    drei Übersichten; nachgemessen in M53: kein Hinweis bei 46 Themen mit eigenem Artikel, alle 6 Themen mit Aspekt
    erkannt, von den M48-Sammelthemen 1 von 6 (mit drei Übersichten 3 von 6), weil das Modell eine Epoche wie *Wiener
    Klassik* für deckend hält. Mitbehoben: Ein Baustein mit Belegen, dessen Text keinen davon zitiert, fiel in
    `best-quality-generated` auf wörtliche Absätze zurück, mitten in einem geschriebenen Text; er bleibt jetzt
    geschrieben, jeder Satz gekennzeichnet.
15. **Zeit und Tokens** (Jan, 08.10.2026: „abschließend sollten wir die frage analysieren ob wir
    bearbeitungsgeschwindigkeit und tokenverbrauch verbessern können … die qualität muss aber im auge behalten werden -
    nochmal für alle profile durchdenken“): gemessen in M75, Aufruf für Aufruf, an den neun Themen von M52.

    **Wo die Zeit hingeht:** Ohne LLM wartet der Dienst auf das Archiv: Im ersten Lauf eines Themas brauchte
    `llm-free` 2 bis 15 s, vor allem für Korpus und Nachschlagen von Akteuren und Glossar; im zweiten Lauf brauchte der
    Korpus 0,0 bis 0,1 s und das Nachschlagen 0,2 bis 4,6 s. Mit LLM liegen die Schritte nacheinander auf dem Weg:
    Vorbereitung 1,6 s, Zuordnung 14 bis 15 s, Schreiben 15 bis 18 s, dann Teil 2 mit 2,3 s, dann Teil 3. Kein Aufruf
    wartete auf einen der 10 Plätze. Das Modell schreibt rund 100 Tokens je Sekunde; das Schreiben dauert so lange wie der längste Baustein,
    die Zuordnung so lange wie ihr langsamster Stapel. Die großen Hebel sind schon gezogen und gemessen: Absätze für die
    Zuordnung auf 250 Zeichen, 50 je Stapel (D36, M59), kein Denken bei den fünf Fragen, die ohne gleich gut antworten
    (D81), alles, was Aufrufe teilen, in der System-Nachricht für den Cache des Anbieters (D69).

    **Wo die Tokens hingehen** (`best-quality-generated`, 75.600 je Anfrage): Zuordnung rund 63 %, Schreiben 27 %,
    Teil 2 10 %; ein Fünftel ist Ausgabe, und davon sind zwei Fünftel Denken (Zuordnung und Schreiben, D81). Bei OpenAI
    kostet Ausgabe üblicherweise ein Mehrfaches der Eingabe, Eingabe aus dem Cache einen Bruchteil.

    | # | Vorschlag | Zeit | Tokens | Güte | Empfehlung |
    |---|---|---|---|---|---|
    | a | Gleichzeitige Aufrufe je Anbieter: openai 20, academiccloud 2; `LLM_MAX_CONCURRENCY` überschreibt beide (Jans Vorschlag) | allein nichts, da kein Schritt mehr als 10 Aufrufe stellt; nötig für b und c und wenn sich Anfragen einen Worker teilen | – | – | gebaut (D93) |
    | b | Teil 2 neben Teil 1, sobald die Artikelwahl steht | −1,4 bis −2,2 s in `best-quality`, `best-quality-generated`, `best-coverage-generated` | – | gleich: dieselben Prompts, gemessen ohne Rückfall | gebaut (D93) |
    | c | Teil 3 von Anfang an neben dem Rest | −0,8 bis −5,9 s, wenn eine Sammlung ohne Cache gelesen wird, in jedem Profil | – | gleich | gebaut (D93) |
    | d | Zuordnung in Stapeln von 25 statt 50 | −4 s | +23 % | macro-F1 0,635 statt 0,684, zweimal ausgelassene Absätze | nicht bauen |
    | e | Absatzkopf der Zuordnung kompakter (Artikel und Abschnitt nur beim Wechsel) | – | −7,5 % der Zuordnung, rund 3.500 Eingabe-Tokens je Anfrage | in der Streuung, im Mittel 0,02 macro-F1 darunter | nicht vordringlich |
    | f | Teil-2-Prüfung auf die ersten N Elemente begrenzen (etwa 600) | wenig: Teil 2 läuft jetzt neben Teil 1 | M76, zwölf Themen: ein Deckel von 600 spart 11 % der Prüftokens, einer von 360 39 % | jedes Element, das er streicht, hatte die Note „passt“: bei 600 fallen 310 von 2.235 gedruckten weg, bei 360 920 | nicht bauen (M76) |
    | g | `best-coverage-generated` mit Regel-Zuordnung (Punkt 12d) | rund −14 s | rund −38.000 (40 %) | Passung 4,56 statt 4,81, Nutzen 4,31 statt 4,81 (M47) | nein (Jan, 08.10.2026: „würde die qualität senken“) |
    | h | Nachzügler doppelt stellen | selten (einer unter rund 1.100 Aufrufen, dann 100 statt 10 s) | wenige | gleich | optional, später |
    | i | Cache-Haltezeit 24 h beim Anbieter (`prompt_cache_retention`) | – | keine: nach 20 min Pause noch im Cache, nach weiteren 40 min auch mit dem Parameter nicht mehr | gleich | nicht bauen |
    | j | academiccloud mit 2 Plätzen | `best-quality-generated` 100 s, `best-coverage-generated` 119 s schon mit der Geschwindigkeit von `gpt-6-luna` | – | bei 120 s Frist Rückfälle | gebaut (D93): Frist je Anbieter, academiccloud 600 s, openai 300 s |
    | k | `llm-free`: Artikel parallel lesen und nachschlagen | kalt 2 bis 15 s, davon ein Teil | – | gleich | erst messen |
    | l | Zuordnung antwortet in Zeilen (`p12 fachinhalte 8`) statt in einem JSON-Objekt (M77) | ein Fünftel bis knapp ein Drittel der Zuordnung | −2,8 % der Zuordnung, davon Ausgabe −16 % | gleich: macro-F1 0,682 statt 0,676, micro-F1 0,791 wie zuvor; kein ausgelassener Absatz (JSON: 8) | gebaut (D93) |

    **Nach dem Bau** (M78, dieselben neun Themen und Profile wie M75, 20 Plätze): `best-quality` 15,1 statt 20,4 s,
    `best-quality-generated` 29,8 statt 33,9 s, `best-coverage-generated` 36,7 statt 37,3 s. Die Zuordnung schreibt je
    Absatz 17 bis 20 % weniger und war in allen drei Profilen kürzer (11,6 bis 12,4 statt 13,8 bis 15,1 s); Teil 2
    endete 4,7 bis 5,7 s nach Beginn neben ihr statt mit 2,3 s am Ende; kein Absatz fiel an die Regeln zurück. In
    `best-coverage-generated` schrieb der Anbieter in diesem Lauf langsamer (84 statt 92 Tokens je Sekunde, längster
    Baustein 21,4 statt 17,8 s) und hob die gewonnenen rund 6 s fast auf. Schneller als ihr längster Aufruf wird keine
    Stufe: Die Stapel der Zuordnung und die Bausteine des Schreibens laufen schon alle zugleich (Jans Frage nach mehr
    Workern); mehr Worker-Prozesse helfen, wenn mehrere Anfragen zugleich kommen, nicht der einzelnen.

    **Kaputte Antworten** (Jan: „eventuell müßte man auch fälle einplanen bei denen eine llm rückmeldung fehlschlägt
    oder nicht sauber geparst werden kann“): Jeder Schritt mit LLM fällt bei einem Fehler des Aufrufs, erschöpftem
    Budget, abgelaufener Frist oder unlesbarer Antwort auf seine Regeln zurück und nennt den Grund im Audit; der Client
    wiederholt Aufrufe bei 429 und den Gateway-Fehlern 500 und 502 bis 504, die Zuordnung fragt bei unlesbarer Antwort
    einmal nach (V4). Ein neuer Test beantwortet jede Frage mit acht Arten kaputter Antworten (leer, Prosa, leeres
    Objekt, Liste, `null`, abgeschnittenes JSON, falsche Typen, unbekannte Schlüssel), in jedem Profil mit LLM und an
    jedem Endpunkt, der fragt: nie ein Fehler, jeder Rückfall mit Grund. Eine Lücke fand er beim Schreiben in den
    Profilen mit Modellwissen: Dort stand jede nicht leere Antwort als gekennzeichneter Text im Kompendium, auch JSON und
    eine Antwort, die das Ausgabelimit mitten im Satz abschnitt. Jetzt gilt JSON nicht als Text (Rückfall mit Grund),
    und von einer abgeschnittenen Antwort fällt der unvollendete Satz weg (`cut_off` im Audit). Nicht gebaut: Absagen
    des Modells („dazu kann ich nichts sagen“) an Wörtern zu erkennen wäre unzuverlässig; in den gespeicherten
    Messtexten kam keine vor.

    Kurz: Gebaut sind a bis c, j und l (D93): `best-quality` rund 5 s und `best-quality-generated` rund 4 s schneller,
    `best-coverage-generated` in Zuordnung und Teil 2 rund 6 s, mit Sammlung bis zu 6 s mehr, wenn Teil 3 ohne Cache
    liest. Zuordnung und Schreiben warten auf das Modell; mehr Tempo und spürbar weniger Tokens gäbe es nur gegen Güte
    (d, g) oder mit weniger bestätigten Lehrplanbezügen (f).

16. **Weitere Kiwix-Archive als Quellen** (Jan, 09.10.2026: „ob man das hinzufügen weiterer kiwix zum quellen die
    qualität verbessern kann … primär um deutsche quellen“; nach M84: „empfehlungen bitte umsetzen“): entschieden als
    D99, gemessen in M84.

    ![Quellen des Kompendiums: Empfehlung (D99, M84)](bilder/quellen_empfehlung.svg)

    **Empfehlungen, kurz:**

    - Bei Wikipedia und Klexikon bleiben (Profil `standard`). Wikibooks, Wikiversity, Wiktionary, Wikisource, Wikiquote,
      Wikivoyage und Projekt Gutenberg nicht aufnehmen; `extended` bleibt einstellbar, ist aber nicht empfohlen.
    - Die Wikipedia aktuell halten: Die Ausgabe 2026-10 (18,6 GB, mwoffliner 2.0.1) las der Parser bei drei Stichproben
      gleich. Der `zim-updater` holt sie von selbst; geprüft wird sie online auf dem Testserver, und der Betrieb braucht
      jetzt mindestens 50 GB Platte.
    - Den Klexikon-Zwilling nur über den exakten Titel nehmen: gemessen in M85, gebaut als D100 (Release 2.18.2); ein
      Archiv aus ZUM-Unterrichten oder dem MiniKlexikon wäre eine eigene Messung.

    **Beobachtungen:**

    - Kein weiteres Archiv bringt passenden Text. Über den gleichen Titel, den Weg in den Korpus, kommen Wikibooks und
      Wikiversity bei je 1 von 40 Themen, die anderen nur mit Wörterbucheinträgen, Zitatlisten, Linklisten und einem
      Reiseführer; für die 11 Aspektthemen fand die Suche in keinem eine passende Seite.
    - In den wörtlichen Profilen schaden sie: Wiktionary, Wikiquote und Wikisource setzten 26 Absätze aus
      Deklinationstabellen, Zitaten und Listen in den Text; mit allen sechs Archiven fielen 41 Absätze der Wikipedia
      weg, und drei Bausteine blieben leer. Das gemischte Schriftbild entstünde also schon mit deutschen Archiven.
    - Das Klexikon trägt (passender Zwilling bei 15 von 40 Themen, 20 Absätze im Text), holt aber über einen Alias auch
      falsche Absätze: Flüsse bei „Elektrischer Strom“, Gefängniszellen bei „Zelle (Biologie)“. Seit D100 kommt der
      Zwilling nur noch über den exakten Titel (M85).

    ![Mehrwert weiterer Kiwix-Archive für die Kompendien (M84)](bilder/kiwix_quellen.svg)

    **Umgesetzt:** Manifest, README, Installation, Übergabe und Betrieb nennen `extended` nicht empfohlen und die Größen
    der Ausgabe 2026-10; die sechs gemessenen Archive sind gelöscht (`mc_kiwix_laden.py` holt sie für eine
    Wiederholung). Lokal bleibt die Januar-Ausgabe der Wikipedia, weil für zwei Ausgaben der Platz fehlt. Katalog,
    Gutenberg und alle Zahlen: M84.

    **Nachtrag (M90):** Jan: „mich würde noch interessieren ob bei x10 im vergleich zu x1 die zusätzlichen quellen
    (wikibooks, wikiversity) einen mehrwert bieten oder die einschätzung unverändert bleibt“. Über den exakten Titel
    bekommen nur 6 von 100 Anfragen einen Zwilling aus Wikibooks oder Wikiversity, drei Seiten: *Optik*, *Lineare
    Funktion* und *Open Educational Resources*. Bei ×1 druckt `llm-free` daraus 3 Absätze, bei ×10 70; von den 30
    verschiedenen sind 22,5 zum Thema und 6,5 am Rand. Der Zwilling belegt einen Korpusplatz und verdrängt den letzten
    Artikel der Wikipedia: bei Optik vor allem *Röntgenoptik* mit ebenso passenden Absätzen, bei „Lineare Funktion“
    *Lineare Algebra* mit 36 unpassenden, bei „OER-Förderungen“ *Open Access* und *Open Source*. Wo ein Zwilling kommt,
    wird der Text bei ×10 also nicht schlechter, bei zwei der drei Seiten besser; an der Empfehlung ändert das wenig,
    weil es selten trifft. Die beiden Archive kosten 4,1 GB Platte; gemessen nur in `llm-free`, für M90 neu geladen.

17. **Bausteinbudget** (Jan, 09.10.2026: „der größte hebel ist das bausteinbudget … vom team gewünscht war, das die
    kompendiale texte umfangreich und vollständig sind“; nach den ersten Zahlen: „zu prüfen wäre was möglicherweise
    dagegen sprechen könnte … vielleicht kann man dann mit einem f1 sagen wo die verbesserungen gesättigt sind“):
    gemessen in M86 mit dem Faktor 1, 2, 4 und 10 auf die Absätze und Zeichen je Baustein an vier Themen in `llm-free`,
    `balanced` und `best-quality-generated`, dazu am Gold der Zuordnung bis ×1000 und mit einem Urteil zu jedem
    gedruckten Absatz und jedem Beleg des Schreibers; entschieden (D102, Jan): das Zehnfache als Vorgabe seit
    Release 2.19.0.

    ![Bausteinbudget ×1 bis ×10: Text, Belege, Kosten und Noten (M86)](bilder/bausteinbudget.svg)

    | Median über vier Themen | ×1 | ×2 | ×4 | ×10 |
    |---|---|---|---|---|
    | `llm-free`: Zeichen | 10.400 | 14.400 | 22.800 | 28.700 |
    | `llm-free`: Nutzen / Vollständigkeit / Lesbarkeit | 1,5 / 1,5 / 2,3 | 2,0 / 1,5 / 2,5 | 2,5 / 1,9 / 2,5 | 2,8 / 1,9 / 2,5 |
    | `balanced`: Zeichen | 11.100 | 17.600 | 27.900 | 44.900 |
    | `balanced`: Nutzen / Vollständigkeit / Lesbarkeit | 2,0 / 1,3 / 3,0 | 2,8 / 2,1 / 2,6 | 3,4 / 2,1 / 2,4 | 4,3 / 2,1 / 2,4 |
    | `balanced`: Absätze daneben im Text, Summe der Themen | 3 (3 %) | 4 (2 %) | 7,5 (3 %) | 22 (5 %) |
    | wörtliche Profile: Zuordnung und Text | 0,5 und 0,8 s | 0,5 und 0,9 s | 0,5 und 0,8 s | 0,8 und 1,1 s |
    | `best-quality-generated`: Zeichen | 23.200 | 26.300 | 27.700 | 28.600 |
    | `best-quality-generated`: Tokens je Anfrage | 65.200 | 69.600 (+7 %) | 77.600 (+19 %) | 86.400 (+33 %) |
    | `best-quality-generated`: Nutzen / Vollständigkeit / Lesbarkeit | 3,8 / 3,8 / 4,0 | 4,3 / 4,1 / 4,0 | 4,5 / 4,3 / 3,6 | 4,9 / 4,6 / 4,0 |
    | `best-quality-generated`: Zuordnung und Schreiben | 24,9 s | 23,0 s | 25,1 s | 25,9 s |
    | `best-quality-generated`: Belege daneben, Summe der Themen | 3 (3 %) | 4 (2 %) | 11 (3 %) | 17,5 (3 %) |
    | Gold der Zuordnung: F1 der Regeln und des LLM | 0,26 und 0,35 | 0,34 und 0,46 | 0,46 und 0,58 | 0,60 und 0,74 |

    **Was dagegen sprechen könnte, gemessen:**

    - **Kosten:** Mehr Tokens braucht mehr Budget nur in den schreibenden Profilen, in `best-quality-generated` 7 % bei
      ×2, 19 % bei ×4, 33 % bei ×10. Es wächst die Eingabe, kaum die Ausgabe; der teuerste Lauf brauchte 103.400 der
      damals erlaubten 180.000 Tokens. Am breitesten Thema, Demokratie, brauchte Teil 1 bei ×10 109.100 Tokens in
      `best-quality-generated` und 132.100 in `best-coverage-generated`, `best-quality` so viele wie bei ×1 (M86, nach
      der Messung). `llm-free` braucht keine, `balanced` gleich bleibend rund 310. `/qa` schreibt seine Paare aus einem
      Teil 1 von `llm-free`; mit dem Zehnfachen fielen sie im Test auf die Regeln zurück, weil sie den ganzen Teil 1
      lesen, und `/qa` bleibt bei den Budgets der Vorlage (D102).
    - **Dauer:** In keinem Profil länger (Tabelle): Das Budget greift erst nach Artikelwahl und Zuordnung, und der
      Schreiber schreibt die Bausteine nebeneinander.
    - **Präzision, unpassende Absätze:** Am Gold bleibt die Precision bei jedem Faktor (Regeln 0,62 bis 0,66, LLM 0,78
      bis 0,82), auch der Anteil der Absätze, die nicht hineingehören (10 bis 14 und 4 bis 7 %). Im Text von `balanced`
      bleibt der Anteil daneben bis ×4 bei 2 bis 3 %; ×10 bringt mehr Absätze am Rand und unter den neuen 8 % daneben,
      vor allem beim Aspektthema und bei Optik. Die Zahl unpassender Absätze wächst mit der Länge, ihr Anteil bis ×4
      nicht. Die Belege, die der Schreiber von `best-quality-generated` liest, sind bei jedem Faktor zu 2 bis 3 %
      daneben, auch die neuen bei ×10, alle beim Aspektthema (M86, nach der Messung).
    - **Länge und Lesbarkeit:** Die wörtlichen Texte werden länger und etwas schwerer lesbar (`balanced` 3,0 auf 2,4 bis
      ×4, danach gleich). Bei ×10 ist `balanced` im Median 44.900 Zeichen lang, beim Aspektthema 62.400, deutlich über
      der Ziellänge. `best-quality-generated` hält Länge und Lesbarkeit.
    - **Fehler:** Die leichten Fehler, die die wörtlichen Texte aus Wikipedia und Klexikon erben, wachsen mit dem Text,
      je 10.000 Zeichen etwa gleich viele.

    **Wo es sättigt:** Nichts wächst linear; jede Einheit Budget bringt weniger als die vorige. Am Gold holt ×4 die
    Hälfte des möglichen F1-Gewinns, ×10 82 und 85 %, ×20 98 %; ab ×30 ist alles Zugeordnete gedruckt. In den Texten
    steigt der Nutzen je Verdopplung um einen ähnlichen Betrag; die Vollständigkeit der wörtlichen Profile ist bei ×2
    bis ×4 am Ende, die von `best-quality-generated` steigt bis ×10.

    ![Bausteinbudget am Gold der Zuordnung: Precision, Recall und F1 (M86)](bilder/bausteinbudget_gold.svg)

    ![Bausteinbudget: passende und unpassende Absätze im Text von llm-free und balanced und in den Belegen von best-quality-generated (M86)](bilder/bausteinbudget_absaetze.svg)

    **Empfehlung vor der Entscheidung:** Faktor 4 als einstellbare Vorgabe für alle Profile, angewandt wie gemessen auf
    die Höchstzahl der Absätze und die Zeichen, ab denen ein Baustein schließt; die Vorlagen bleiben, wie sie sind. Bei
    ×4 gewinnt jedes Profil 0,8 bis 1,4 Noten an Nutzen und `best-quality-generated` 0,5 an Vollständigkeit, für 19 %
    mehr Tokens dort und ohne längere Dauer; Precision und Anteil unpassender Absätze bleiben, und die wörtlichen Texte
    kommen in die Nähe der Ziellänge. Über ×4 hinaus lohnt es nur für `best-quality-generated`: ×10 bringt dort noch 0,4
    Noten an Nutzen und Vollständigkeit für 14 Prozentpunkte mehr Tokens, ohne den Text zu verlängern; die wörtlichen
    Profile bekämen bei ×10 lange Texte mit mehr Absätzen am Rand. Ein eigener, höherer Faktor für die schreibenden
    Profile wäre eine zweite Einstellung; für `/qa` kann der Faktor bei 1 bleiben.

    **Entschieden (D102, Jan):** „bei llm free steigt die fehlerquote nicht. bei balanced scheint sie leicht zu steigen.
    der tokenanstieg scheint zwar spürbar zu sein aber sich in grenzen zu halten … wahrscheinlich sollten wir das 10
    fachebudget als default wert setzen“. Seit Release 2.19.0 gilt das Zehnfache für alle Profile, einstellbar mit
    `BLOCK_BUDGET_FACTOR` (`1` stellt das Verhalten bis 2.18.2 her), und die `best-quality`-Profile dürfen 200.000
    Tokens je Anfrage brauchen (`LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY`). Die wörtlichen Texte werden damit deutlich
    länger, `balanced` im Median 44.900 statt 11.100 Zeichen, `best-quality` bei Demokratie 105.200 statt 15.500; die
    Belege des Schreibers bleiben so passend wie bei ×1. `/qa` bleibt bei den Budgets der Vorlage; `extraction=llm`, in
    keinem Profil voreingestellt, ist mit dem Zehnfachen nicht gemessen.

    Nebenbefund: Die Artikel, die das LLM zu einem Thema nennt (D63), wechselten von Lauf zu Lauf; einmal kam für Optik
    „Linsen“, im Archiv die Pflanzengattung, und ein größeres Budget druckte deren Botanik. M86 maß deshalb jedes Thema
    auf einem festen Korpus; die genannten Artikel auf Mehrdeutigkeit zu prüfen, ist eine eigene Messung.

18. **Genannte Artikel einer anderen Bedeutung** (Nebenbefund von Punkt 17): gemessen in M88 an den 100 Anfragen von
    M82, je fünf Läufe `balanced` (500), alle Varianten auf denselben Antworten von N; zu entscheiden.

    **Befund:** 16 von 3.309 Artikeln, die das Archiv für die Titel von N lieferte, behandeln etwas anderes gleichen
    Namens (0,5 %; mit den Fällen nur eines Gutachters 21). In 14 von 500 Läufen druckt der Text Absätze daraus,
    zusammen 61 von 12.447 (0,5 %), zwei Drittel bei mehrdeutigen Wörtern mit Fach. „Linsen“ kam nicht wieder; N nannte
    die Linse zu Optik als „Linse (Optik)“. Zehn der 16 lieferte das Archiv, obwohl N das Richtige meinte: über eine
    Weiterleitung („Instrumental“ führt zur *Instrumentalmusik*), einen gleichnamigen Artikel („Friedrich von Spee“
    ist ein Landrat, „Neuronales Netz“ das biologische) und die Übersicht „Delta (Geografie)“, die ohne Klammerzusatz
    der griechische Buchstabe ist. Sechs nannte N selbst, etwa „Intervall (Mathematik)“ zum Intervall in Musik und
    „Mechanische Spannung“ zur Spannung in Physik. Keiner der Fälle ist im Archiv als mehrdeutig erkennbar.

    | Variante | andere Bedeutung im Korpus (heute 16) | passende Artikel weg | gedruckte Absätze anderer Bedeutung (heute 61) | gedruckte Absätze (heute 12.447) |
    |---|---|---|---|---|
    | den Artikelanfang auf Wörter des Themas prüfen (`anfang`) | 9 | 604 | 37 | 11.726 |
    | Verlinkung mit Hauptartikel oder Übersicht verlangen (`verlinkt`) | 6 | 159 | 26 | 12.229 |
    | den Klammerzusatz zum Fach bevorzugen (`klammer`) | 17 | 5, dafür 39 neu | 61 | 12.474 |
    | nur Namen prüfen, die das Archiv als mehrdeutig zeigt (`mehrdeutig`) | 16 | 7, dafür 8 neu | 61 | 12.458 |
    | ein Klammerzusatz, der ein anderes Fach nennt, fällt weg (`fachfremd`) | 15 | 0 | 56 | 12.443 |
    | die Übersicht ohne Klammerzusatz nur, wenn ihr Anfang das Klammerwort nennt (`uebersicht`) | 13 | 0 | 43 | 12.435 |

    **Empfehlung:** keine Prüfung der genannten Artikel einbauen. Die allgemeinen Prüfungen kosten das 16- bis 86-Fache
    an passenden Artikeln (`verlinkt` 159 für 10, `anfang` 604 für 7) und Text, und die Fälle haben kein gemeinsames
    Merkmal, an dem eine Regel ansetzen könnte. Wer die zwei häufigsten Wege schließen will: `fachfremd` ist eine Regel
    von wenigen Zeilen und traf in 500 Läufen nur ihren Fall; `uebersicht` nähme den Buchstaben Delta heraus, aber auch
    den Fall, für den die Übersicht ohne Klammerzusatz gebaut wurde (V1a, M49): „Aufklärung (Philosophie)“, deren
    Artikel die Philosophie im ersten Absatz nicht nennt.

    **Beobachtungen:**

    - `klammer` löst ein anderes Problem desselben Schritts: Titel, die ohne Klammer eine Begriffsklärung sind oder
      fehlen, fallen heute aus; mit `klammer` kamen 34 passende Artikel dazu (*Ballade (Gedicht)*, *Hauptsatz
      (Grammatik)*, *Linse (Optik)* für „Linse“) und ein Fehlgriff (*Strom (Gewässerart)* zu „Strom“). Das wäre eine
      eigene Entscheidung, keine Prüfung auf Mehrdeutigkeit.
    - Häufiger als eine andere Bedeutung ist, dass es einen genannten Titel nicht gibt: 437 der 3.729 genannten Teile
      (12 %), 168 davon mit einem Klammerzusatz, den es nicht gibt („Bruch (Mathematik)“, „Welle (Physik)“), dazu 92
      Begriffsklärungen. Beide fallen still aus.
    - Die genannten Artikel wechseln stark von Lauf zu Lauf: Über fünf Läufe kamen je Anfrage im Median 11 verschiedene,
      nur 41 % davon in allen fünf; der Hauptartikel blieb bei allen 100 Anfragen gleich.
    - Mit mehr Budget (Punkt 17) druckt jeder Fehlgriff mehr Absätze (M86).

19. **Satzauswahl der KI beim zehnfachen Bausteinbudget** (Jan, 09.10.2026: „vielleicht sollten wir es trotzdem mal mit
    antesten … es wäre interessant zu wissen welche qualität balance + extraction llm oder max quality + extraction llm
    haben“): gemessen in M89 an den neun Themen von M82, `balanced` und `best-quality` je ohne und mit `extraction=llm`,
    beim ausgelieferten Budget (×10); zu entscheiden. Kein Profil setzt den Schalter; seit D103 steht er als Kästchen
    „KI wählt die Sätze“ beim Profil.

    | Neun Themen | `balanced` | mit Satzauswahl | `best-quality` | mit Satzauswahl |
    |---|---|---|---|---|
    | Passung / Nutzen | 3,2 / 3,8 | 3,1 / 3,1 | 3,6 / 4,2 | 3,8 / 3,4 |
    | Vollständigkeit / Lesbarkeit | 2,3 / 2,4 | 2,4 / 2,6 | 2,8 / 2,5 | 2,9 / 3,0 |
    | Fehler, schwer und leicht, zwei Gutachter | 9 und 32 | 2 und 15 | 7 und 34 | 0 und 24 |
    | Zeichen (Median) | 60.700 | 21.100 | 53.300 | 23.200 |
    | Tokens je Anfrage (Median) | 310 | 33.500 | 40.500 | 71.400 |
    | Dauer der Anfrage (Median) | 4,8 s | 10,8 s | 16,8 s | 22,3 s |
    | Gold der Zuordnung ×10: Precision / Recall | 0,64 / 0,56 | 0,70 / 0,26 | 0,77 / 0,67 | 0,72 / 0,34 |

    - **Nutzen:** sinkt in beiden Profilen um rund 0,75 Noten. Die Auswahl schließt beim Zeichenbudget der Vorlage,
      nicht bei dem von D102: Die Texte werden ein Drittel so lang, und am Gold halbiert sich der Recall.
    - **Lesbarkeit und Fehler:** etwas lesbarer, weniger Fehler, vor allem weil weniger Text dasteht.
    - **Bausteine:** Die Auswahl füllt mehr Bausteine (im Median 9 statt 6 und 7), weil sie auch die nächstbesten
      Absätze eines Bausteins bekommt, dem die Zuordnung keinen gab; die Vollständigkeit steigt dadurch kaum.
    - **Kosten:** rund 33.000 Tokens mehr in `balanced` (das Hundertfache), rund 31.000 in `best-quality`, je rund 6 s;
      keine Anfrage kam an die ausgelieferten Grenzen, keine fiel zurück.

    **Empfehlung:** In keinem Profil voreinstellen; der Schalter bleibt für Anfragen und die Prüfansicht. Soll die
    Auswahl die Länge von D102 halten, müsste sie beim Zeichenbudget mal `BLOCK_BUDGET_FACTOR` schließen; ob sie dann
    den Nutzen hält und lesbarer bleibt, wäre neu zu messen.

Die KI-Prüfung der Lehrplanelemente, seit D53 offen, ist mit D58 gebaut: Jan hat die MEM-Daten am 26.09.2026 ohne
Einschränkung freigegeben, die FWU stellt den Zugang offen bereit (github.com/FWU-DE/mem-mcp). Sie läuft in den beiden
`best-quality`-Profilen (`curriculum_check=llm`); `llm-free` und `balanced` bleiben bei den Regeln mit gebündelten
Überschriften-Treffern.

## Außerhalb von Teil 1: Knoten-Eingang und Lehrplanbezüge

Die Zahlen stehen im [Messprotokoll](05-messprotokoll.md), M21 bis M25.

6. **Kompendium aus einem Material (`node_id` ohne `topic`), eingebaut (D47):** Echte Titel nennen oft Format oder
   Datum; seit D47 ist der Titel nur der Anfang der Suche. Hauptartikel-F1 der Materialien mit klarem Thema: 31 aus
   M21 und 30 neue, beschriftet, bevor ein Weg auf ihnen lief (M25):

   | Weg | Stufe | M21-Materialien | neue Materialien | LLM je Material |
   |---|---|---|---|---|
   | Titel als Thema (bis D47) | – | 0,20 | 0,00 | – |
   | Regeln über Titel und Beschreibung | LLM-frei | 0,56 | 0,63 | – |
   | Thema vom LLM | ausgewogen | 0,98 | 0,88 | rund 310 bis 340 Tokens, 1,8 bis 2,0 s |
   | Begriff, den eine Lehrkraft eintippt | – | 0,94 | 0,83 | – |
   | Begriff und Material, das LLM hört beides | ausgewogen | 1,00 | 0,87 | rund 550 bis 600 Tokens, 2,5 bis 2,6 s |

   Findet die Regel keinen Artikel, fragt der 404 nach einem `topic`; zu Materialien ohne fachliches Thema baut sie
   in 5 von 6 Fällen keines, das LLM dagegen in 5 von 6 eines. Bis zum Kompendium gemessen (M23) wurde es mit dem
   Titel bei 5 von 31 Materialien brauchbar, mit dem Thema vom LLM bei 17; bei gleichem Hauptartikel entsteht
   derselbe Text wie zum Begriff. Mit `topic` und `node_id` zusammen führt das Thema, und der Artikel des Materials
   kommt dazu, wenn er mit dem Hauptartikel verlinkt ist; soweit M23 diese Artikel benotet hat (10), passten sie oder
   waren verwandt. Ohne LLM hilft kein Embedding (M24, F1 höchstens 0,03).

   Offen: ob der Artikel eines Materials neben einem Thema die Kompendien besser macht (nur auf Artikelebene
   gemessen), und ob das LLM zu Materialien ohne Thema schweigen soll; der Prompt erlaubt es, das Modell nutzt es
   selten.
7. **Lehrplanbezüge (Teil 2, M22, M32):** entschieden (D58). Alle Profile nutzen die schärferen Stichwortregeln
   (`f5d8297`) und bündeln Elemente, die nur ihre Überschrift zum Thema macht, bei ihrem Bereich: 70 bis 81 % der
   einzeln gezeigten passend statt 62 bis 67 %, 5 bis 9 % unpassend statt 11 bis 17 %. In den `best-quality`-Profilen
   prüft das LLM jedes Element: 74 bis 79 % passend, ohne ein passendes zu verlieren. Jeder Block nennt Lehrplan,
   Land, Bildungsstufe und Klasse. Model2Vec als Filter (D1) verlöre ein Viertel der passenden und bleibt draußen.
8. **Punkte der Durchsicht vom 25.09.2026, alle umgesetzt:** Behoben sind die Fehler (Messprotokoll, M25). Die Punkte, die
   ändern, was Aufrufer bekommen, hat Jan am 25.09.2026 zur Umsetzung nach Empfehlung freigegeben:
   - `/qa` mit `text` und zugleich `topic` oder `node_id` nahm den Text nicht, ohne es zu sagen. Umgesetzt (D49): 422,
     wie bei `/entities`; ebenso `subject`, `preset` und `article_choice` ohne Thema.
   - Ein unbekanntes `subject` („Pysik“) wurde still übergangen, Teil 2 suchte dann in allen Fächern; unbekannte Namen
     in `regenerate_sections` erneuerten nichts; unbekannte Felder aller Anfragen fielen still weg. Umgesetzt (D49):
     422 mit den erlaubten Werten; Fächer seit D51 gegen die beiden Fachvokabulare von edu-sharing.
   - `/lehrplan/search` suchte die Wörter, wie sie kamen, Teil 2 den aufgelösten Artikel, seine Aliase und
     Unterthemen. Umgesetzt (`ff41a11`): `mode=topic` löst `q` wie Teil 2 auf, nennt den Artikel in `topic` und
     antwortet 404 für ein Thema, das die Archive nicht haben; Standard bleibt `keyword`. Seit D59 nimmt die Suche
     die Profile: In `balanced` wählt das LLM den Artikel des Themen-Modus, in den `best-quality`-Profilen prüft es
     jeden Treffer.
   - Die CLI kannte keinen Knoten, `/qa` mit der Stufe `llm` öffnete nach dem Kompendium ein zweites Token- und
     Zeitbudget, und eine unbekannte `knowledge_collection_id` ergab 200 mit dem Fehler im Audit, eine unbekannte
     `collection_id` 404. Umgesetzt (D49): `--node-id` und `--repository`, ein Budget je Anfrage, 404 vor jedem
     LLM-Aufruf. `/matching/compare` ist entfallen (D50): Im Betrieb braucht ihn niemand, und `compendium eval`
     vergleicht die Strategien auf dem Gold. Wie der Comparator wählt `compendium eval` die Artikel ohne LLM; die
     Zuordnung einer Stufe mit LLM-Artikelwahl braucht deshalb eine eigene Messung.
   - Die Links des Hauptartikels wurden je Anfrage neu aufgelöst. Umgesetzt (`267210f`): Ein Archiv behält die
     aufgelösten Namen (bis 20.000); *Deutschland* braucht im ersten Korpus weiter 1,9 s, im zweiten zum selben Thema
     0,002 statt 0,19 s.
