# Messprotokoll (23.09.2026)

[Übersicht](README.md) · Skripte und Ergebnisdateien: [messung/](messung/README.md)

## Umgebung

| Was | Stand |
|---|---|
| Server | Hostinger, Image v2.0.0 aus GHCR, zwei Worker; Archive `wikipedia_de_all_nopic_2026-01` und `klexikon_de_all_maxi_2026-08`; Lehrplan-Cache vom 22.09.2026; edu-sharing `repository.staging.openeduhub.net` |
| Entwicklungsrechner | Windows 11, Python 3.13.5; venv des neuen Dienstes, venv der Testapp (torch 2.14, transformers 5.17, model2vec 0.9), venv des alten Dienstes nach seiner Lock-Datei (openai 2.26, aiohttp 3.12.13); dieselben Archive |
| Testsuite | 767 Tests bestanden, 94,11 % Abdeckung mit `matcher=llm` (D34); Stand `02070a3` nach 2.0.0: 753 Tests, 94,04 %; Schwelle der CI 90 % |
| Sprachmodelle | `gpt-4.1-mini` für den alten Dienst, `gpt-5.6-luna` für den Richter und als Zuordner, alle über die b-api |
| Tokens für diese Messungen | alter Dienst 87.710 (`gpt-4.1-mini`); mit `gpt-5.6-luna`: Richter 67.936, LLM als Zuordner 144.596, Richter der Artikelwahl 21.166, `matcher=llm` im Dienst 144.486 laut b-api, davon acht Themen aus ihrem Zwischenspeicher |

Gerundet wird kaufmännisch. Nebenwerte (Testsuite, Entitätenerkennung, Kiefer-Alternativen, Länge von Teil 2,
Knotenzeilen von Teil 3) stehen in `messung/ergebnisse/nebenwerte.txt`, die Suchzeiten des Wikipedia-Archivs in
`zim_suche.json`: Titelvorschlag im Median 2,9 ms, Volltextsuche 0,4 ms, gemessen auf dem Entwicklungsrechner direkt
nach den Korpusläufen, also mit der Datei im Speicher des Betriebssystems.

## M1 Laufzeit des neuen Dienstes

**Aufbau:** 20 Themen (die zehn Goldthemen, die vier Richterthemen und sechs weitere Schulthemen). Nach einer
Aufwärmanfrage kam jedes Thema einmal (Durchgang 1), danach alle noch einmal (Durchgang 2), jeweils mit Teil 1 und 2.
Dazu kamen drei Sammlungen mit allen drei Teilen und mit Teil 3 allein. Jede Anfrage schaltete das Sprachmodell
ausdrücklich ab; kein Audit meldete eine LLM-Nutzung. 47 Anfragen, alle mit HTTP 200.

| Server | Median | 90. Perzentil | Maximum |
|---|---|---|---|
| Teil 1 und 2, Durchgang 1 | 2,81 s | 3,96 s | 4,34 s |
| Teil 1 und 2, Durchgang 2 | 1,98 s | 2,61 s | 3,42 s |
| alle drei Teile (drei Sammlungen) | 3,09 s | – | 5,52 s |
| Teil 3 allein | 0,16 s | – | 0,16 s |

| Schritt (Durchgang 1, Median) | Dauer |
|---|---|
| Thema auflösen | 32 ms |
| Korpus aus den Archiven | 882 ms |
| Segmentieren | 18 ms |
| Zuordnen | 291 ms |
| Text bauen (samt Akteuren, Quellen, Glossar) | 1.087 ms |
| Teil 2 | 240 ms |
| Zusammensetzen | 3 ms |

Beim ersten Abruf einer Sammlung kostete Teil 3 bis 3,45 s. Im lokalen Container dauerte Durchgang 1 im Median
7,0 s, weil Docker Desktop die Archive über das Windows-Dateisystem liest; für den Vergleich zählen die
Serverwerte. Die Entitätenerkennung brauchte für einen Beispielsatz 0,07 bis 0,15 s.

