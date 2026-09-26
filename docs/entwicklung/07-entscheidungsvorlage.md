# Entscheidungsvorlage: Verfahren und Schalter von Teil 1

[Übersicht](README.md) · Stand 26.09.2026 · Zahlen: [Messprotokoll](05-messprotokoll.md), M1 bis M31; Rohdaten und
Zusammenfassungen in [messung/ergebnisse](messung/ergebnisse/README.md)

Teil 1 des Kompendiums, das Weltwissen, entsteht in fünf Schritten. An vier davon lässt sich ein Sprachmodell (LLM)
zuschalten. Diese Vorlage zeigt je Schritt, welche Verfahren es gibt, wie man sie im Dienst wählt, was sie leisten und
was sie an Zeit und Tokens kosten. Vier Profile bündeln sie (D53); der Schalter `preset` wählt eines. „Standard“
heißt: Das gilt, wenn die Anfrage nichts anderes verlangt. Standard ist das Profil `balanced` (`PRESET_DEFAULT`);
jedes Profil außer `llm-free` braucht ein LLM, sonst ist die Anfrage ein 503. Die Profile wählen auch das Verfahren
der QA-Paare (D54, D55, D57).

## Die vier Profile auf einen Blick

| | `llm-free` | `balanced` (Standard) | `best-quality` | `best-quality-generated` |
|---|---|---|---|---|
| Hauptartikel (`article_choice`) | `rule-based` | `llm` | `llm` | `llm` |
| Korpus | 12 Artikel, Volltexttreffer nur mit Link zum Hauptartikel | dazu Prüfung der Nebenartikel | dazu Prüfung der Nebenartikel | dazu Prüfung der Nebenartikel |
| Zuordnung (`matcher`) | `hybrid_light` | `hybrid_light` | `llm` | `llm` |
| Text (`generation`, `enrichment`) | wörtlich | wörtlich | wörtlich | vom LLM geschrieben, ergänzt um Modellwissen |
| QA-Paare (`/qa`, `method`) | `rule-based` | `rule-based` | `llm` | `llm` |
| Lehrplanbezüge (Teil 2) | Regeln | Regeln | Regeln | Regeln |
| Hauptartikel richtig, 94 Goldanfragen (M9) | 86 | 91 | 91 | 91 |
| Material ohne `topic`: Hauptartikel-F1, zwei Stichproben (M25) | 0,56 und 0,63 | 0,98 und 0,88 | wie `balanced` | wie `balanced` |
| gedruckte Absätze aus unpassenden Artikeln, 20 Themen (M25) | 12 von 352 | 5 von 346 | nicht gemessen | nicht gemessen |
| Zuordnung, macro-F1 der gelabelten Absätze (M27, M19) | 0,45 | 0,45 | 0,70 | 0,70 |
| Lesbarkeit für Lehrkräfte, 1 bis 5, zwei Gutachter (M28) | wörtlich wie `best-quality` | wörtlich wie `best-quality` | 2,5 | 4,0; im Mittel 5 Füllsätze je Thema, mit dem ersten Prompt 12 (M31) |
| QA-Paare mangelfrei bei beiden Gutachtern (M30) | 48 von 96, 0,3 s je Text | wie `llm-free` | 99 von 120, rund 2.400 Tokens | 99 von 120, rund 2.400 Tokens |
| Teil 1 und 2 je Kompendium (M27) | 1,6 s | rund 3,4 s | rund 14 s | rund 24 s |
| Tokens je Kompendium, Median (M27) | 0 | 905 | 26.267 | 35.376 |
| Kompendien je Tagesbudget von 2 Mio. Tokens | ohne Grenze | rund 2.200 | rund 76 | rund 57 |
| so wählt man es | `preset: llm-free`, ohne LLM `PRESET_DEFAULT=llm-free` | Standard, `preset: balanced` | `preset: best-quality` | `preset: best-quality-generated` |

![Die vier Profile im Vergleich](bilder/kombinationen.svg)

- **`llm-free`** ist das Beste, was ohne Sprachmodell geht: die geschärften Regeln der Artikelwahl, für ein Material
  ohne `topic` die Regeln über Titel und Beschreibung (D47), Volltexttreffer nur mit Link zum Hauptartikel (D48),
  `hybrid_light` mit Model2Vec als bestes lokales Zuordnungsverfahren, wörtlicher Text und QA-Paare aus den Regeln über
  den spaCy-Parse (D55): 48 von 96 bei beiden Gutachtern mangelfrei, in 0,3 s je Text (M30). Keine Tokens, keine
  Abhängigkeit von der b-api; das Profil für einen Dienst ohne LLM.