## M2 Alter Dienst

**Aufbau:** Der Code v0.2.0 blieb unverändert. Ein Messrahmen ruft die Funktion hinter
`POST /api/v1/pipeline-compendium-only` direkt auf und zeichnet an zwei Bibliotheksaufrufen auf: jeden Chat-Aufruf
(Dauer, Tokens) und jede HTTP-Anfrage (Adresse, Status, Dauer). Modell `gpt-4.1-mini` am b-api-Endpunkt `openai`;
das Standardmodell im Code, `deepseek-r1`, bietet die b-api nicht mehr an.

- **Wie ausgeliefert** (User-Agent ohne Kontakt), Thema Optik: 374,3 s, 12 Modellaufrufe (1 für Begriffe,
  10 für Synonyme, 1 für den Text), 4.926 Tokens; 240 Wikipedia-Anfragen, alle mit 403 beantwortet; keine Quelle.
  Der Aufruf endete ohne Fehler, über HTTP wäre das ein 200. Ergebnis: 11.906 Zeichen Text, 78 Sätze, 15 Verweise
  „(1)“, Literaturverzeichnis „Keine Referenzen verfügbar“.
- **Nachstellung der Abweisung:** Dieselbe Anfrage über aiohttp mit dem alten User-Agent ergab 403 mit Verweis auf
  die Robot-Policy von Wikimedia, mit einer Kontaktadresse im User-Agent 200. Über `curl` kam auch der alte
  User-Agent durch; Wikimedia bewertet also vermutlich Client und User-Agent zusammen.
- **Bester Fall** (`PROJECT_NAME` mit Kontaktadresse, Code unverändert), zehn Goldthemen:

| Thema | Dauer | Aufrufe | Tokens | Wikipedia-Anfragen | Begriffe mit Artikel | verschiedene Artikel | Begriffsklärungen | Sätze | mit Quellenangabe | gestützt |
|---|---|---|---|---|---|---|---|---|---|---|
| Barockliteratur | 37,0 s | 3 | 8.685 | 12 | 9 von 9 | 9 | 0 | 101 | 20 | 18 |
| Bruchrechnung | 60,4 s | 7 | 8.200 | 34 | 8 von 10 | 5 | 0 | 95 | 12 | 11 |
| Demokratie | 32,6 s | 2 | 7.819 | 10 | 10 von 10 | 10 | 0 | 87 | 29 | 28 |
| Französische Revolution | 29,4 s | 4 | 7.220 | 16 | 10 von 10 | 10 | 0 | 81 | 29 | 27 |
| Klimawandel | 28,8 s | 2 | 11.044 | 10 | 10 von 10 | 10 | 0 | 83 | 9 | 8 |
| Optik | 30,8 s | 4 | 7.880 | 18 | 10 von 10 | 10 | 4 | 76 | 17 | 15 |
| Photosynthese | 28,6 s | 2 | 7.946 | 10 | 10 von 10 | 9 | 0 | 77 | 28 | 27 |
| Programmiersprache | 43,1 s | 6 | 7.307 | 22 | 10 von 10 | 10 | 4 | 95 | 28 | 18 |
| Säure-Base-Konzepte | 62,4 s | 7 | 8.845 | 32 | 9 von 10 | 8 | 2 | 110 | 30 | 26 |
| Sinfonie | 37,5 s | 2 | 7.838 | 10 | 10 von 10 | 10 | 0 | 111 | 18 | 14 |
| **Summe oder Median** | **Median 34,8 s** | **39** | **82.784** | **174** | **96 von 99** | **91** | **10** | **916** | **220 (24 %)** | **192 (21 %)** |