- **`balanced`** ist der Standard. Die LLM-Artikelwahl ist der billigste Hebel mit messbarer Wirkung: fünf richtige
  Hauptartikel mehr von 94, 5 statt 12 gedruckte Absätze aus unpassenden Artikeln und bei einem Material ohne `topic`
  ein Hauptartikel-F1 von 0,88 bis 0,98 statt 0,56 bis 0,63, für rund 1,5 bis 2 s und 900 Tokens (M25, M27). Die
  Zuordnung bleibt die von `llm-free` (0,45): Das LLM wirkt vor ihr, nicht in ihr (M27). Die QA-Paare kommen seit D57
  aus denselben Regeln wie in `llm-free` (Jan: der Standard fragt schnell und ressourcenschonend): 0,3 s, keine
  Tokens, kein zusätzliches Modell. Die zwei kleinen Modelle, die hier bis D57 fragten, waren in M30 die schwächste
  und langsamste Stufe (25 von 120 mangelfrei, rund 25 s je Text) und sind entfernt.
- **`best-quality`** nimmt dazu das LLM als Zuordner: 0,70 statt 0,45 macro-F1, für rund 14 s und 26.000 Tokens je
  Kompendium, rund 170 je Absatz. Sinnvoll, wo Qualität zählt und Zeit nicht, etwa beim Vorbereiten eines Kompendiums
  für die Redaktion. Der Text bleibt wörtlich und belegt. Die QA-Paare schreibt das LLM: 99 von 120 mangelfrei, rund
  2.400 Tokens und 4 bis 7,5 s je Text (M30).
- **`best-quality-generated`** lässt das LLM zusätzlich jeden Baustein schreiben und eigenes Wissen ergänzen, ohne
  Belegnummer und sichtbar gekennzeichnet mit `[Modellwissen]` (D56): rund 24 s und 35.000 Tokens je Kompendium. Zwei
  blinde Gutachter zogen den geschriebenen Text in 11 von 12 Urteilen dem wörtlichen vor (Lesbarkeit 4,0 statt 2,5 von
  5, Zusammenhang 4,0 statt 2,4), bei ähnlich vielen Fachfehlern, die meist schon in den Quellen stehen (M28). Mit dem
  ersten Prompt bestand das ergänzte Modellwissen zu zwei Dritteln aus Füllsätzen; der zweite verlangt eine prüfbare
  Sachaussage oder nichts: 50 statt 82 ergänzte Sätze, davon 13 statt 50 Füllsätze und 32 statt 27 fachliche, keiner
  falsch nach beiden Gutachtern (M31).

Zeiten: Entwicklungsrechner, Teil 1 und 2 im Prozess, jedes LLM-Profil auf eigenen Themen als `llm-free` plus
LLM-Anteil (M27); auf dem Server über HTTP dauert Teil 1 ohne LLM im Median 2,0 s (M3). Tokens: dieselben sechs
Themen in allen Profilen (M27). Mit `gpt-6-luna`; die LLM-Schritte eines Profils liefen zusammen.

## Die Profile: `preset`

`preset` setzt alle Schalter von Teil 1 auf eines der vier Profile (D41, D53). Einen Schalter, den die Anfrage selbst
setzt, lässt es stehen. Ohne `preset` gilt `PRESET_DEFAULT`, ausgeliefert `balanced` (D53; bis dahin war `llm-free`
die Vorgabe, D40); es ersetzt die Vorgaben der Einzelschalter (`MATCHER_DEFAULT`, `LLM_ARTICLE_CHOICE_DEFAULT` und
die übrigen). Jedes Profil außer `llm-free` braucht ein LLM: Ohne `LLM_ENABLED` und `B_API_KEY` ist eine solche
Anfrage ein 503, der die Schalter nennt, die ein LLM brauchen; ein Dienst ohne LLM setzt `PRESET_DEFAULT=llm-free`.

| `preset` | `article_choice` | `matcher` | `extraction` | `generation` | `enrichment` |
|---|---|---|---|---|---|
| `llm-free` | `rule-based` | `hybrid_light` | `rule-based` | `rule-based` | `sources-only` |
| `balanced` | `llm` | `hybrid_light` | `rule-based` | `rule-based` | `sources-only` |
| `best-quality` | `llm` | `llm` | `rule-based` | `rule-based` | `sources-only` |
| `best-quality-generated` | `llm` | `llm` | `rule-based` | `llm` | `model-knowledge` |

Wo man es findet: in `/docs` am Feld `preset` von `POST /api/v2/compendium` (mit Güte, Zeit und Tokens je Profil) und in
vier Beispielen, eines je Profil; `POST /api/v2/knowledge` und `POST /api/v2/qa` nehmen `preset` ebenfalls an
(`/knowledge` übernimmt daraus nur `article_choice`, `/qa` nur das Verfahren der Paare, D55); auf der Kommandozeile
`compendium generate --preset balanced`. Die Antwort nennt das wirksame Profil in `audit.preset`, was tatsächlich lief
in `audit.llm`. Ist die b-api nur gerade nicht erreichbar, laufen die Regeln, und `audit.llm` sagt warum.
`best-quality-generated` schaltet als einziges Profil `generation` und `enrichment` ein (Jan, 25.09.2026): Das LLM
schreibt jeden Baustein und darf eigenes Wissen ergänzen, ohne Belegnummer und sichtbar gekennzeichnet mit
`[Modellwissen]` (D56); `extraction` bleibt regelbasiert, weil es am Goldstandard nichts gewann (Schritt 4). Gemessen in
M27, M28 und M31: rund 24 s und 35.000 Tokens je Kompendium; zwei blinde Gutachter zogen den geschriebenen Text in 11
von 12 Urteilen dem wörtlichen vor (Lesbarkeit 4,0 statt 2,5 von 5, Zusammenhang 4,0 statt 2,4), bei ähnlich vielen
Fachfehlern, die meist schon in den Quellen stehen. Mit dem ersten Prompt waren zwei Drittel des ergänzten Modellwissens
Füllsätze; mit dem zweiten (D56) sind es 13 von 50 ergänzten Sätzen statt 50 von 82, und keiner ist nach beiden
Gutachtern falsch (M31).

## Die Profile je Endpunkt

| Endpunkt | `llm-free` | `balanced` | `best-quality` | `best-quality-generated` |
|---|---|---|---|---|
| `POST /api/v2/compendium` | Regeln; 1,6 s, keine Tokens | LLM-Artikelwahl und Prüfung der Nebenartikel; rund 3,4 s, 905 Tokens | dazu LLM-Zuordnung; rund 14 s, 26.267 Tokens | dazu Text vom LLM; rund 24 s, 35.376 Tokens |
| `POST /api/v2/knowledge` | Regeln; rund 0,5 s | LLM-Artikelwahl und Prüfung der Nebenartikel; rund 2 bis 3 s, rund 900 Tokens | wie `balanced` | wie `balanced` |
| `POST /api/v2/qa` mit `text` | `rule-based`: rund 0,3 s je Text, 9 bis 20 von 20 Paaren, 48 von 96 mangelfrei | wie `llm-free` (D57) | `llm`: 4 bis 7,5 s und rund 2.400 Tokens für 20 Paare, 99 von 120 mangelfrei | wie `best-quality` |
| `POST /api/v2/qa` mit `topic` oder `node_id` | Teil 1 ohne LLM wie in `llm-free`, dann die Paare wie mit `text`; die Regeln lesen dazu Glossar und Akteure | ebenso; nur bei einem Material-Knoten wählt das LLM den Artikel (D47) | ebenso | ebenso; auch hier fragen die Paare den wörtlichen Teil 1 ab |
| `GET /api/v2/lehrplan/search` | Regeln, in allen Profilen gleich; `mode=topic` löst wie Teil 2 auf, ohne LLM, 0,5 bis 1,3 s | wie `llm-free` | wie `llm-free` | wie `llm-free` |
| `GET /api/v2/nodes/{id}` | Regeln, in allen Profilen gleich: zeigt, was ein Knoten mitbringt | wie `llm-free` | wie `llm-free` | wie `llm-free` |
| `POST /api/v2/entities` | spaCy und Wörterbuch der Archive, ohne LLM | wie `llm-free` | wie `llm-free` | wie `llm-free` |
| `GET /api/v2/collections/{id}/overview` | Teil 3, ohne LLM | wie `llm-free` | wie `llm-free` | wie `llm-free` |

`/knowledge` und `/qa` nehmen `preset` wie das Kompendium; ohne es gilt `PRESET_DEFAULT`. Bei `/qa` wählt es nur das
Verfahren der Paare, Teil 1 eines Themas entsteht immer ohne LLM (D55). `/lehrplan/search`, `/nodes`, `/entities` und
der Sammlungsüberblick kennen kein LLM und kein Profil. Zeiten: M27 (`/compendium`, aus den Phasen für `/knowledge` und
`/lehrplan/search`) und M30 (`/qa`).

## Der Ablauf