Die 82.784 Tokens verteilen sich auf 46.590 Eingabe- und 36.194 Ausgabetokens. Der Textaufruf dauerte im Median 26,3 s
und schrieb im Median 2.865 Tokens. Die Wikipedia-Anfragen dauerten je Thema zusammen im Median 3,3 s (2,3 bis
22,6 s). „Gestützt“ heißt: Mindestens 20 % der Inhaltswörter eines Satzes stehen in der Einleitung, auf die er
verweist; geprüft mit dem Belegcode des neuen Dienstes. 25 zitierte Sätze fielen durch, 3 waren zu kurz für ein
Urteil. Die 696 Sätze ohne Quellenangabe wurden nicht mit den Quellen verglichen. Die Begriffsklärungen waren Brechen,
Beugung, Polarisierung, Interferenz (Optik), Bedeutungslehre, Assembler, Hochsprache, Verfahren (Programmiersprache)
sowie Säuregrad und Wasserstoffion (Säure-Base-Konzepte). Einzelwerte je Thema:
`messung/ergebnisse/m2_alter_dienst_details.json`.

## M3 Teil 1 im neuen Dienst

**Aufbau:** Die zehn Goldthemen, nur Teil 1, regelbasiert, vom Server. Lokal wurde derselbe Korpus aus denselben
Archiven aufgebaut, sodass hinter jeder Belegnummer der zitierte Absatz bekannt ist. Geprüft wurden die gematchten
Bausteine 1 bis 5 und 7 bis 11: Jeder Satz mit eigener Belegnummer muss wörtlich in dem Absatz stehen, auf den die
Nummer zeigt. Listenpunkte tragen keine eigene Nummer, weil die Liste als Ganzes belegt ist; sie müssen in einem der
Absätze stehen, die ihr Baustein zitiert. Tabellenzeilen wurden nicht geprüft. Die Sätze wurden mit demselben Code
zerlegt wie beim alten Dienst. Die Dauer stammt aus dem ersten Lauf; die Belegprüfung lief in einem zweiten Lauf mit
denselben Texten.

| Thema | Dauer Teil 1 | Quellartikel | belegte Bausteine (samt erzeugten) | Zeichen Bausteintext | Markdown gesamt | Sätze mit eigener Nummer, im zitierten Absatz | Listenpunkte, im Baustein belegt |
|---|---|---|---|---|---|---|---|
| Barockliteratur | 1,6 s | 2 | 7 von 13 | 5.838 | 19.098 | 34 von 34 | – |
| Bruchrechnung | 2,4 s | 5 | 4 von 13 | 3.014 | 11.493 | 23 von 23 | – |
| Demokratie | 2,1 s | 12 | 11 von 13 | 9.466 | 29.470 | 55 von 55 | 7 von 7 |
| Französische Revolution | 2,3 s | 12 | 9 von 13 | 7.091 | 23.936 | 33 von 33 | 11 von 11 |
| Klimawandel | 2,4 s | 9 | 11 von 13 | 8.721 | 26.475 | 45 von 45 | – |
| Optik | 1,1 s | 12 | 11 von 13 | 8.121 | 31.785 | 62 von 62 | – |
| Photosynthese | 2,5 s | 8 | 7 von 13 | 6.419 | 19.460 | 39 von 39 | – |
| Programmiersprache | 1,5 s | 12 | 12 von 13 | 12.390 | 34.061 | 70 von 70 | 8 von 8 |
| Säure-Base-Konzepte | 1,9 s | 3 | 6 von 13 | 2.995 | 12.035 | 21 von 21 | – |
| Sinfonie | 1,8 s | 12 | 10 von 13 | 9.261 | 29.470 | 50 von 50 | – |
| **Summe oder Median** | **Median 2,0 s** | **Median 10,5** | | **Median 7.606** | **Median 25.206** | **432 von 432** | **26 von 26** |

Weitere Prüfungen (`messung/ergebnisse/m3_pruefungen.txt`):

- In allen zehn Themen ist der Hauptartikel die erste Quelle. Unter den 87 Quellen ist keine Begriffsklärungsseite.
- Zweimal dieselbe Anfrage (Photosynthese, Teil 1 und 2) ergab bis auf den Zeitstempel denselben Text von 93.335
  Zeichen.