![Ablauf von Teil 1](bilder/prozess.svg)

Dieselben Schritte mit allen Optionen, ihrer Güte, Zeit und ihren Tokens; die Quadrate zeigen, welche Stufe welche
Option nutzt:

![Jeder Schritt mit seinen Optionen](bilder/prozess_optionen.svg)

Teil 2 (Lehrplanbezüge) und Teil 3 (Sammlungsüberblick) laufen daneben und brauchen kein LLM. Die Schritte 1 bis 4
laufen bei jeder Anfrage, Schritt 5 nur auf Wunsch. Ein LLM steht nur bereit, wenn es konfiguriert ist:
`LLM_ENABLED=true` und `B_API_KEY`, Modell `gpt-6-luna` (`B_API_MODEL`, seit D44). Die Zahlen dieser Vorlage stammen
von `gpt-5.6-luna`; `gpt-6-luna` erreicht dieselbe Güte mit gleich bis 12 % mehr Tokens zum halben Preis je Token,
antwortet aber je Aufruf ein Viertel bis drei Viertel langsamer (M19). Ohne LLM oder bei einem Ausfall der b-api
laufen alle Schritte regelbasiert, und das Audit der Antwort nennt den tatsächlich genutzten Weg.

## Schritt 1: Hauptartikel finden

Der Dienst bereinigt das Thema („Physik: Optik in Klasse 7“ wird zu *Optik* mit dem Fach Physik als Kontext) und
sucht dann den Artikel, um den sich der Korpus dreht.

| Verfahren | Wie es arbeitet |
|---|---|
| v2.0.0 (nur zum Vergleich) | exakter Titel oder Weiterleitung; bei einer Begriffsklärung zählt, wie oft die Wörter der Anfrage wörtlich im Anfang jeder Bedeutung stehen; sonst Titelvorschläge und Volltextsuche. Nicht mehr wählbar. |
| **Regeln** (`rule-based`) | wie v2.0.0, aber mit den Kontextwörtern des Fachs aus `config/subjects.yaml`, Wortanfängen statt ganzer Wörter, dreifach gewertetem Titel, Personen und Werken erst zuletzt und Regeln für gebeugte Formen und Genitivwendungen. Sie melden, ob sie sich sicher sind (`method`, `confident`). |
| **Regeln und LLM** (`llm`) | erst die Regeln; nur wenn sie unsicher sind, wählt das LLM unter ihren Kandidaten oder nennt einen Titel, der nur zählt, wenn das Archiv ihn als Artikel hat. |
| laya (nur zum Vergleich) | ein kleines lokales Entscheidungsmodell (mmBERT-base, 322 Mio. Parameter) wählt an der Stelle des LLM unter den Kandidaten der Regeln. Ohne Nachtraining gemessen; nicht eingebaut (D42). |
| alter Weg (v0.2.0, nur zum Vergleich) | ein LLM nennt bei jeder Anfrage bis zu zehn Begriffe mit vermutetem Wikipedia-Titel, jeder wird nachgeschlagen; einen Hauptartikel wählt er nicht. Nicht eingebaut. |

**Profile:** `llm-free` nimmt `rule-based`, die übrigen `llm`, also auch der Standard `balanced` (D53).

| Einstellung | Werte | Standard |
|---|---|---|
| Anfrage: `article_choice` (Kompendium, `POST /api/v2/knowledge` und `/qa`) | `rule-based`, `llm` | aus dem Profil; bei `/qa` mit `topic` `rule-based` in allen Profilen (D55) |
| Anfrage: `preset` | `llm-free` setzt `rule-based`, die übrigen Profile `llm` | `PRESET_DEFAULT` |
| Umgebung: `PRESET_DEFAULT` | die vier Profile | `balanced` (D53); ein Dienst ohne LLM setzt `llm-free` |

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
| Materialien einer Sammlung (optional) | `knowledge_collection_id`: bis zu 30 Materialien mit je 20.000 Zeichen, wörtlich nur unter CC0, Public Domain, CC BY oder CC BY-SA; Bildung und Praxis bevorzugen sie. Am Goldstandard nicht gemessen. |

Artikel ohne das Themenwort im Titel geben nur die Absätze ab, die das Thema nennen. Mit `article_choice=llm`
benotet das LLM danach alle Korpusartikel in einem Aufruf, und Volltexttreffer und verlinkte Unterartikel mit der
Note 0 fallen heraus (D48); ohne solche Nebenartikel wird es nicht gefragt.