- Keine Belegnummer zeigte auf einen Absatz, den es im lokal aufgebauten Korpus nicht gibt.

## M4 Zuordnung: alle Verfahren im Ablauf des Dienstes

**Aufbau:** Für jedes der zehn Themen wurde der Korpus mit dem Code 2.0.0 gebaut, zusammen 1.632 Absätze, und die 603
noch bewertbaren Labels wurden zugeordnet; 40 von 643 Labels passen zu keinem heutigen Absatz mehr. Jedes Verfahren
nimmt den Weg von `CompendiumService.match`: Ranker, Zusammenführung, Glättung und Policy mit einem Längenziel von
12.000 Zeichen.

- **Ranker des Dienstes:** direkt gerechnet. Ein Nachbau von `hybrid_light` aus seinen Bestandteilen ergab auf
  allen zehn Themen und in beiden Pools dieselbe Zuordnung wie der Dienst.
- **Modelle der Testapp:** Sie bewerteten zuerst in der Umgebung der Testapp alle Paare aus Baustein und Absatz.
  Dabei sahen sie dieselben Texte wie die Ranker des Dienstes: Überschriftenpfad plus Text gegen Titel,
  Beschreibung, Inhalte, Unterpunkte und Suchbegriffe. Ihre Werte liefen dann als Ranker durch denselben Weg.
- **Frage-Antwort-Modell:** Es prüfte wie in der Testapp nur die 15 besten MiniLM-Kandidaten je Baustein, mit
  ihrer Formel ohne die Stichwort-Boni.

Klassifikation heißt die Entscheidung je Absatz vor den Längenbudgets (macro- und micro-F1). „Richtig unter Top 2“
zählt unter den zwei besten Absätzen je Baustein die mit Gold-Label, die richtig sitzen. Die Tabelle gilt für den
vollen Kandidatenpool, also alle Absätze des Korpus:

| Verfahren | macro-F1 | micro-F1 | zugeordnet | davon falsch | richtig unter Top 2 | belegte Bausteine | Rechenzeit je Thema |
|---|---|---|---|---|---|---|---|
| nur Überschriften-Lexikon | 0,35 | 0,65 | 518 | 184 | 63,9 % | 5,1 | 0,02 s |
| BM25 | 0,37 | 0,65 | 525 | 189 | 61,5 % | 5,6 | 0,03 s |
| Zeichen-TF-IDF | 0,42 | 0,64 | 538 | 203 | 55,6 % | 7,1 | 0,25 s |
| Model2Vec allein | 0,45 | 0,62 | 550 | 218 | 53,7 % | 7,3 | 0,04 s |
| MiniLM-Satzvektoren allein | 0,37 | 0,60 | 550 | 229 | 48,3 % | 7,3 | 4,1 s |
| Cross-Encoder allein | 0,30 | 0,53 | 550 | 270 | 35,6 % | 8,8 | 73,3 s |
| Frage-Antwort-Modell (MiniLM-Kandidaten) | 0,38 | 0,65 | 527 | 190 | 55,6 % | 6,1 | 29,8 s |
| BM25 + Model2Vec | 0,44 | 0,65 | 535 | 194 | 62,9 % | 5,9 | 0,05 s |
| `hybrid_light` ohne Model2Vec | 0,39 | 0,65 | 531 | 193 | 61,2 % | 6,0 | 0,26 s |
| **Standard** (`hybrid_light` + Model2Vec) | 0,45 | 0,66 | 533 | 189 | 67,1 % | 6,0 | 0,30 s |
| Standard, vom Cross-Encoder umsortiert | 0,35 | 0,51 | 568 | 289 | 37,9 % | 8,6 | 14,9 s |
| Standard + Cross-Encoder als vierter Ranker | 0,37 | 0,64 | 535 | 197 | 57,9 % | 6,5 | 73,6 s |

Rechenzeiten (Entwicklungsrechner, nur CPU):