| Einstellung | Werte | Standard |
|---|---|---|
| Anfrage: `max_articles` | 1 bis 50 | `CORPUS_MAX_ARTICLES` = 12; Hauptartikel und Klexikon-Zwilling immer |
| Umgebung: `CORPUS_MAX_CHUNKS` | 20 bis 5.000 Absätze | 400 |
| Umgebung: `ZIM_PROFILE` | `compact` (Top-Artikel, 1,4 GB), `standard` (ganze Wikipedia und Klexikon), `extended` (dazu Wikibooks und Wikiversity) | `standard` |
| Anfrage: `knowledge_collection_id` | nodeId einer Sammlung | keine |
| Prüfung der Nebenartikel | über `article_choice` | an, wo `article_choice=llm` gilt |

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
- Wikibooks und Wikiversity (`extended`) bringen nichts: Mit ihrer Volltextsuche kam in 20 Themen ein gefüllter
  Baustein dazu (mit Trefferprüfung drei), und aus guten Unterrichtsseiten wie *Physikunterricht/ Optik* druckte der
  Standard keinen Absatz (M11).

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
| Umgebung: `LLM_MAX_TOKENS_PER_REQUEST` | Tokens je Anfrage | 60.000: vier Stapel zugleich, weitere warten (D39); 100.000 erlaubt sieben |

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

## Schritt 4: Text bauen und optional umformulieren

Der Text entsteht immer erst extraktiv: Je Baustein übernimmt der Dienst die zugeordneten Absätze wörtlich, ihre
ersten Sätze bis zum Längenbudget, jeden mit Belegnummer; dazu erzeugt er Akteure, Quellen und Glossar. Darauf setzen
drei Schalter auf.

| Schalter | Werte | Standard | Was er tut |
|---|---|---|---|
| `extraction` | `rule-based`, `llm` | `rule-based` in allen Profilen | `llm`: Das LLM wählt je Baustein Sätze aus bis zu acht Kandidatenabsätzen (`LLM_EXTRACTION_CANDIDATES`); der Wortlaut bleibt der der Quelle. |
| `generation` | `rule-based`, `llm-fast`, `llm` | `llm` in `best-quality-generated`, sonst `rule-based` | `llm-fast`: Das LLM schreibt Themendefinition und Querschnitt & Bezüge neu (`LLM_FAST_SECTIONS`); `llm`: alle Inhaltsbausteine. |
| `enrichment` | `sources-only`, `model-knowledge` | `model-knowledge` in `best-quality-generated`, sonst `sources-only` | `model-knowledge`: Das schreibende LLM darf eigenes Wissen ergänzen, ohne Belegnummer und sichtbar gekennzeichnet mit `[Modellwissen]` (D56); nur mit `generation` `llm` oder `llm-fast`. |
| `target_length` | 2.000 bis 60.000 Zeichen | 12.000 | steuert die Länge über Budgets je Baustein; eine Richtgröße, keine Obergrenze |
| `empty_slot_policy` | `omit`, `note` | aus dem Template, bei SC26 `omit` | leere Bausteine weglassen oder mit Hinweis zeigen |

**Kombinierbar:** `extraction` und `generation` lassen sich zusammen einschalten, `enrichment` wirkt nur mit
`generation`. Alle LLM-Schalter teilen sich das Budget je Anfrage (`LLM_MAX_TOKENS_PER_REQUEST`) und das Tagesbudget
(`LLM_DAILY_TOKEN_BUDGET`, 2 Mio.). Ein geschriebener Satz bleibt nur, wenn er eine gültige Belegnummer trägt und
mindestens 20 % seiner Inhaltswörter im zitierten Absatz stehen; sonst wird er gestrichen
(`LLM_UNSUPPORTED_SENTENCES=drop`) oder als Schlussfolgerung markiert (`mark`).

| Schalter | Zeit | Tokens | Güte |
|---|---|---|---|
| extraktiv (Standard) | 1,1 s auf dem Server, samt Akteuren, Quellen, Glossar | 0 | jeder Satz wörtlich im zitierten Absatz (432 von 432) |
| `extraction=llm` | rund 11 s | 14.000 bis 22.400 | 14 richtige Absätze mehr bei gleicher Präzision (59 %) gegenüber derselben Konfiguration ohne LLM; kleine Bausteine oft falsch |
| `generation=llm-fast` | 9 bis 15 s | 2.300 bis 4.000 | flüssiger Einstieg; Belegprüfung |
| `generation=llm` | 16 bis 20 s | 10.500 bis 14.500 | flüssiger Text; Belegprüfung, im Median 73 % der Inhaltswörter im zitierten Absatz |
| beide auf `llm` | 18 s (Optik) | 27.205 (Optik) bis rund 37.000 | |
| `best-quality-generated` gegen `best-quality` (M27, M28, gpt-6-luna) | rund 8,8 s mehr | 4.300 bis 11.600 mehr | Lesbarkeit 4,0 statt 2,5, in 11 von 12 Urteilen vorgezogen; im Mittel 12 Füllsätze je Thema, mit Prompt v2 5 (M31) |

![Zeit und Tokens der Text-Schalter](bilder/text_schalter.svg)

**Beobachtungen**

- Für Maschinen, also Suche, KI-Assistenten und Weiterverarbeitung, ist der extraktive Text der beste: Jeder Satz
  steht wörtlich in seiner Quelle. Für Menschen liest er sich wie eine geordnete Sammlung von Auszügen; dafür ist
  `generation` gedacht.
- `extraction=llm` wurde am 19.09.2026 ohne Model2Vec gemessen. Gegenüber dem heutigen Standard (110 gedruckte
  Absätze, 67 richtig, 61 %) sind 131 und 77 (59 %) nur ein Anhaltspunkt; in Querschnitt & Bezüge landeten 7 Absätze,
  keiner richtig. Keine Empfehlung.
- Die übrigen Werte der Text-Schalter stammen vom 18. und 19.09.2026 an vier Themen bzw. an Optik (gpt-5.6-luna). Die
  Lesbarkeit maß M28 an sechs Themen, blind von zwei Gutachtern: Der geschriebene Text liest sich besser (4,0 statt 2,5
  von 5, in 11 von 12 Urteilen vorgezogen), trug aber im Mittel 12 Füllsätze je Thema; zwei Drittel des ergänzten
  Modellwissens waren Füllsätze. Der zweite Prompt (D56) senkt das auf 13 von 50 ergänzten Sätzen und 5 Füllsätze je
  Thema (M31).

## Kosten und Kapazität

| Profil | Tokens je Kompendium, Median (Spanne), M27 | Kompendien je Tag bei 2 Mio. Tokens |
|---|---|---|
| `llm-free` | 0 | ohne Grenze |
| `balanced` | 905 (750 bis 1.103) | rund 2.200 |
| `balanced` mit `generation=llm-fast` | rund 3.200 bis 4.900 (addiert) | rund 400 bis 620 |
| `best-quality` | 26.267 (4.942 bis 54.448) | rund 76 |
| `best-quality-generated` | 35.376 (9.223 bis 65.975) | rund 57 |

Die Profile maß M27 auf denselben sechs Themen; die Zeile mit `llm-fast` ist addiert. Große Themen kosten mehr: Mit
323 Absätzen brauchte Renaissance 54.448 und 65.975 Tokens. Das Tagesbudget gilt für alle Anfragen
und Worker zusammen; ist es aufgebraucht, fallen LLM-Schalter bis zum nächsten Tag auf die Regeln zurück.

## Die Empfehlungen im Einzelnen

### `llm-free`: das Optimum ohne Sprachmodell

Anfrage: `{"topic": "Optik", "preset": "llm-free"}`; ein Dienst ohne LLM stellt es als Vorgabe ein:

```
PRESET_DEFAULT=llm-free                 # ausgeliefert ist balanced (D53)
MODEL2VEC_PATH=/models/m2v              # im Image gesetzt; ohne Model2Vec 0,38 statt 0,43
ZIM_PROFILE=standard
CORPUS_MAX_ARTICLES=12
```

Ergebnis: 86 von 94 Hauptartikeln, 12 von 352 gedruckten Absätzen aus unpassenden Artikeln (M25), macro-F1 0,45, Teil 1
und 2 in 1,6 s ohne Tokens (M27), QA-Paare aus den Regeln über den spaCy-Parse, 48 von 96 mangelfrei in 0,3 s je Text
(M30). Bei einem Material ohne `topic` trifft sie den Hauptartikel mit F1 0,56 bis 0,63; findet sie keinen, fragt der
404 nach einem `topic`. Keine andere lokale Einstellung war besser: Die übrigen Verfahren verlieren in kleinen
Bausteinen, Wikibooks und Wikiversity bringen nichts, schwerere Modelle schaden.

### `balanced`: Zeit und Kosten optimiert bei guter Qualität (Standard)

Anfrage: `{"topic": "Optik"}` genügt. Dafür muss ein LLM konfiguriert sein:

```
LLM_ENABLED=true
B_API_KEY=…                             # aus dem Geheimnisspeicher, nie im Repository
PRESET_DEFAULT=balanced                 # ausgeliefert
```