- **Ranker des Dienstes:** Mittelwert über die zehn Themen mit Aufwärmlauf.
- **Modelle der Testapp:** Median je Thema für ihre Paare. Der Cross-Encoder schaffte 46,8 ms je Paar. Das
  Frage-Antwort-Modell brauchte über alle Paare für Demokratie allein 746 s, deshalb die Kandidaten.
- **Umsortieren:** der Standard plus die Cross-Encoder-Zeit für die Kandidatenpaare, im Median rund 310 je Thema.

Nur auf den 603 gelabelten Absätzen gerechnet (Goldpool), bleibt die Reihenfolge fast gleich (M5). Die F1-Werte je
Baustein stehen in `messung/ergebnisse/m3_pruefungen.txt`, die vollständige Ausgabe in `m4_goldstandard.txt` und
`m4_tabellen.json`.

## M5 LLM als Zuordner

**Aufbau der ersten Messung (Skript `mc_llm_matcher.py`):** `gpt-5.6-luna` über die b-api, mit den
Voreinstellungen des Dienstes (`reasoning_effort` und `verbosity` niedrig), bekam je Aufruf:

- die zehn Inhaltsbausteine mit Titel, Beschreibung, „gehört hinein“ und „gehört nicht hinein“;
- die Labelregeln des Goldstandards aus `eval/README.md`;
- 25 Absätze, je mit Artikel und dessen Rolle, Überschriftenpfad und Text (bis 700 Zeichen).

Es antwortete je Absatz mit Baustein oder „keiner“ und einer Sicherheit von 0 bis 1. Die Sicherheit ordnet die
Absätze je Baustein für „richtig unter Top 2“. Vier Aufrufe liefen parallel. Das Ergebnis: 28 Aufrufe, keiner
fehlgeschlagen, alle 603 Absätze beantwortet, kein unbekannter Baustein-Schlüssel.

**Nachmessung im Dienst (`matcher=llm`, D34, Skript `mc_llm_dienst.py`):** Der Prompt ging unverändert in den
Dienst; die Regeln stehen dort als `assignment_rules` im Template. Ein Vergleich der Anfragen ergab in 29 Stapeln
aus drei Themen Zeichen für Zeichen dieselben. Für jedes Goldthema baute `CompendiumService.prepare` den Korpus, er
wurde auf die gelabelten Absätze geschnitten, und `CompendiumService.match` lief mit `matcher=llm`, vier Aufrufe
parallel. Das Ergebnis: 28 Aufrufe, keiner fehlgeschlagen, kein Absatz fiel auf die Regeln zurück. Der Dienst gab
601 Absätze an das Modell, weil er zwei für das Akteursverzeichnis zurückhält; die b-api meldete 144.486 Tokens.
Acht Themen beantwortete sie aus ihrem Zwischenspeicher, mit denselben Antworten und Tokenzahlen wie im ersten Lauf
und 0,1 bis 3,3 s je Thema. In Optik und Sinfonie verschoben die zurückgehaltenen Absätze die Stapel, das Modell
antwortete neu (8,7 und 8,1 s), und 17 von 154 Entscheidungen wichen vom ersten Lauf ab. Im Dienst zählt „richtig
unter Top 2“ nach den Längenbudgets wie bei allen anderen Verfahren; der erste Lauf kannte keine Budgets. Zum
Vergleich wurden alle Verfahren aus M4 auf denselben 603 Absätzen gemessen:

| Verfahren | macro-F1 | micro-F1 | zugeordnet | davon falsch | richtig unter Top 2 |
|---|---|---|---|---|---|
| **`matcher=llm` im Dienst** | 0,66 | 0,79 | 547 | 125 | 74,8 % |
| `gpt-5.6-luna`, erste Messung | 0,63 | 0,79 | 547 | 128 | 72,6 % |
| nur Überschriften-Lexikon | 0,35 | 0,65 | 518 | 184 | 63,3 % |
| BM25 | 0,36 | 0,63 | 536 | 203 | 59,8 % |
| Zeichen-TF-IDF | 0,40 | 0,61 | 551 | 223 | 51,4 % |
| Model2Vec allein | 0,41 | 0,57 | 566 | 260 | 43,2 % |
| MiniLM-Satzvektoren allein | 0,37 | 0,57 | 562 | 254 | 41,7 % |
| Cross-Encoder allein | 0,29 | 0,45 | 570 | 327 | 30,6 % |
| Frage-Antwort-Modell (MiniLM-Kandidaten) | 0,37 | 0,64 | 531 | 196 | 53,7 % |
| BM25 + Model2Vec | 0,43 | 0,64 | 546 | 208 | 58,3 % |
| `hybrid_light` ohne Model2Vec | 0,38 | 0,63 | 543 | 207 | 57,4 % |
| **Standard** (`hybrid_light` + Model2Vec) | 0,43 | 0,64 | 546 | 205 | 60,8 % |
| Standard, vom Cross-Encoder umsortiert | 0,32 | 0,43 | 584 | 345 | 35,0 % |
| Standard + Cross-Encoder als vierter Ranker | 0,36 | 0,63 | 546 | 214 | 52,9 % |

**Kosten und Zeit der ersten Messung:** 144.596 Tokens für 603 Absätze, also rund 240 je Absatz. Je Aufruf im Median
5,5 s (höchstens 9,8 s), je Thema im Median 7,5 s Wandzeit. Hochgerechnet mit einem Aufruf je angefangene 25 Absätze,
vier Aufrufen parallel und 240 Tokens je Absatz kostet ein ganzes Kompendium im Median rund 39.000 Tokens (5.500 bis
92.000) und 11 s (höchstens 22 s). Beurteilte das LLM nur die Absätze, die die Ranker überhaupt vorschlagen, wären es
im Median 109 von 162 Absätzen und rund 26.000 Tokens. Die Antworten je Absatz stehen in
`messung/ergebnisse/m5_llm_zuordnung.json`, die Entscheidungen des Dienstes in `m5_llm_dienst.json`.

## M6 Gegenprobe: blinder LLM-Richter

**Aufbau:** Vier Themen, an denen nichts abgestimmt wurde: Plattentektonik, Ökosystem, Atommodell (Weiterleitung
auf *Liste der Atommodelle*) und Industrielle Revolution. Das sind andere Daten als der Goldstandard. Beurteilt
wurden die Verfahren des Dienstes, je Baustein ihre zwei besten Absätze. Je Thema und Baustein wurde die Vereinigung
aller Auswahlen einmal bewertet, gemischt und ohne Verfahrensnamen, acht Absätze je Aufruf, mit dem Prompt vom
18.09.2026. Bewertung: 2 = gehört klar hinein, 1 = teilweise, 0 = gehört nicht hinein.

Bewertungen vom 18.09. wurden übernommen, wo Absatztext und Bausteinbeschreibung unverändert waren. Der erste Lauf
kostete 48 Aufrufe und 62.101 Tokens; ein Teil davon galt Auswahlen aus dem Ablauf der Testapp, die nicht vergleichbar
sind und hier nicht aufgeführt werden. Der Lauf für Model2Vec allein und BM25 + Model2Vec kostete 11 Aufrufe und
5.835 Tokens.

| Verfahren | Absätze | Ø Note | klar | teilweise | falsch | belegte Bausteine | mit Volltreffer |
|---|---|---|---|---|---|---|---|
| **Standard** | 39 | 1,33 | 61,5 % | 10,3 % | 28,2 % | 5,50 | 3,75 |
| BM25 + Model2Vec | 39 | 1,36 | 61,5 % | 12,8 % | 25,6 % | 5,25 | 3,75 |
| `hybrid_light` ohne Model2Vec | 38 | 1,37 | 63,2 % | 10,5 % | 26,3 % | 5,25 | 3,75 |
| Zeichen-TF-IDF | 42 | 1,31 | 59,5 % | 11,9 % | 28,6 % | 5,75 | 3,75 |
| BM25 | 38 | 1,37 | 63,2 % | 10,5 % | 26,3 % | 5,25 | 3,75 |
| nur Überschriften-Lexikon | 38 | 1,39 | 63,2 % | 13,2 % | 23,7 % | 5,25 | 3,75 |
| Model2Vec allein | 49 | 1,16 | 49,0 % | 18,4 % | 32,7 % | 7,00 | 4,25 |