Ergebnis: 91 von 94 Hauptartikeln, 5 von 346 gedruckten Absätzen aus unpassenden Artikeln (M25), bei einem Material ohne
`topic` F1 0,88 bis 0,98, macro-F1 0,45 wie `llm-free` (M27), Teil 1 und 2 rund 3,4 s und 905 Tokens (M27; in M25
kostete Teil 1 im Median 2,0 s mehr als ohne LLM, 90. Perzentil 4,2 s). QA-Paare aus denselben Regeln wie `llm-free`,
48 von 96 mangelfrei in 0,3 s je Text (M30, D57). Wer einen lesbaren Einstieg braucht, ergänzt
`"generation": "llm-fast"`: 9 bis 15 s und 2.300 bis 4.000 Tokens mehr für Themendefinition und Querschnitt
(gpt-5.6-luna, 18.09.2026).

### `best-quality`

Anfrage: `{"topic": "Optik", "preset": "best-quality"}`, mit konfiguriertem LLM wie oben und mehr Budget je Anfrage:

```
LLM_MAX_TOKENS_PER_REQUEST=100000       # sieben Stapel zugleich: keine zweite Runde bis 350 Absätze und kein
                                        # Rückfall bei sehr großen Themen (bei 60.000 ab rund 320 Absätzen);
                                        # nicht gemessen
```

Ergebnis: 91 von 94 Hauptartikeln, macro-F1 0,70 (M19, gpt-6-luna), Teil 1 und 2 rund 14 s (11 bis 16 s), im Median
26.267 Tokens, rund 170 je Absatz (M27). Der Text bleibt wörtlich und belegt. QA-Paare vom LLM, 99 von 120 mangelfrei
(M30).

### `best-quality-generated`

Anfrage: `{"topic": "Optik", "preset": "best-quality-generated"}`, mit LLM und Budget wie bei `best-quality`.

Ergebnis: wie `best-quality`, dazu schreibt das LLM jeden Baustein und darf eigenes Wissen ergänzen, sichtbar
gekennzeichnet mit `[Modellwissen]`; rund 24 s (19 bis 28 s) und im Median 35.376 Tokens (M27), mit dem zweiten Prompt
rund 3 % mehr (M31). Zwei blinde Gutachter zogen den geschriebenen Text in 11 von 12 Urteilen dem wörtlichen vor
(Lesbarkeit 4,0 statt 2,5 von 5, Zusammenhang 4,0 statt 2,4), bei ähnlich vielen Fachfehlern, die meist schon in den
Quellen stehen (M28). Mit dem zweiten Prompt (D56) sind 13 von 50 ergänzten Sätzen Füllsätze statt 50 von 82, 32 statt
27 fachlich und keiner nach beiden Gutachtern falsch; im Mittel bleiben 5 Füllsätze je Thema statt 12, und v2 wurde in 8
von 12 Urteilen vorgezogen (M31). Wer den geschriebenen Text ohne Modellwissen will, setzt `"enrichment":
"sources-only"`; dann bleibt jeder Satz belegt.

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

1. **Vorgabe im Betrieb:** entschieden (D53): `balanced`. Vor dem nächsten Deployment brauchen die Server
   `LLM_ENABLED`, den Produktivschlüssel in `B_API_KEY` und ein Tagesbudget, sonst `PRESET_DEFAULT=llm-free`.
2. **Beste Qualität als eigener Weg:** entschieden (D53) als Profil `best-quality`, rund 26.000 Tokens und 14 s je
   Kompendium (M27).
3. **Lesefassung:** entschieden (D53) als Profil `best-quality-generated`; gemessen in M28: Der geschriebene Text liest
   sich besser (4,0 statt 2,5 von 5, in 11 von 12 Urteilen vorgezogen). Das Modellwissen ist seit D56 im Text sichtbar
   gekennzeichnet (`[Modellwissen]`, Jan), und der zweite Prompt verlangt eine prüfbare Sachaussage oder nichts: 13
   statt 50 Füllsätze bei 50 statt 82 ergänzten Sätzen (M31). Offen: ob er auch rhetorische Fragen verbieten soll, drei
   der 13 übrigen Füllsätze.
4. **Goldstandard prüfen lassen:** Alle Gütezahlen hängen an Labels, die eine Redaktion noch nicht gesehen hat.
5. **Sichere Fehler der Regeln:** ob das LLM mit `article_choice=llm` auch sichere Auflösungen mehrdeutiger Wörter
   prüfen soll. Der alte Weg fand zwei der drei (M17); es kostete einen Aufruf mehr bei jedem solchen Thema und wäre
   vorher am Gold zu messen.