„Belegte Bausteine“ und „mit Volltreffer“ (mindestens ein Absatz mit Note 2) sind Mittelwerte je Thema, von zehn
Inhaltsbausteinen. Je Thema, Anteil klar und falsch:

| Verfahren | Plattentektonik | Ökosystem | Atommodell | Industrielle Revolution |
|---|---|---|---|---|
| **Standard** | 83 % / 0 % (6) | 67 % / 33 % (12) | 50 % / 25 % (8) | 54 % / 38 % (13) |
| BM25 + Model2Vec | 83 % / 0 % (6) | 62 % / 38 % (13) | 57 % / 0 % (7) | 54 % / 38 % (13) |
| `hybrid_light` ohne Model2Vec | 83 % / 0 % (6) | 67 % / 33 % (12) | 57 % / 14 % (7) | 54 % / 38 % (13) |
| Zeichen-TF-IDF | 71 % / 14 % (7) | 69 % / 31 % (13) | 57 % / 0 % (7) | 47 % / 47 % (15) |
| BM25 | 83 % / 0 % (6) | 67 % / 33 % (12) | 57 % / 14 % (7) | 54 % / 38 % (13) |
| nur Überschriften-Lexikon | 83 % / 0 % (6) | 67 % / 33 % (12) | 57 % / 0 % (7) | 54 % / 38 % (13) |
| Model2Vec allein | 60 % / 30 % (10) | 64 % / 29 % (14) | 38 % / 13 % (8) | 35 % / 47 % (17) |

In Klammern die Zahl der bewerteten Absätze; die Stichproben je Thema sind klein. Die Modelle der Testapp im Ablauf
des Dienstes wurden nicht vom Richter beurteilt; Grundlage des Vergleichs ist der Goldstandard. Beim LLM wären
Richter und Zuordner dasselbe Modell.

## M7 Größe des XML-Dumps

**Aufbau:** Aus `dewiki-latest-pages-articles-multistream.xml.bz2` (8,25 GB, Stand 07.09.2026) wurden an 16
gleichmäßig verteilten Stellen je 4 MB geladen und alle darin vollständigen bz2-Blöcke entpackt, zusammen 541
Blöcke. Das Verhältnis entpackt zu gepackt lag bei 3,88 (3,43 bis 4,26), hochgerechnet auf die ganze Datei 32,0 GB
(29,8 GiB). Das ist eine Hochrechnung, keine Messung der ganzen Datei. Größen der übrigen Varianten stehen in
`messung/ergebnisse/m7_xml_dump.txt`.

## M8 Artikelwahl

**Aufbau:** Das Gold liegt in `eval/artikelwahl/` und wurde von Claude festgelegt; redaktionell ist es ungeprüft.

- `hauptartikel.yaml`: 59 Anfragen in sechs Arten mit den akzeptierten Titeln, festgelegt vor dem ersten Lauf.
  Eine Weiterleitung, die Wikipedia für einen akzeptierten Titel setzt, zählt mit. Vor dem Lauf wurde ein Titel nach
  dem Archiv korrigiert: *Welle (Physik)* gibt es nicht, *Welle* ist der Physikartikel.
- `korpus_labels.yaml`: 288 Bewertungen auf der Skala 2 = gehört zum Thema, 1 = verwandt, 0 = passt nicht. Bewertet
  wurden die 221 Artikel, die `build_corpus` für die 20 Themen aus M1 wählt, und die 91 Artikel, die der alte Dienst
  im besten Fall (M2) für die zehn Goldthemen abrief; 24 davon wählten beide. Die Artikel lagen gemischt und
  alphabetisch vor, nur mit Titel und Artikelanfang, ohne Angabe des Dienstes. Klexikon-Artikel verraten ihre
  Herkunft.