6. **QA-Verfahren je Profil:** entschieden (D57). `llm-free` und `balanced` fragen mit den Regeln, die beiden
   `best-quality`-Profile mit dem LLM; die zwei kleinen Modelle (in M30 25 von 120 mangelfrei, rund 25 s je Text,
   1,3 GB je Worker) und `parse-based` sind aus Code und Image entfernt. Die vier alten Vorlagen bleiben nur als
   Rückfall, wenn das spaCy-Modell fehlt.
7. **Regeln der QA verbessern:** Ihr häufigster Mangel ist eine Frage, die ohne den Text unverständlich ist (23 und 24
   von 96), etwa „Wo befinden sich die Kurszentren?“. Weitere Sperren gingen ohne Modell (nebengeordnete Sätze,
   Maßverben wie „dauern“, Fragen ohne Inhalt wie „Was ist notwendig?“), wären aber an M30 nachzumessen.

Seit D53 offen: eine KI-Prüfung der Lehrplanelemente für die LLM-Profile. Sie ist nicht gebaut, weil sie die Texte der
Elemente aus dem MEM-Cache an die b-api schicken würde, und ob MEM-Daten weitergegeben werden dürfen, ist nicht geklärt:
Die Lizenz der MEM-Daten ist unbestätigt (PLAN.md 13.1, Manifest `unconfirmed`) und vor dem Produktivbetrieb mit der FWU
zu klären; bis dahin zitiert der Dienst nur Bezeichnungen und Links. Die Menge wäre lösbar: Mit Fach läse das LLM im
Mittel 158 Elemente je Thema, bei breiten Themen über 500 (M22). Bis dahin arbeiten die Lehrplanbezüge in allen Profilen
mit Regeln.

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
7. **Lehrplanbezüge (Teil 2, M22):** Rund 60 % der ausgegebenen Lehrplanelemente gehören zum Thema, 13 bis 19 %
   passen nicht. Das Fach kürzt Teil 2 um ein Drittel, hebt die Treffsicherheit aber kaum und verwirft ein Viertel
   der passenden Elemente. Empfehlung: schärfere Stichwortregeln (lokal, verwerfen kein passendes Element) und nach
   einem Blick auf die Darstellung die Elemente, bei denen nur die Überschrift das Thema nennt, zu ihrem Bereich
   bündeln.
8. **Offene Punkte der Durchsicht vom 25.09.2026:** Behoben sind die Fehler (Messprotokoll, M25). Die Punkte, die
   ändern, was Aufrufer bekommen, hat Jan am 25.09.2026 zur Umsetzung nach Empfehlung freigegeben:
   - `/qa` mit `text` und zugleich `topic` oder `node_id` nahm den Text nicht, ohne es zu sagen. Umgesetzt (D49): 422,
     wie bei `/entities`; ebenso `subject`, `preset` und `article_choice` ohne Thema.
   - Ein unbekanntes `subject` („Pysik“) wurde still übergangen, Teil 2 suchte dann in allen Fächern; unbekannte Namen
     in `regenerate_sections` erneuerten nichts; unbekannte Felder aller Anfragen fielen still weg. Umgesetzt (D49):
     422 mit den erlaubten Werten; Fächer seit D51 gegen die beiden Fachvokabulare von edu-sharing.
   - `/lehrplan/search` sucht die Wörter, wie sie kommen, Teil 2 den aufgelösten Artikel, seine Aliase und Unterthemen.
     Vorschlag: ein Themen-Modus, der wie Teil 2 auflöst; zu messen an den 20 Themen von M22.
   - Die CLI kannte keinen Knoten, `/qa` mit der Stufe `llm` öffnete nach dem Kompendium ein zweites Token- und
     Zeitbudget, und eine unbekannte `knowledge_collection_id` ergab 200 mit dem Fehler im Audit, eine unbekannte
     `collection_id` 404. Umgesetzt (D49): `--node-id` und `--repository`, ein Budget je Anfrage, 404 vor jedem
     LLM-Aufruf. `/matching/compare` ist entfallen (D50): Im Betrieb braucht ihn niemand, und `compendium eval`
     vergleicht die Strategien auf dem Gold. Wie der Comparator wählt `compendium eval` die Artikel ohne LLM; die
     Zuordnung einer Stufe mit LLM-Artikelwahl braucht deshalb eine eigene Messung.
   - Die Links des Hauptartikels werden je Anfrage neu aufgelöst, bei großen Artikeln bis 0,7 s (*Deutschland*); ein
     Zwischenspeicher je Archiv spart das bei Wiederholungen.