Jede Anfrage lief durch `CompendiumService.prepare` mit den Archiven des Servers (Wikipedia und Klexikon). Die
gedruckten Absätze stammen vom Standard (`hybrid_light` mit Model2Vec, 12.000 Zeichen). Als Artikel des alten
Dienstes zählt der Artikel hinter der abgerufenen Adresse; wo Wikipedia umleitete, weicht er vom Titel ab, den sein
LLM geraten hatte („Emblem (Literatur)“ wurde zu *Symbol*).

Der Richter `gpt-5.6-luna` bekam je Thema einen Aufruf mit derselben Skala. Die Artikel waren mit festem Startwert
gemischt, er sah nur Titel und die ersten 180 Zeichen. 20 Aufrufe, 21.166 Tokens, alle 288 Artikel bewertet.

| Art der Anfrage | Hauptartikel richtig |
|---|---|
| normale Themen (die 20 aus M1) | 20 von 20 |
| mit Klassen-, Stufen- oder Fachzusatz | 8 von 8 |
| mehrdeutig, Fach als Kontext | 6 von 16 |
| mehrdeutig, ohne Kontext | 3 von 3 |
| Schreibvariante, Abkürzung, Mehrzahl | 6 von 8 |
| ohne gleichnamigen Artikel zum Thema | 2 von 4 |
| **alle** | **45 von 59** |

| Korpus, 20 Themen | Artikel | Gold: gehört, verwandt, passt nicht | Richter: gehört, verwandt, passt nicht |
|---|---|---|---|
| Hauptartikel | 20 | 100 %, 0 %, 0 % | 100 %, 0 %, 0 % |
| dasselbe Thema aus Klexikon | 14 | 86 %, 14 %, 0 % | 86 %, 0 %, 14 % |
| verlinkte Unterartikel | 140 | 50 %, 41 %, 9 % | 54 %, 41 %, 6 % |
| Volltexttreffer je Baustein | 47 | 32 %, 34 %, 34 % | 40 %, 36 %, 23 % |
| alle gewählten | 221 | 53 %, 34 %, 13 % | 57 %, 33 %, 10 % |
| davon mit Absätzen im Korpus | 183 | 58 %, 31 %, 11 % | 61 %, 31 %, 9 % |
| davon ohne Absatz (Themenfilter) | 38 | 29 %, 50 %, 21 % | 39 %, 47 %, 13 % |

Von den 3.035 Absätzen im Korpus stammen 149 (5 %) aus Artikeln, die nach Gold nicht passen, von den 358
gedruckten 26 (7 %). Am meisten druckt der Standard aus *Probit-Modell* (Lineare Funktion, 5 Absätze) und
*Kernwaffe* (Atommodell, 4).

| Zehn Goldthemen | Artikel | Median je Thema | Gold: gehört, verwandt, passt nicht | Richter: gehört, verwandt, passt nicht |
|---|---|---|---|---|
| alter Dienst, bester Fall | 91 | 10 | 51 %, 35 %, 14 % | 71 %, 23 %, 5 % |
| neuer Dienst, Artikel mit Absätzen | 87 | 11 | 62 %, 32 %, 6 % | 66 %, 32 %, 2 % |

Gold und Richter stimmen bei 223 von 288 Artikeln überein (77 %, Cohens Kappa 0,61). Der Richter vergibt öfter
eine 2 als das Gold. Von den sieben Artikeln, die das Gold mit 0 und der Richter mit 2 bewertet, sind sechs
Begriffsklärungsseiten des alten Dienstes. Die falsch aufgelösten Anfragen, die unpassenden Artikel mit Absätzen im
Korpus und die Kreuztabelle stehen in `messung/ergebnisse/m8_artikelwahl.txt`, die Rohdaten in
`m8_artikelwahl.json` und `m8_artikel_richter.json`.
