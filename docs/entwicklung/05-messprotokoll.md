# Messprotokoll (23. bis 26.09.2026)

[Übersicht](README.md) · Skripte und Ergebnisdateien: [messung/](messung/README.md)

## Umgebung

| Was | Stand |
|---|---|
| Server | Hostinger, Image v2.0.0 aus GHCR, zwei Worker; Archive `wikipedia_de_all_nopic_2026-01` und `klexikon_de_all_maxi_2026-08`; Lehrplan-Cache vom 22.09.2026; edu-sharing `repository.staging.openeduhub.net` |
| Entwicklungsrechner | Windows 11, Python 3.13.5; venv des neuen Dienstes, venv der Testapp (torch 2.14, transformers 5.17, model2vec 0.9), venv des alten Dienstes nach seiner Lock-Datei (openai 2.26, aiohttp 3.12.13); dieselben Archive |
| Testsuite | 767 Tests bestanden, 94,11 % Abdeckung mit `matcher=llm` (D34); Stand `02070a3` nach 2.0.0: 753 Tests, 94,04 %; Schwelle der CI 90 % |
| Sprachmodelle | `gpt-4.1-mini` für den alten Dienst, `gpt-5.6-luna` für den Richter und als Zuordner, alle über die b-api |
| Tokens für diese Messungen | alter Dienst 87.710 (`gpt-4.1-mini`); mit `gpt-5.6-luna`: Richter 67.936, LLM als Zuordner 144.596, Richter der Artikelwahl 21.166, `matcher=llm` im Dienst 144.486 laut b-api, davon acht Themen aus ihrem Zwischenspeicher. M9 bis M12 (24.09.2026): Artikelwahl 17.116, Trefferprüfung 6.330 und 14.240, Zusatzquellen 18.188, schärfere Beschreibungen 149.910, Zuordnung nur für unsichere Absätze 71.173, mit 50 und 400 105.727; M12 zweiter Lauf 144.758 und 103.368; M13 Artikelwahl 34.288, `matcher=llm` 146.848; M14 `matcher=llm` 172.440; dazu Wiederholungen aus dem Zwischenspeicher der b-api (dieselben Prompts, dieselben Antworten), die sie trotzdem mit ihren Tokens meldet |

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

## M9 Artikelwahl: schärfere Regeln und LLM für unsichere Fälle (23. und 24.09.2026)

**Aufbau:** Zu `hauptartikel.yaml` aus M8 kamen zwei Goldsätze, beide festgelegt, bevor die Verbesserungen
geschrieben wurden: `hauptartikel_validierung.yaml` mit 23 Anfragen und `hauptartikel_test.yaml` mit 12
zurückgehaltenen Anfragen, die erst liefen, als die Regeln feststanden. `mc_aufloesung.py` löst jede Anfrage durch
`CompendiumService.prepare` auf, ohne Korpus, einmal nur mit den Regeln und einmal mit `article_choice=llm`
(`gpt-5.6-luna`). Der alte Stand ist Commit `c03dafe` in einer `git archive`-Kopie. Eine Weiterleitung, die
Wikipedia für einen akzeptierten Titel setzt, zählt wie in M8 mit.

| Goldsatz | alter Stand | Regeln | Regeln und LLM | LLM gefragt |
|---|---|---|---|---|
| Hauptgold, 59 Anfragen | 45 | 55 | 57 | 7 |
| Validierung, 23 | 14 | 22 | 23 | 5 |
| Test, 12, erster Lauf | 7 | 8 | 9 | 4 |
| Test, 12, nach zwei Korrekturen | 7 | 9 | 11 | 6 |

| Art der Anfrage (alle drei Sätze) | alter Stand | Regeln | Regeln und LLM |
|---|---|---|---|
| normale Themen | 24 von 24 | 24 | 24 |
| mit Klassen-, Stufen- oder Fachzusatz | 8 von 8 | 8 | 8 |
| mehrdeutig, Fach als Kontext | 19 von 38 | 31 | 35 |
| mehrdeutig, ohne Kontext | 3 von 3 | 3 | 3 |
| Schreibvariante, Abkürzung, Mehrzahl | 9 von 12 | 11 | 12 |
| ohne gleichnamigen Artikel zum Thema | 3 von 9 | 9 | 9 |

Die Validierung ist seit ihrem ersten Lauf nach der ersten Regelrunde (21 von 23) nicht mehr unabhängig: Ihre beiden
Fehler flossen in die zweite Runde ein. Der Testsatz fand im ersten Lauf zwei Fehler, die danach behoben wurden:
Wortformen eines Fachworts zählten doppelt („Mathematik: Ableitung“ wurde zu *Ableitung (Informatik)*), und ein
exakter Titel ohne jeden Fachbezug galt als sicher („Erdkunde: Delta“ blieb beim Buchstaben). Unabhängig gemessen
sind also 7 zu 8 zu 9 auf dem Testsatz.

Übrig: „Physik: Leiter“ und „Physik: Strom“ enden bei *Leiter (Physik)* und *Strom (Physik)*, allgemeineren
Physikartikeln zum richtigen Begriff; die Regeln sind sich dort sicher, also fragen sie das LLM nicht. „Informatik:
Netzwerk“ bleibt bei *Netzwerk* statt *Rechnernetz*. „Physik: Strom“ traf der alte Stand mit *Elektrischer Strom*;
es ist die einzige Anfrage, die schlechter wurde. Wo die Regeln sich sicher sind, liegen sie 73 von 76 Mal richtig,
bei den 18 unsicheren 13 Mal, mit dem LLM 18 Mal. Das LLM wurde 18-mal gefragt, rund 950 Tokens je Aufruf, zusammen
17.116; der Messlauf mit eigenem Skript und der Lauf über den Schalter des Dienstes ergaben genau dieselben Titel
und dieselbe Tokenzahl, die b-api erkannte die Prompts als gleich. Rohdaten: `m9_aufloesung_alt.json`,
`m9_aufloesung_regeln.json`, `m9_aufloesung_llm.json`; Zusammenfassung mit allen geänderten und falschen Anfragen:
`m9_artikelwahl.txt`.

## M10 Volltexttreffer je Baustein: Filter (24.09.2026)

**Aufbau:** Die 47 Volltexttreffer der 20 Themen aus M1 mit ihren blind vergebenen Noten aus M8.
`mc_trefferfilter.py` beschreibt jeden Treffer so, wie ein Filter ihn sehen könnte. `mc_treffer_llm.py` lässt
`gpt-5.6-luna` mit dem unveränderten Prompt des M8-Richters benoten, einmal die Treffer allein, einmal mit allen
Korpusartikeln des Themas im selben Aufruf (`--korpus`). `mc_treffer_wirkung.py` baut den Korpus ohne die mit 0
benoteten Treffer und zählt, was der Standard druckt.

| Filter | behalten: gehört, verwandt, passt nicht | verworfen |
|---|---|---|
| heute: Themenstamm in Titel oder Einleitung | 15, 16, 16 | 0, 0, 0 |
| Themenstamm im Titel oder im ersten Satz | 8, 5, 2 | 7, 11, 14 |
| alle Themenwörter in Titel und Einleitung | 14, 16, 13 | 1, 0, 3 |
| Model2Vec-Ähnlichkeit zur Einleitung des Hauptartikels ≥ 0,7 | 14, 12, 10 | 1, 4, 6 |
| LLM, Treffer allein benotet | 15, 16, 10 | 0, 0, 6 |
| LLM, mit dem ganzen Korpus benotet | 15, 16, 5 | 0, 0, 11 |

| 20 Themen, Standard | gedruckt: gehört, verwandt, passt nicht | gefüllte Inhaltsbausteine |
|---|---|---|
| heute | 252, 80, 26 | 122 |
| ohne die mit 0 benoteten Treffer | 260, 86, 10 | 120 |

Die zwei Bausteine, die leer werden, trugen bei „Atommodell“ nur Absätze aus *Kernwaffe*. Das LLM brauchte 16 Aufrufe
mit 14.240 Tokens (Treffer allein: 6.330); über den Schalter des Dienstes verwarf es dieselben 11 Treffer (14.243
Tokens). Nebenbefund: Passte der Hauptartikel selbst auf ein Muster der Sperrliste für Links, galt die ganze Liste
nicht; „Atommodell“ leitet auf *Liste der Atommodelle* um und ließ so *Physik* ein. Seit der Korrektur ändern sich
zwei Korpora: *Liste von Programmiersprachen* weicht *Zeittafel der Programmiersprachen*, *Physik* weicht *Molekül*.
Rohdaten: `m10_trefferfilter.json`, `m10_treffer_llm_allein.json`, `m10_treffer_llm_korpus.json`,
`m10_treffer_wirkung.json`; Zusammenfassung: `m10_volltexttreffer.txt`.

## M11 Wikibooks und Wikiversity als weitere Quellen (24.09.2026)

**Aufbau:** Die 20 Themen aus M1 mit Wikipedia und Klexikon (Profil `standard`) und zusätzlich mit
`wikibooks_de_all_nopic_2026-01` und `wikiversity_de_all_nopic_2026-07` (Profil `extended`), zugeordnet mit dem
Standard. `mc_zusatzquellen.py` misst den heutigen Weg: Aus weiteren Archiven kommt nur ein Artikel mit genau dem
Titel des Hauptartikels. `mc_zusatzsuche.py` fügt je Archiv die ersten drei Volltexttreffer zum Thema hinzu
(Metaseiten und Sperrliste ausgenommen) und misst ohne und mit der Trefferprüfung aus M10.

| 20 Themen | Seiten aus Wikibooks und Wikiversity | davon verworfen | gedruckt | gefüllte Inhaltsbausteine |
|---|---|---|---|---|
| nur Wikipedia und Klexikon | 0 | | | 122 |
| heute: gleicher Titel | 2 | | 2 | 122 |
| Volltextsuche, 3 je Archiv | 88 | | 29 | 123 |
| Volltextsuche mit Trefferprüfung | 88 | 33 | 31 | 125 |

Über den gleichen Titel kamen nur Wikibooks *Optik* (kein Absatz gedruckt) und Wikiversity *Lineare Funktion*
(2 Absätze); bei „Lineare Funktion“ druckte der Standard danach 16 statt 21 Absätze, weil der Zwilling einen
Korpusplatz belegt. Die Volltextsuche findet Brauchbares, etwa *Physikunterricht/ Optik*, den Wikiversity-Kurs
*Kurs:Optik*, *Anorganische Chemie für Schüler/ Säure-Base-…* oder *Wikijunior Wie Dinge funktionieren/ Elektrischer
Strom*, aber von keiner dieser Seiten druckte der Standard einen Absatz. Gedruckt wurde aus Seiten wie
*OpenSource4School/Potenziale digitaler Medien*, *Arbeiten mit .NET*, *SHK-Handwerk in Sachsen* oder *Kommutative
Ringe/Bruchrechnung/Aufgabe*. Bei fünf Themen kommen Wikibooks-Treffer aus dem *Ungarisch-Lesebuch*, 9 der 42, bei
zweien alle drei. Ohne die Prüfung sinkt „Wasserkreislauf“ von 5 auf 3 gefüllte Bausteine. Tokens der Prüfung:
18.188. Zusammenfassung: `m11_zusatzquellen.txt`; Rohdaten:
`m11_zusatzquellen.json`, `m11_zusatzsuche.json`; die Textanfänge der Seiten bleiben außerhalb des Repositorys.

## M12 Zuordnung: schärfere Bausteinbeschreibungen und günstigere LLM-Zuordnung (23. und 24.09.2026)

**Aufbau:** `mc_varianten.py` und `mc_llm_sparvarianten.py` auf festen Korpora der zehn Goldthemen, wie M4 und M5.
Die schärferen Beschreibungen stehen in `messung/sc26_beschreibungen.json` (sc26 mit überarbeiteten Beschreibungen,
„gehört hinein“ und „gehört nicht hinein“; Suchanfragen und Überschriftenmuster unverändert, damit der Korpus
gleich bleibt).

| Bausteinbeschreibungen | Pool | macro-F1 | micro-F1 | richtig unter Top 2 | Tokens |
|---|---|---|---|---|---|
| sc26, `hybrid_light` | alle Absätze | 0,447 | 0,656 | 67,1 % | |
| schärfer, `hybrid_light` | alle Absätze | 0,448 | 0,658 | 63,4 % | |
| sc26, `matcher=llm` | Gold | 0,665 | 0,794 | 74,8 % | 144.486 |
| schärfer, `matcher=llm` | Gold | 0,678 | 0,795 | 81,2 % | 149.910 |

Nicht übernommen: lokal kein Gewinn, mit dem LLM +0,013 macro-F1, innerhalb der Streuung wiederholter Läufe.

| LLM-Zuordnung, Gold-Pool (597 Absätze) | macro-F1 | micro-F1 | falsch | an das LLM | Tokens |
|---|---|---|---|---|---|
| Regeln (`hybrid_light` mit Model2Vec) | 0,433 | 0,645 | 201 von 542 | 0 | 0 |
| 25 Absätze je Aufruf, 700 Zeichen (bis D36) | 0,657 | 0,791 | 127 von 548 | 597 | 144.062 |
| nur Absätze ohne sicheres Signal der Policy | 0,543 | 0,686 | 203 von 578 | 278 | 71.173 |
| 50 Absätze je Aufruf, 400 Zeichen (D36) | 0,720 | 0,820 | 113 von 550 | 597 | 105.727 |

| F1 je Baustein | Belege | Regeln | 25 und 700 | nur unsichere | 50 und 400 |
|---|---|---|---|---|---|
| Fachinhalte | 276 | 0,70 | 0,84 | 0,74 | 0,86 |
| Entwicklung & Ausblick | 83 | 0,73 | 0,83 | 0,74 | 0,84 |
| Gliederung & Systematik | 55 | 0,60 | 0,76 | 0,64 | 0,78 |
| Gesellschaftlicher Kontext | 38 | 0,41 | 0,71 | 0,58 | 0,80 |
| Themendefinition | 22 | 0,68 | 0,81 | 0,65 | 0,91 |
| Praxis | 18 | 0,19 | 0,34 | 0,51 | 0,58 |
| Beruf & Wirtschaft | 11 | 0,27 | 0,80 | 0,50 | 0,80 |
| Bildung | 8 | 0,50 | 0,74 | 0,63 | 0,78 |
| Querschnitt & Bezüge | 3 | 0,00 | 0,17 | 0,22 | 0,19 |
| Regularien & Rahmensetzung | 2 | 0,25 | 0,57 | 0,22 | 0,67 |

Der Lauf mit 25 und 700 kam für neun der zehn Themen aus dem Zwischenspeicher der b-api (4,9 s): dieselben Prompts
wie in M5, dieselben Antworten. Die Policy entscheidet 319 der 597 Absätze mit sicherem Signal und liegt bei 125 davon
falsch (39 %), bei den übrigen 278 bei 131 (47 %); darum hilft das LLM nur für die unsicheren wenig.

**Zweiter Lauf (24.09.2026, `--rotieren`):** Jeder Pool beginnt in der Mitte, das Modell bekommt dieselben Absätze in
anderen Stapeln, und kein Prompt kommt aus dem Zwischenspeicher: eine unabhängige Stichprobe beider Einstellungen.

| LLM-Zuordnung, Gold-Pool | 1. Lauf macro-F1 | 2. Lauf macro-F1 | 2. Lauf micro-F1 | 2. Lauf falsch | 2. Lauf Tokens |
|---|---|---|---|---|---|
| 25 Absätze je Aufruf, 700 Zeichen | 0,657 | 0,727 | 0,826 | 110 von 550 | 144.758 |
| 50 Absätze je Aufruf, 400 Zeichen | 0,720 | 0,694 | 0,820 | 113 von 550 | 103.368 |

Der Vorsprung des ersten Laufs hat sich umgedreht: Der Unterschied liegt in der Streuung des Modells, die bei den
kleinen Bausteinen am größten ist (Praxis 0,34, 0,58, 0,73 und 0,69; Themendefinition 0,81, 0,91, 0,90 und 0,76),
während die großen stabil bleiben (Fachinhalte 0,84 bis 0,86). Beide Einstellungen sind gleich gut; 50 und 400 braucht
27 bis 29 % weniger Tokens und bleibt deshalb (D36). Je Thema brauchte der Gold-Pool im Median 7,5 s mit 25 und
700 und 6,8 s mit 50 und 400. Rohdaten: `m12_beschreibungen_lokal.json`, `m12_beschreibungen_llm.json`,
`m12_sparvarianten.json`, `m12_sparvarianten_rotiert.json`; Zusammenfassung mit Tokens und Sekunden je Weg und F1 je
Baustein in beiden Läufen: `m12_zuordnung.txt`.

## M13 Laufzeit der LLM-Schalter gegen den vorherigen Standard (24.09.2026)

**Aufbau:** 30 Themen, die keine frühere Messung gestellt hatte, damit kein Prompt aus dem Zwischenspeicher der b-api
kommt: 20 Schulthemen, 9 mehrdeutige Wörter mit Fach und eine Genitivwendung (`mc_zeit_artikelwahl.py`). Jede Anfrage
lief im Prozess durch `CompendiumService.generate`, nur Teil 1, mit Model2Vec, auf dem Entwicklungsrechner. Vor dem
gemessenen Durchgang lief jedes Thema einmal mit den Regeln, damit Archivseiten und Modell warm sind. Der vorherige
Standard ist `c03dafe` (v2.0.0 mit D34) in einer `git archive`-Kopie, der aktuelle Stand `f9accb7`; beim aktuellen
wechselten sich `rule-based` und `llm` je Thema ab.

| Teil 1 je Kompendium | Median | 90. Perzentil | Mittel |
|---|---|---|---|
| vorheriger Standard (v2.0.0) | 1,27 s, im zweiten Lauf 1,37 s | 1,83 s | 1,30 s |
| aktuelle Regeln (`article_choice=rule-based`), eigener Lauf | 1,35 s | 1,88 s | 1,36 s |
| `article_choice=llm`, im Wechsel mit den Regeln | 2,68 s | 4,64 s | 2,93 s |

Im Wechsellauf kamen die Regeln auf 0,90 s, weil der LLM-Durchgang desselben Themas die Archivseiten gerade gelesen
hatte; der Unterschied zwischen den Prozessen ist Dateicache, nicht Code. Belastbar sind deshalb die Phasen, die das
Audit je Anfrage misst:

| Phase mit `article_choice=llm` | Median | 90. Perzentil | Maximum |
|---|---|---|---|
| Trefferprüfung (alle 30 Themen) | 1,43 s | 3,19 s | 3,84 s |
| unsichere Artikelwahl (5 Themen) | 1,45 s | | 2,65 s, kürzeste 1,00 s |
| beide zusammen je Thema | 1,72 s | 3,37 s | 3,86 s |

Tokens: 34.288 für 30 Themen, im Median 927 je Thema. Die Trefferprüfung verwarf 20 Treffer in 14 Themen, etwa
*Buchbinder*, *Heraklit* und *Mnemotechnik* bei „Satz des Thales“ oder *Halluzination* bei „Musik: Stimme“; das LLM
änderte eine Auflösung („Physik: Feder“: *Feder (Technik)* statt der Begriffsklärung) und bestätigte vier. Die neuen
Regeln wählten bei 5 der 9 mehrdeutigen Wörter einen anderen Hauptartikel als v2.0.0, dem Titel nach jedes Mal den
besseren; ein Goldsatz dafür fehlt.

**`matcher=llm` an ganzen Kompendien** (`mc_zeit_zuordnung.py`): fünf dieser Themen, `article_choice=rule-based`, im
Wechsel mit `hybrid_light`.

| Teil 1 je Kompendium | Median | davon Zuordnung | Maximum | Tokens |
|---|---|---|---|---|
| `hybrid_light` | 1,20 s | 0,27 s | 1,26 s | 0 |
| `matcher=llm` (D36) | 11,97 s | 10,83 s | 13,36 s | 146.848, 19.000 bis 38.000 je Thema |

Bei 3 der 5 Themen blieben 194 von 1.053 Absätzen bei der Standard-Strategie, alle mit „Token-Budget der Anfrage
erschöpft“: Jeder Stapel zu 50 Absätzen reserviert vorab rund 12.500 bis 13.500 Tokens (Schätzung der Eingabe plus
Antwortgrenze samt Denkreserve) und verbraucht rund 8.000; die Stapel laufen parallel, und so war das Budget von 60.000
nach vier Stapeln verplant, bevor einer abgerechnet hatte. Rohdaten: `m13_zeit_alt.json`,
`m13_zeit_alt_zweiter_lauf.json`, `m13_zeit_neu.json`, `m13_zeit_neu_regeln_zweiter_lauf.json`,
`m13_zeit_zuordnung.json`; Zusammenfassung mit allen Themen: `m13_laufzeit.txt`.

## M14 `matcher=llm` ohne Rückfall am Budget (24.09.2026)

**Frage:** Entscheidet das LLM mit D39 alle Absätze, und was kostet das Warten an Zeit?

**Aufbau:** Fünf Themen, die keine frühere Messung gestellt hatte, damit kein Stapel aus dem Zwischenspeicher der
b-api kommt, ähnlich groß wie die aus M13: *Relativitätstheorie*, *Völkerwanderung*, *Kreuzzüge* (aufgelöst zu
*Kreuzzug*), *Expressionismus* und *Verdauung*, zusammen 1.005 Absätze, drei Themen mit fünf oder sechs Stapeln.
`mc_zeit_zuordnung.py` mit diesen Themen als Argumenten, der Stand mit D39 in einer `git archive`-Kopie, sonst wie
M13: Teil 1, Model2Vec, `article_choice=rule-based`, `LLM_MAX_TOKENS_PER_REQUEST=60000`, im Wechsel mit
`hybrid_light`. Was das alte Verfahren mit denselben Themen getan hätte, rechnet `mc_budget_nachrechnung.py` ohne
b-api nach: Es schneidet die Stapel wie der Dienst, schätzt ihre Reservierung wie `budgeted_chat` und lässt sie der
Reihe nach zu, bis der nächste nicht mehr passt. So verhielten sich die parallelen Aufrufe, weil jeder reservierte,
bevor der erste abrechnete. Für die fünf Themen aus M13 ergibt die Rechnung genau die gemessenen Rückfälle (94, 50,
0, 50 und 0 Absätze), und der erste abgewiesene Stapel von *Evolution* reserviert 12.883 Tokens, die Zahl aus dem
Audit von M13.

| Thema | Absätze | Stapel | Rückfall ohne Warten, nachgerechnet | mit D39 | Teil 1 | davon Zuordnung | Tokens |
|---|---|---|---|---|---|---|---|
| Relativitätstheorie | 284 | 6 | 84 | 0 | 25,36 s | 25,11 s | 45.915 |
| Völkerwanderung | 236 | 5 | 36 | 0 | 24,92 s | 23,07 s | 42.815 |
| Kreuzzüge | 231 | 5 | 31 | 0 | 22,71 s | 22,22 s | 40.633 |
| Expressionismus | 150 | 3 | 0 | 0 | 19,23 s | 16,95 s | 24.267 |
| Verdauung | 104 | 3 | 0 | 0 | 15,40 s | 15,08 s | 18.810 |

| Teil 1 je Kompendium | Median | davon Zuordnung | Maximum | Rückfall | Tokens |
|---|---|---|---|---|---|
| `hybrid_light` (M14) | 1,83 s | 0,51 s | 2,70 s | – | 0 |
| `matcher=llm` vor D39 (M13, andere Themen) | 11,97 s | 10,83 s | 13,36 s | 194 von 1.053 | 146.848 |
| `matcher=llm` mit D39 (M14) | 22,71 s | 22,22 s | 25,36 s | 0 von 1.005 | 172.440 |

Kein Absatz fiel zurück; ohne Warten wären es 151 gewesen (15 %). Das LLM brauchte 22 Aufrufe und 172 Tokens je Absatz
(M13: 171), ein Kompendium im Mittel 34.500 Tokens, das größte 45.915. Die Zeit ist aus zwei Gründen länger. Die b-api
antwortete langsamer als bei M13: Themen mit drei Stapeln, deren Reservierungen zusammen in 60.000 passen und die
deshalb nie warten, brauchten 15,1 und 16,9 s für die Zuordnung, in M13 10,8 und 11,7 s. Und Themen ab fünf Stapeln
brauchen eine zweite Runde: Vier Stapel zu je rund 13.000 Tokens passen in 60.000, jeder weitere startet erst, wenn
laufende abgerechnet haben. Sie brauchten 22,2 bis 25,1 s für die Zuordnung. Ein Budget, das alle Stapel zugleich hält
(sechs volle Stapel reservieren rund 80.000), spart die zweite Runde, ohne den Verbrauch zu ändern; gemessen ist das
nicht. Auch `hybrid_light` lief langsamer als in M13 (0,51 statt 0,27 s für die Zuordnung). Wo der Verbrauch selbst an
die Grenze kommt, fällt weiter zurück, was nicht mehr hineinpasst: gerechnet ab rund 320 Absätzen, wenn der letzte
Stapel seine Reservierung nicht mehr neben dem Verbrauch der übrigen unterbringt. Rohdaten: `m14_zeit_zuordnung.json`,
`m14_budget_nachrechnung.json`; Zusammenfassung: `m14_zuordnung_budget.txt`.

## M15 F1 je Baustein aller lokalen Strategien (24.09.2026)

**Aufbau:** `mc_varianten.py` ohne LLM auf den festen Korpora der zehn Goldthemen, mit `lexicon_only`, `bm25`,
`char_tfidf` und `hybrid_light` (mit Model2Vec), in beiden Kandidatenpools. Keine Tokens. `hybrid_light` im Goldpool
trifft die Regeln aus M12 je Baustein genau; die Werte stehen also neben den beiden LLM-Läufen aus M12 auf denselben
597 Absätzen.

| F1 je Baustein (Gold-Absätze) | `lexicon_only` | `bm25` | `char_tfidf` | `hybrid_light` | `llm`, Lauf 1 | `llm`, Lauf 2 |
|---|---|---|---|---|---|---|
| Fachinhalte (276) | 0,70 | 0,69 | 0,69 | 0,70 | 0,86 | 0,86 |
| Entwicklung & Ausblick (83) | 0,74 | 0,72 | 0,70 | 0,73 | 0,84 | 0,84 |
| Gliederung & Systematik (55) | 0,58 | 0,60 | 0,57 | 0,60 | 0,78 | 0,76 |
| Gesellschaftlicher Kontext (38) | 0,43 | 0,37 | 0,40 | 0,41 | 0,80 | 0,78 |
| Themendefinition (22) | 0,68 | 0,68 | 0,68 | 0,68 | 0,91 | 0,76 |
| Praxis (18) | 0,21 | 0,20 | 0,15 | 0,19 | 0,58 | 0,69 |
| Beruf & Wirtschaft (11) | 0,17 | 0,15 | 0,20 | 0,27 | 0,80 | 0,80 |
| Bildung (8) | 0,00 | 0,20 | 0,43 | 0,50 | 0,78 | 0,78 |
| Querschnitt & Bezüge (3) | 0,00 | 0,00 | 0,00 | 0,00 | 0,19 | 0,00 |
| Regularien & Rahmensetzung (2) | 0,00 | 0,00 | 0,17 | 0,25 | 0,67 | 0,67 |
| **macro-F1** | **0,35** | **0,36** | **0,40** | **0,43** | **0,72** | **0,69** |

Die lokalen Strategien unterscheiden sich nur in drei kleinen Bausteinen: Bildung, Regularien und Beruf & Wirtschaft,
zusammen 21 Gold-Absätze. Dort liegt der ganze Abstand von 0,35 auf 0,43; in den großen Bausteinen liegen sie
höchstens 0,04 auseinander, bei Gesellschaftlichem Kontext und Praxis liegt das Lexikon allein leicht vorn. Im vollen
Pool: 0,350, 0,370, 0,422 und 0,448. Rohdaten: `m15_bausteine_lokal.json`; Zusammenfassung: `m15_bausteine_lokal.txt`.
Die Grafiken der Entscheidungsvorlage erzeugt `mc_grafiken.py` aus diesen und den übrigen Rohdaten.

## M16 laya-multilingual für Artikelwahl und Trefferprüfung (24.09.2026)

**Aufbau:** laya ist ein kleines Entscheidungsmodell ohne Textgenerierung (GitHub NandhaKishorM/laya, Paket `laya`
0.3.20 von PyPI, Apache 2.0): Es beantwortet typisierte Fragen (Auswahl, Ja/Nein, Skala) in einem Durchlauf. Getestet
wurde `convaiinnovations/laya-multilingual` (mmBERT-base, 322 Mio. Parameter, 644 MB) ohne Nachtraining auf der CPU des
Entwicklungsrechners, in der venv der Testapp (torch 2.14 CPU, transformers 5.17). `mc_laya_export.py` legt die
Entscheidungen so an, wie der Dienst sie dem LLM stellt: für die 18 unsicheren Anfragen der drei Goldsätze dieselben
Kandidaten mit Textanfang (291 zusammen, 1 bis 39 je Anfrage), für die 47 Volltexttreffer aus M10 Titel, Textanfang und
den Hauptartikel des Themas. `mc_laya.py` stellt die Artikelwahl als Auswahlfrage und die Trefferprüfung als
Ja/Nein-Frage und als Dreiwahl (gehört, verwandt, passt nicht). Keine Tokens.

| Artikelwahl, 18 unsichere Anfragen | richtig | ohne die 3 mit nur einem Kandidaten |
|---|---|---|
| Regeln | 13 | 10 von 15 |
| laya, deutsche Anweisung | 8 | 5 von 15 |
| laya, englische Anweisung | 8 | 5 von 15 |
| LLM (`article_choice=llm`, M9) | 18 | 15 von 15 |

laya wählte etwa *Strom (Ucker)* für „Strom“, *The Fall* für „Deutsch: Fall“, *Benin* für „Aufbau der Atome“ und
*Delta Motor Group* für „Erdkunde: Delta“. Auf höchstens 20 Kandidaten begrenzt, wie das Modellblatt rät: 7 richtig.

| Trefferprüfung, 47 Treffer | verworfen: gehört (15), verwandt (16), passt nicht (16) | AUC gehört gegen passt nicht |
|---|---|---|
| laya ja/nein unter 0,5, deutsche Anweisung | 5, 6, 5 | 0,51 |
| laya ja/nein unter 0,5, englische Anweisung | 8, 8, 10 | 0,47 |
| laya Dreiwahl „passt nicht“ | 12, 11, 12 | – |
| LLM mit dem ganzen Korpus (M10) | 0, 0, 11 | – |

Die Wahrscheinlichkeit für „ja“ trennt nicht: Unpassende Treffer bekommen im Median 0,72, passende 0,70. Keine
Schwelle verwirft mehr als einen unpassenden Treffer, ohne einen passenden zu verlieren.

**Auf der CPU** läuft es: Laden 22 bis 61 s aus dem Plattencache (beim ersten Mal 121 s samt Download),
Arbeitsspeicher 1,7 GB, beim Laden kurz 2,3 GB. Eine Entscheidung dauert 0,2 s bei kurzem Text und rund 0,5 s bei den
Entscheidungen hier, die 47 Treffer im Stapel 21 s. Die Trefferprüfung eines Themas mit rund 12 Artikeln bräuchte so
rund 6 s; das LLM braucht im Median 1,4 s für alle Artikel in einem Aufruf.

**Ergebnis:** Ohne Nachtraining taugt laya-multilingual für keine der beiden Entscheidungen. Es liegt bei der
Artikelwahl unter den Regeln und bei der Trefferprüfung auf Zufallsniveau. An die Stelle des LLM gesetzt, ergäbe es mit
den Regeln 81 von 94 Hauptartikeln (54, 20 und 7 in den drei Goldsätzen): fünf weniger als die Regeln allein (86) und
zehn weniger als mit dem LLM (91). Das Modellblatt nennt für die eigene Aufgabensammlung 0,352 ohne und 0,766 mit
Feinabstimmung (laya-typed-decisions). **laya müsste also erst auf unsere Entscheidungen trainiert werden**, etwa auf
die Wahlen und Noten, die heute das LLM trifft, und danach am selben Gold bestehen; das wäre ein Destillationsversuch
(06-daten-und-training.md). Auch dann bräuchte es 1,7 GB je Worker und mehr Zeit als das LLM. **Nicht in die API
eingebaut** (D42); die Werte stehen hier und in der Entscheidungsvorlage nur zum Vergleich. Rohdaten: `m16_laya.json`,
`m16_laya_englisch.json`; die Textanfänge der Kandidaten bleiben außerhalb des Repositorys.

## M17 Die Artikelwahl des alten Dienstes auf dem Gold (24.09.2026)

**Aufbau:** Der alte Dienst (v0.2.0) wählte keinen Hauptartikel. Sein Linker ließ ein LLM bis zu zehn Begriffe „mit
exakten Wikipedia-Titeln“ nennen (Modus `generate`, Bildungsmodus an) und schlug jeden Titel live nach: direkt samt
Weiterleitung, dann mit Schreibvarianten, dann über drei LLM-Synonyme. Die Einleitungen der Treffer waren die Quellen
seines Textes. `mc_alte_artikelwahl.py` schickt denselben Prompt wortgleich an das Modell des alten Dienstes
(`gpt-4.1-mini`, Temperatur 0,7 wie dort) und an das des neuen (`gpt-5.6-luna`) und schlägt die Titel im
Wikipedia-Archiv des neuen Dienstes nach, direkt und mit den alten Schreibvarianten; den Synonymschritt spart es aus.
Gezählt wird je Anfrage der drei Goldsätze aus M9, ob der Artikel hinter dem ersten Begriff ein akzeptierter
Hauptartikel ist und ob einer unter allen Artikeln ist. Im selben Lauf rechnen die Regeln des neuen Dienstes nach: 86
wie in M9, und 87 Mal steht ein akzeptierter Artikel irgendwo in ihrem Korpus. Je Modell ein Lauf; mit Temperatur 0,7
streut `gpt-4.1-mini` von Lauf zu Lauf.

| 94 Anfragen | alter Weg, `gpt-4.1-mini`: erster Begriff / unter allen | alter Weg, `gpt-5.6-luna`: erster / unter allen | Regeln | Regeln und LLM (M9) |
|---|---|---|---|---|
| normale Themen (24) | 18 / 20 | 5 / 5 | 24 | 24 |
| mit Klassen-, Stufen- oder Fachzusatz (8) | 7 / 8 | 6 / 7 | 8 | 8 |
| mehrdeutig, Fach als Kontext (38) | 12 / 30 | 29 / 30 | 31 | 35 |
| mehrdeutig, ohne Kontext (3) | 2 / 2 | 1 / 1 | 3 | 3 |
| Schreibvariante, Abkürzung, Mehrzahl (12) | 7 / 9 | 8 / 9 | 11 | 12 |
| ohne gleichnamigen Artikel (9) | 9 / 9 | 6 / 6 | 9 | 9 |
| **alle** | **55 / 78** | **55 / 58** | **86** | **91** |

| Je Anfrage | alter Weg, `gpt-4.1-mini` | alter Weg, `gpt-5.6-luna` | Regeln und LLM |
|---|---|---|---|
| LLM-Aufrufe | immer einer, im alten Dienst dazu einer je nicht gefundenem Titel | immer einer | nur bei unsicheren Auflösungen einer (18 von 94) |
| Tokens, Median | 1.311 (123.357 für alle 94) | 1.484 (139.889) | rund 950 je Aufruf |
| Zeit, Median (90. Perzentil) | 6,3 s (7,3 s) | 8,3 s (9,4 s) | 1,0 bis 2,7 s je Aufruf (M13) |
| Titel ohne Artikel im Archiv | 102 von 940 (11 %) | 62 von 935 (7 %) | – |
| Begriffsklärungen unter den Treffern | 29 von 838 (3,5 %) | 32 von 873 (3,7 %) | keine (M8) |

- **Der Prompt verlangt „additional entities“**, also Begriffe neben dem Text. `gpt-5.6-luna` nennt deshalb bei
  normalen Themen das Thema selbst fast nie (5 von 24; für „Klimawandel“ etwa *Globale Erwärmung*, *Treibhauseffekt*,
  *Treibhausgas*), `gpt-4.1-mini` öfter (20 von 24). M8 fand im Korpus des alten Dienstes den Hauptartikel bei 9 von
  10 Goldthemen.
- **Bei mehrdeutigen Wörtern mit Fach** liegt der alte Weg unter allen Artikeln gleichauf mit den Regeln (30 gegen
  31 von 38), sagt aber nicht, welcher der Hauptartikel ist. An erster Stelle steht bei `gpt-4.1-mini` in 17 der 38
  Anfragen das Fach selbst („Physik: Leiter“ ergibt zuerst *Physik*), der richtige Artikel nur 12 Mal.
- **Wo die Regeln scheitern**, findet er 6 der 8 Hauptartikel, darunter zwei, bei denen sich die Regeln sicher sind
  und das LLM deshalb nicht gefragt wird: *Elektrischer Strom* für „Physik: Strom“ und *Rechnernetz* für „Informatik:
  Netzwerk“, mit beiden Modellen; `gpt-4.1-mini` findet auch den dritten, *Elektrischer Leiter*. Dafür fehlt der
  richtige Artikel bei 14 (`gpt-4.1-mini`) und 34 (`gpt-5.6-luna`) Anfragen, die die Regeln treffen.

**Ergebnis:** Der alte Weg ersetzt die Artikelwahl nicht. Einen Hauptartikel benennt er nicht; an erster Stelle steht
der richtige 55 von 94 Mal, irgendwo unter bis zu zehn Artikeln 58 bis 78 Mal. Die Regeln treffen 86, mit LLM 91. Er
kostet bei jeder Anfrage einen Aufruf, 6 bis 8 s und rund 1.300 bis 1.500 Tokens und bringt Begriffsklärungsseiten mit;
für den Korpus fand M8 bei ihm 14 % unpassende Artikel gegen 6 %. Seine Stärke, das Wissen des Modells um den
richtigen Titel, nutzt der neue Dienst schon: Mit `article_choice=llm` darf das LLM bei einer unsicheren Auflösung
einen Titel nennen, der nur zählt, wenn das Archiv ihn als Artikel hat (D35). Offen ist allein, ob das LLM auch die
drei sicheren Fehler der Regeln fangen soll; dafür müsste es auch sichere Auflösungen mehrdeutiger Wörter prüfen, und
das wäre eigens zu messen. Rohdaten: `m17_alte_artikelwahl_gpt41mini.json`, `m17_alte_artikelwahl.json`
(`gpt-5.6-luna`); nur Titel, kein Artikeltext. `gpt-4.1-mini` diente hier nur der Nachstellung des alten Dienstes;
es ist veraltet und teurer und wird sonst nicht verwendet (M19, D44).

## M18 GND-Nummern aus dem Archiv (24.09.2026)

**Aufbau:** Die deutsche Wikipedia schließt die meisten Artikel mit dem Normdaten-Block, und der Kiwix-Dump behält
ihn: die Art des Datensatzes (Person, Sachbegriff, Geografikum, Körperschaft, Werk), die GND-Nummer, oft VIAF und
LCCN. Wikidata-Nummern führt der Dump nicht ([Umbau](../umbau.md)). `mc_entitaeten_gnd.py` nimmt die Anfänge (bis
2.000 Zeichen) der Hauptartikel der 20 Themen aus M1, erkennt die Begriffe über das Wörterbuch von
`POST /api/v2/entities`, verknüpft sie mit dessen eigener Funktion und liest aus jedem verknüpften Wikipedia-Artikel
den Normdaten-Block. Das spaCy-Modell liegt nur im Image; ein Name, den es findet, verknüpft über dieselbe Funktion.
Kein Download, kein Netz; nur die Stichprobe fragt lobid-gnd (hbz), und zwar mit nichts als den Nummern.

| 20 Texte | Anzahl |
|---|---|
| Begriffe des Wörterbuchs | 931 |
| verknüpft (Begriffsklärungen fallen weg) | 724, davon 679 mit einem Wikipedia-Artikel |
| mit Normdaten-Block | 506 (75 % der Wikipedia-Artikel) |
| mit GND-Nummer | 503 (74 %): 450 Sachbegriffe, 25 Geografika, 23 Personen, 3 Werke, 2 Körperschaften |
| Personen nach `kind` des Dienstes mit GND | 21 von 24 |

Ohne GND bleiben 176 Artikel, fast alle Sachartikel (169).

**Stichprobe gegen lobid-gnd:** 30 Nummern mit fester Saat, jede vorkommende Art dabei (12 Sachbegriffe, 7 Geografika,
7 Personen, 3 Werke, 1 Körperschaft). Alle 30 gibt es, und jede benennt den Gegenstand ihres Artikels (*Lebewesen*
ergibt „Organismus“, *Martin Lowry* „Lowry, Thomas Martin“). Vier der 30 Artikel sind aber schon falsch verknüpft,
keiner davon ein Sachbegriff: „Abraham Lincolns“ und „des Wassers“ im Genitiv führen zum biblischen *Abraham* und zum
Ort *Wassers*, „Potenzen und Wurzeln“ zur Fernsehserie *Wurzeln* (GND „Roots“), „Zeiträume“ zu einem Verein. Der
Fehler liegt beim Wörterbuch (U3b), nicht bei der Nummer.

**Ergebnis:** Für verknüpfte Entitäten ist die GND-Nummer im Archiv schon vorhanden, ohne Download und so genau wie die
Verknüpfung selbst: Drei von vier verknüpften Wikipedia-Artikeln tragen sie. Nicht gelöst sind Entitäten ohne
Wikipedia-Artikel und falsche Verknüpfungen. Wikidata-Nummern gibt der Dump nicht her; dafür bräuchte es einen Index
aus den Wikipedia-Tabellen `page_props` (105 MB) und `page` (320 MB) oder den Entity-Facts-Abzug der DNB (1,3 GB, nur
Personen, Familien, Körperschaften, Konferenzen und Geografika). Beim alten Weg aus M17 trugen 67 bis 74 % der
gefundenen Artikel eine GND.

**Nachtrag, eingebaut (D43):** Der Endpunkt liefert GND, VIAF und die aus dem Titel gebildete DBpedia-URI, die
Wikidata-Nummer kommt aus einem lokalen Index. `compendium wikidata build` baute ihn aus `page_props` (105 MB) und
`page` (320 MB) vom 07.09.2026 in fünf bis acht Minuten auf dem Entwicklungsrechner (302 und 504 s): 3.177.984 Titel,
darunter rund 32.100 Weiterleitungen mit eigenem Wikidata-Objekt, 107 MB. Dieselben 20 Texte, jetzt mit der Funktion
des Endpunkts gezählt:

| 679 verknüpfte Wikipedia-Artikel | Anzahl |
|---|---|
| mit GND-Nummer | 503 (74 %), wie oben |
| mit Wikidata-Nummer | 674 (99,3 %), darunter alle 503 mit GND |
| ohne Wikidata-Nummer | 5, etwa *Bruchterme*, *Schichten*: Weiterleitungen auf einen Abschnitt, die Wikidata mit keinem eigenen Objekt verknüpft |
| Verknüpfen je Text, Median | 141 ms ohne, 147 ms mit Index (beide warm, im Mittel 47 Begriffe je Text) |

Gegenprobe ohne Netz: Für die 30 Stichprobennummern nennt lobid-gnd eine Wikidata-Verknüpfung; 29 stimmen mit dem
Index überein. Die eine Abweichung ist keine: Der Artikel *England* ist das Land (Q21), der GND-Datensatz „England“
ist in Wikidata mit dem historischen Königreich verknüpft (Q179876). Rohdaten: `m18_entitaeten_gnd.json` (Kennungen
je Entität), `m18_gnd_stichprobe.json`; nur Begriffe, Titel und Nummern.

**Korrektur nach dem Review (24.09.2026):** Die erste Fassung zählte 670 und hielt die neun Fehlstellen für Artikel,
die seit dem ZIM umbenannt wurden. Das stimmte nicht. Alle neun sind schon im ZIM vom Januar Weiterleitungen auf einen
Abschnitt (*Nenner* → *Bruchrechnung#Nenner*), die das ZIM als eigene Seite führt, und der Index ließ Weiterleitungen
aus. Vier davon sind in Wikidata aber eigene Objekte, mit dem Abzeichen „Sitelink auf Weiterleitung“: *Nenner*
Q3044574, *Gedicht* Q5185279, *Ordinate* Q500576, *Abszisse* Q515874. Seitdem nimmt der Index sie auf. Die damals
vorgeschlagene Tabelle `redirect` hätte geschadet: Sie führt zum Zielartikel und damit zur Nummer eines anderen
Begriffs, *Lyrik* statt *Gedicht*. Auch die erste Zeitmessung war schief: Sie wärmte den Index nicht vor, die 46 ms
Aufschlag waren kalte Seiten; warm sind es 6 ms je Text.

## M19 gpt-6-luna gegen gpt-5.6-luna (24.09.2026)

**Aufbau:** `gpt-6-luna` ist an der b-api der Nachfolger von `gpt-5.6-luna`, nach Angabe zum halben Preis je Token.
Es ist wie sein Vorgänger ein Reasoning-Modell: `max_tokens` beantwortet es mit HTTP 400 und verlangt
`max_completion_tokens`. Der Client erkannte es daran bisher nicht, D44 behebt das. Verglichen wurden die drei
LLM-Entscheidungen des Dienstes an denselben Goldsätzen, mit den Skripten von M9, M10 und M12 und
`B_API_MODEL=gpt-6-luna`; die Werte von `gpt-5.6-luna` stammen aus diesen Messungen. Zeiten verschiedener Läufe lassen
sich nicht vergleichen, weil die b-api über den Tag schwankt. Deshalb bekamen beide Modelle dieselben acht frischen
Prompts abwechselnd in denselben Minuten (`mc_latenz_modelle.py`, zwei abgelegte Läufe).

| | `gpt-5.6-luna` | `gpt-6-luna` |
|---|---|---|
| Artikelwahl, 94 Anfragen (18 unsichere entscheidet das LLM) | 91 richtig | 90 richtig |
| Tokens der Artikelwahl, 18 Aufrufe | 17.116 | 17.642 |
| Trefferprüfung, 47 Treffer: unpassende verworfen | 11 von 16 | 10 von 16 |
| dabei passende verworfen | 0 von 31 | 0 von 31 |
| Tokens der Trefferprüfung | rund 14.200 | 15.924 |
| LLM-Zuordner, Goldpool: macro-F1 / micro-F1 | 0,720 und 0,694 / 0,820 (zwei Läufe) | 0,703 / 0,814 |
| falsch zugeordnet | 113 von 550 | 98 von 519 |
| Tokens des Zuordners | 105.727 und 103.368 | 108.266 |
| Latenz bei gleichen frischen Prompts, Median | 1,60 s und 2,47 s | 2,75 s und 3,06 s |
| Ausgabetokens dabei, Summe über acht Aufrufe | 800 und 854 | 1.500 und 1.526 |

Die eine falsche Artikelwahl mehr ist „Lichtlehre“: `gpt-6-luna` nannte *Hesychasmus*, `gpt-5.6-luna` *Optik*. Bei
„Musik: Satz“ wählte es *Tonsatz* statt *Satz (Musikstück)*, beide nach dem Gold richtig; die übrigen 92 Anfragen enden
beim selben Artikel. Der Zuordner brauchte auf dem Goldpool im Median 12,6 s je Thema, `gpt-5.6-luna`
am Vormittag 6,8 s; der Unterschied ist größer als der im gleichzeitigen Vergleich und wohl zum Teil Tagesschwankung.

**Ergebnis:** Gleichauf in der Güte: je eine Entscheidung weniger bei Artikelwahl und Trefferprüfung, beim Zuordner
zwischen den beiden Läufen von `gpt-5.6-luna`. Die Tokens der Aufgaben des Dienstes liegen gleich bis 12 % höher; zum
halben Preis je Token sind das rund 45 % geringere Kosten, solange Ein- und Ausgabe gleich viel kosten. `gpt-6-luna`
gibt aber fast doppelt so viele Ausgabetokens aus (im Latenzvergleich 1.500 und 1.526 statt 800 und 854 bei gleicher
Eingabe); kostet die Ausgabe mehr als die Eingabe, fällt die Ersparnis kleiner aus. Der Preis ist die Zeit: je Aufruf
0,6 und 1,1 s mehr, ein Viertel bis drei Viertel. Übernommen als Vorgabe (D44). `gpt-4.1-mini`, das Modell des alten
Dienstes, wird nicht mehr verwendet: veraltet und teurer; es diente nur der Nachstellung in M17. Gemessen wurde an der
Staging-b-api; die Produktiv-b-api ließ sich mit dem Schlüssel der Entwicklung nicht fragen (HTTP 401). Ein erster
Latenzlauf (1,79 gegen 2,43 s) wurde überschrieben und ist nicht abgelegt; seitdem verweigert das Skript eine
vorhandene Ausgabedatei. Rohdaten: `m19_aufloesung_gpt6.json`, `m19_treffer_gpt6.json`, `m19_zuordnung_gpt6.json`,
`m19_latenz.json`, `m19_latenz_2.json`.

## M20 Genitiv beim Verknüpfen der Entitäten (24.09.2026)

**Aufbau:** In M18 verknüpfte das Wörterbuch zwei Genitive falsch: „des Wassers“ mit dem Ort *Wassers*, „Abraham
Lincolns“ mit dem biblischen *Abraham*. Eine Regel (D46) versucht den Titel ohne Genitivendung, „-es“ vor „-s“: nach
*des*, *eines* und ähnlichen Artikeln zuerst (ein Wort dazwischen erlaubt), sonst erst, wenn die wörtliche Form kein
Titel ist. Ohne Artikel bleiben ein einzelnes Wort am Satzanfang vor einem kleingeschriebenen Wort und Adverbien auf
„-s“ („Bereits“) wörtlich. Dieselben 20 Texte wie in M18, verglichen Verknüpfung für Verknüpfung
(`mc_entitaeten_gnd.py` mit dem Index von M18).

| | vorher (M18) | mit Regel |
|---|---|---|
| Begriffe (höchstens 50 je Text) | 931 | 939 |
| verknüpft, davon Wikipedia | 724, 679 | 729, 682 |
| mit GND / mit Wikidata-Nummer | 503 / 674 | 505 / 677 |
| neue Verknüpfungen | – | 30, keine falsch |
| ersetzte Verknüpfungen | – | 4: *Abraham* → *Abraham Lincoln*, Ort *Wassers* → *Wasser*, *Klimas* → *Klima*, *Systems* → *System* |
| von der Obergrenze verdrängt | – | 12 spätere Begriffe |

Die neuen sind Genitive, die ihren Artikel jetzt finden: *Englands*, *Jahrhunderts*, *Europas*, *Lichts*, *Kampfes*,
*Volkes*, *Ciceros* (→ *Marcus Tullius Cicero*) und weitere. *Stroms* und *Elements* führen in der Wikipedia auf
Begriffsklärungen und landen deshalb beim Klexikon, beide passend. Die Obergrenze gilt vor dem Verknüpfen in
Lesereihenfolge, wie `max_entities` am Endpunkt: Findet das Wörterbuch vorn mehr, fallen hinten Begriffe weg. Ein
erster Entwurf verknüpfte noch *Daraus* → *Darau*, *Bereits* → *Johann Bereit* und *Reiches* → *Reiche*; daher
kamen die Endungsfolge und die Ausnahmen ohne Artikel dazu, jede mit einem Test. Der Abgleich mit lobid bleibt bei
29 von 30.

**Ergebnis:** Übernommen (D46). Nicht gelöst sind Homonyme ohne Genitiv (*Wurzeln* → Fernsehserie, *Zeiträume* →
Verein); dafür bräuchte die Verknüpfung den Zusammenhang des Textes. Rohdaten: `m20_entitaeten_genitiv.json`.

## M21 Artikelwahl für echte Materialien (24.09.2026)

**Aufbau:** Der Knoten-Eingang (D45) nimmt den Titel eines Materials als Thema. Echte Materialien nennen im Titel aber
oft ihr Format, ihre Quelle oder ein Datum. Das Gold `eval/materialwahl/materialien.yaml` hält 40 Materialien der
WLO-Produktion, je Fach 4 mit Beschreibung, gezogen mit fester Saat (`mc_material_stichprobe.py`) und beschriftet von
Claude, bevor ein Verfahren lief: 31 mit klarem Thema, 7 unscharf (Portal, Methode, Meinung), 2 ohne Thema. Die
Stichprobe zeigt die Lage der Metadaten: Fächer passen oft nicht (ein Zeitraffer vom Sonnenuntergang unter Chemie,
englische Videos zur organischen Chemie unter Biologie), Titel nennen Daten („21./22. April 1946“) oder Formate
(„… - Experiment“), Beschreibungen sind Werbelinks oder der Text des Arbeitsblatts. Verglichen im Ablauf des Dienstes
(`mc_material_artikelwahl.py`, die Materialien anonym aus dem Repository gelesen):

| Weg | richtig, 38 mit Thema | davon klar, 31 | ohne Artikel | Zeit je Material, Median | Tokens |
|---|---|---|---|---|---|
| S0 Titel als Thema (heute) | 7 | 5 | 15 | 11 ms | 0 |
| S1 Titel ohne Format- und Quellenteile | 9 | 7 | 6 | 11 ms | 0 |
| S2 das häufigste Schlagwort | 6 | 5 | 11 | 9 ms | 0 |
| S3 Entitäten aus Titel und Beschreibung, gewichtet | 16 | 13 | 0 | 0,22 s | 0 |
| S4 das LLM nennt den Artikel | 34 | 30 | 0 | 2,8 s | rund 470 |
| Regeln, wo sicher, sonst Entitäten | 16 | 13 | 0 | – | 0 |
| Regeln, wo sicher, sonst LLM | 31 | 28 | 0 | – | weniger |

Das LLM liest aus der Beschreibung, was der Titel verschweigt: „21./22. April 1946“ wird zur *Zwangsvereinigung von
SPD und KPD zur SED*, ein englisches Video zu SN1 und SN2 zur *Nukleophilen Substitution*, der Text eines
Arbeitsblatts zu *Dreisatz* oder *Proportionalität*. Die Entitäten schlagen den Titel deutlich, verlieren aber an
häufige Allerweltswörter: *Brötchen* aus einem Arbeitsblatt, *April*, *Lernen*, *Zeit*. Die Regeln, die bei Themen
verlässlich sagen, ob sie sicher sind (M9), sind es bei Materialien nicht: Von fünf Materialien, bei denen S1 sich
sicher gibt, liegen drei falsch, und bei allen dreien läge das LLM richtig, etwa *Scratch (Computer)* statt der
Programmiersprache. Grenzfall: „20. - 24.
Sept. 1947“ nennt das LLM *Parteitag der SED*; vertretbar, nach dem Gold falsch. Bei den zwei Materialien ohne Thema
nennt jeder Weg trotzdem einen Artikel. 18.757 Tokens für 40 Materialien, mit `gpt-6-luna`.

**Ergebnis und Optionen (zu entscheiden):** Der Titel trägt bei echten Materialien nicht. Für Knoten ohne mitgeschicktes
`topic` stehen vier Wege offen: (A) das LLM nennt das Thema aus Titel, Beschreibung und Schlagwörtern, die Regeln
schlagen es nach, 34 von 38 für rund 470 Tokens und 2,8 s; (B) die Entitäten aus Titel und Beschreibung, lokal, 16
von 38 in 0,2 s; (C) A, wo ein LLM bereitsteht (Stufen `balanced` und `best-quality`), sonst B; (D) wie heute der
Titel, 7 von 38, und der Aufrufer schickt das Thema mit. Die Messung spricht für C. Rohdaten: `m21_materialwahl.json`.

## M22 Lehrplanbezüge von Teil 2 (24.09.2026)

**Aufbau:** Teil 2 sucht im lokalen MEM-Cache nach den Stichwörtern eines Themas und schränkt die Lehrpläne auf die
Fächer ein, wenn welche bekannt sind (`04-lehrplaene-und-sammlung.md`). Ob die ausgegebenen Elemente zum Thema
gehören, war nicht geprüft; der alte Dienst ordnete keine Lehrpläne zu, einen Vergleich gibt es nicht. Die 20
normalen Themen des Artikelgolds liefen im Ablauf des Dienstes je zweimal, ohne Fach und mit dem Fach, das eine
Lehrkraft nennen würde (Optik mit Physik, Klimawandel mit Geografie), über den lokalen Cache vom 17.09.2026
(`mc_lehrplan_treffer.py`, LLM aus). Der Lauf mit Fach gibt eine Teilmenge des anderen aus. Beurteilt wurde eine
Stichprobe mit fester Saat: je Thema bis zu fünf Elemente des Laufs mit Fach und bis zu fünf, die nur der Lauf ohne
Fach ausgibt, zusammen 175, gemischt und ohne Angabe der Schicht. Noten: 2 gehört zum Thema, 1 berührt es (Beispiel
in einer Aufzählung, Werkzeug, Zeile ohne eigenen Inhalt unter einem passenden Bereich), 0 passt nicht. Claude hat
beschriftet, ein Claude-Subagent ohne die ersten Noten ein zweites Mal nach denselben Regeln: gleiche Note bei 93 %
der Elemente (Cohens Kappa 0,89), einig über „passend“ bei 98 %, über „passt nicht“ bei 95 %; strittig war nur die 1,
etwa Napoleon unter „Aufklärung, Französische Revolution und Napoleon“. Die Anteile sind je Thema aus beiden
Schichten hochgerechnet und über die Themen gemittelt (`mc_lehrplan_auswertung.py`), in Klammern mit den zweiten
Noten:

| | ohne Fach | mit Fach |
|---|---|---|
| Elemente in den 20 Themen | 4.623 | 3.154 |
| davon nur über die Überschrift gefunden | 1.503 | 1.211 |
| passend (Note 2) | 60 % (62 %) | 62 % (64 %) |
| mindestens berührt (Note 1 oder 2) | 86 % (81 %) | 87 % (81 %) |
| passende Elemente, hochgerechnet | 2.434 (2.651) | 1.831 (2.048) |

Die Themen gehen weit auseinander, von 100 % passend (Plattentektonik, Industrielle Revolution, Photosynthese mit
Fach) bis 0 % (Programmiersprache mit Fach: Die Elemente nutzen eine Programmiersprache als Werkzeug, „implementieren
verkettete Listen in einer objektorientierten Programmiersprache“, und bekommen eine 1). Je Thema und Schicht stehen
höchstens fünf Elemente in der Stichprobe; die Werte je Thema sind grob, die Mittel über 20 Themen tragen.

Die Fehltreffer (Note 0) haben zwei Ursachen. Im Lauf ohne Fach steckt das Stichwort meist in einem anderen Wort oder
hat eine andere Bedeutung: „Erdplatten“ trifft die „Herdplatten“, der Bindestrich-Teil „affin“ des Synonyms
„affin-linearen Funktion“ trifft „Paraffin“ und „Affinität“, „Zelle“ die „Solarzelle“ und die Zellen einer
Tabellenkalkulation, „Base“ die „Basenpaarung“ der DNA, „Lineare Funktion“ die Überschrift „NICHT-LINEARE
FUNKTIONEN“. Das Fach nimmt 17 der 21 Wortfehler der Stichprobe heraus, nach den zweiten Noten 20 von 24. Im Lauf
mit Fach nennt meist nur die Überschrift das Thema, und das Element handelt von etwas anderem, etwa „Ionennachweise“
unter „Vom Daltonschen Atommodell zum Kern-Hülle-Modell“: 10 der 13 Fehltreffer dieser Schicht sind
Überschriften-Treffer, nach den zweiten Noten 15 von 19. Überschriften-Treffer sind ein Drittel aller Elemente und
passen seltener (46 % passend, 25 % gar nicht) als solche mit dem Stichwort im eigenen Text (55 % und 15 %), oft
aber doch: „Ausbreitung von Licht“ unter „Grundlagen der Optik“.

Das Fach macht Teil 2 um ein Drittel kürzer und hebt die Treffsicherheit kaum. Es verwirft ein Viertel der passenden
Elemente, vor allem aus drei Gruppen: berufliche Lehrpläne ohne Schulfach (Optik für Podologen und Geomatiker, die
Sinfonie für Instrumentenmacher), der Sachunterricht der Grundschule (Demokratie, Wasserkreislauf) und Nachbarfächer,
die das Thema ebenso lehren (Atommodell in Physik statt Chemie, Photosynthese in Chemie, Ökosystem in Geographie,
Plattentektonik in Geologie, Römisches Reich in Latein). Der Wasserkreislauf behält mit Geografie 2 von 19 Elementen.

**Ergebnis und Optionen (zu entscheiden):** Teil 2 findet zu jedem der 20 Themen passende Lehrplanelemente, aber
nicht nur solche. Von dem, was er ausgibt, gehören rund 60 % zum Thema, 17 bis 26 % berühren es, 13 bis 19 % passen
nicht. Vier Wege, die sich ergänzen:
(A) Stichwortregeln schärfen: Bindestrich-Teile nur aus dem Thema selbst, nicht aus Synonymen und Unterartikeln;
eine Fundstelle direkt nach „nicht-“ zählt nicht; am Ende eines längeren Wortes zählt ein Treffer nur, wenn davor
mindestens zwei Buchstaben stehen („H|erdplatten“ ist keine Zusammensetzung, „Ei|zelle“ bleibt); Silbentrennzeichen
fallen vor dem Vergleich weg. Lokal und ohne Kosten. Über alle Elemente nachgerechnet fallen 44 ohne Fach und 34 mit
Fach, keines davon passend, 38 bei Lineare Funktion (quadratische, Potenz-, Exponential- und Winkelfunktionen,
affine Abbildungen der Geometrie); in der Stichprobe 8 der 21 Wortfehler. Andere Bedeutungen kurzer Stichwörter
(Solarzelle, Stromversorgung) bleiben.
(B) Überschriften-Treffer bündeln: Elemente, die nur über ihre Überschrift gefunden werden, erscheinen nicht
einzeln; der Bereich steht einmal da, mit der Zahl seiner Elemente. Teil 2 wird um ein Drittel kürzer, und die
meisten Fehltreffer im Lauf mit Fach verschwinden; die passenden Elemente darunter sind dann nur über den Bereich zu
finden. (C) Fachfilter ergänzen: Lehrpläne ohne Schulfach und der Sachunterricht passieren den Filter, oder sie
folgen dem Fach in einem eigenen Abschnitt; das holt einen Teil der verlorenen passenden Elemente zurück und
verlängert Teil 2. (D) Inhaltlich prüfen: Ein Ähnlichkeitsmaß (Model2Vec liegt im Image) oder das LLM ordnet oder
kappt die Elemente; das LLM läse mit Fach im Mittel 158 Elemente je Thema, bei breiten Themen über 500. Beides wäre
vorher an den 175 Noten zu messen. Die Messung spricht für A und, nach einem Blick auf die Darstellung, für B; C und D
hängen davon ab, ob Lehrkräfte berufliche Lehrpläne und Nachbarfächer sehen sollen. Rohdaten:
`m22_lehrplan_treffer.json`, Noten `eval/lehrplan/treffer_noten.yaml` und `treffer_noten_zweit.yaml`.

## M23 Kompendium aus den Metadaten eines Materials (24.09.2026)

**Aufbau:** M21 hat gemessen, wie der Dienst den Hauptartikel eines echten Materials findet; M23 geht bis zum
Kompendium und fragt, ob es aus den Metadaten eines Materials so gut wird wie aus einem Begriff. Für die 40
Materialien des Golds `eval/materialwahl/materialien.yaml` (WLO-Produktion, anonym aus dem Repository gelesen)
entstanden im Ablauf des Dienstes je sechs Kompendien mit Teil 1 und 2 (`mc_material_kompendium.py`):

| Weg | Eingabe |
|---|---|
| B | der Begriff, den eine Lehrkraft eintippen würde (`begriff` im Gold, vor dem Lauf festgelegt), ohne Knoten |
| K0 | der Knoten allein, wie heute: Sein Titel ist das Thema (D45) |
| K0b | der Knoten allein mit `preset: balanced`: Das LLM entscheidet einen unsicheren Artikel (D35) |
| KL | der Knoten und dazu das Thema, das ein LLM aus Titel, Fächern, Schlagwörtern und Beschreibung nennt (M21 S4) |
| KEl | Entitäten aus Titel und Beschreibung, lokal erkannt (Wörterbuch von `/entities`, Rangfolge wie M21 S3); ihre bis zu zehn Artikel sind der Korpus |
| KEa | Entitäten wie im alten Dienst: dessen Linker-Prompt wortgleich (`alter_linker.py`) auf Titel, Beschreibung und Schlagwörter; ihre bis zu zehn Artikel sind der Korpus |

Die Entitäten-Wege gibt es nur in der Messung: Der Dienst baut seinen Korpus aus einem Artikel; für sie ersetzt das
Skript diesen Schritt durch die Artikel der Entitäten (die erste als Hauptartikel, ohne Begriffsklärungen), alles
danach läuft im Dienst. Teil 1 schreiben in allen Wegen die Regeln. Gezählt sind die gedruckten Absätze je
Quellartikel wie in M10. Jeden der 603 Artikel, aus denen für eines der 38 Materialien mit Thema Absätze gedruckt
wurden, hat Claude benotet (2 Thema des Materials oder ein zentraler Teil, 1 verwandt, 0 unpassend), ohne den Weg zu
kennen; ein Claude-Subagent benotete sie ein zweites Mal nach denselben Regeln: gleiche Note bei 91 % (Cohens Kappa
0,86), einig über „passend“ bei 97 %. Werte der 31 Materialien mit klarem Thema. „Passend“ und „unpassend“ sind
Anteile der gedruckten Absätze, gemittelt über die Kompendien, die entstanden; „brauchbar“ heißt, dass mindestens die
Hälfte der Absätze passt (`mc_material_kompendium_auswertung.py`). In Klammern die Werte mit den zweiten Noten:

| Weg | Kompendium | Hauptartikel im Gold | passend | unpassend | brauchbar | Absätze, Median | LLM je Material |
|---|---|---|---|---|---|---|---|
| B Begriff | 31 | 29 | 59 % (59 %) | 22 % (23 %) | 18 (18) | 16 | – |
| K0 Knoten wie heute | 18 | 5 | 23 % (22 %) | 52 % (51 %) | 5 (5) | 14,5 | – |
| K0b Knoten, `balanced` | 18 | 11 | 48 % (47 %) | 19 % (17 %) | 10 (10) | 14 | 600 Tokens, rund 4,6 s |
| KL Knoten, Thema vom LLM | 31 | 30 | 60 % (59 %) | 19 % (20 %) | 17 (17) | 17 | 440 Tokens, 2,8 s |
| KEl Entitäten, lokal | 31 | 14 | 22 % (23 %) | 62 % (61 %) | 5 (6) | 23 | – |
| KEa Entitäten wie im alten Dienst | 31 | 29 | 42 % (43 %) | 17 % (16 %) | 11 (11) | 23 | 1.680 Tokens, 9,9 s |

Bei den Entitäten-Wegen zählt als Hauptartikel die erste Entität. Die Frage von KL ist wortgleich mit der von M21 und
kam aus dem Zwischenspeicher der b-api; die 2,8 s sind die aus M21. K0b rechnet zu K0 den Unterschied der
Erzeugungszeiten im selben Lauf.

**Geht es?** Mit dem Knoten allein, wie der Dienst ihn heute nimmt, selten: Für 13 der 31 Materialien findet der
Titel keinen Artikel (Antwort 404), für 13 weitere einen falschen; brauchbar sind 5 Kompendien, mit `balanced` 10.
Für die zwei Materialien ohne Thema baut jeder Knoten-Weg trotzdem ein Kompendium (*Studienabschlussarbeit*,
*Digitale Kompetenz*, *Kultusministerkonferenz*): Der Dienst erkennt nicht, dass ein Material kein Thema hat.

**Besser oder schlechter als der Begriff?** Nennt ein LLM das Thema aus den Metadaten (KL), wird das Kompendium so gut
wie aus dem Begriff: Meist ist es derselbe Hauptartikel und damit derselbe Text (24 von 31 Materialien gleich, 4
besser, 3 schlechter bei mehr als zehn Punkten Unterschied im passenden Anteil). Die Fächer des Knotens helfen, wo
der Begriff mehrdeutig ist: „Scratch“ endet ohne Fach beim Bahnradsport, mit Informatik und Medienbildung bei der
Programmiersprache. Schlechter wird es, wo das LLM einen breiteren Artikel nennt als die Lehrkraft (*Getriebe* statt
*Zahnrad*). Auch der Begriff druckt Unpassendes (22 %), etwa *Fahrradverleih* und *Hollandrad* zum Zahnrad.
Der Linker des alten Dienstes (KEa) hat den richtigen Artikel fast immer unter seinen Entitäten (31 von 31), mischt
aber verwandte Artikel dazu: mehr Absätze (23 statt 16) und Bausteine (10 statt 8), am wenigsten Unpassendes (17 %),
aber auch weniger Passendes (42 %). Das hilft bei Materialien mit mehreren Aspekten (*Horst Köhler* mit IWF und
Osteuropabank 93 % statt 18 % passend, die Wirtschaftskrise Frankreichs 64 % statt 21 %) und schadet bei Materialien
mit einem Thema (*Planck-Konstante* 20 % statt 83 %, *Petersberger Klimadialog* 9 % statt 90 %): 9 besser, 16 bis 18
schlechter. Die lokal erkannten Entitäten (KEl) taugen als Korpus nicht: Beschreibungen tragen Rauschen (der
Kanalname „Ecole Science“ wird zu *École* und *Science*, Ausrüstungslisten zu *Sony* und *Softbox*), und in
englischen Texten werden einzelne Großbuchstaben zu den Artikeln *A*, *H*, *J*; 62 % der Absätze passen nicht. Bei den
7 unscharfen Materialien (Portale, Methoden, Meinungen) sind alle Wege schwach (brauchbar 1 bis 4 von 7), bei so
wenigen ohne klare Rangfolge. Zusammen 113.476 Tokens für 40 Materialien, mit `gpt-6-luna`.

**Precision, Recall und F1 (aus denselben Läufen und Noten):** Auf Artikelebene lassen sich die Wege vergleichen
wie bei TREC: Passend sind je Material die Artikel mit Note 2, die einer der sechs Wege gedruckt hat (im Median 2,
höchstens 7). Ein Artikel, den kein Weg druckte, bleibt unbekannt; verwandte Artikel (Note 1) zählen als nicht
passend. Precision ist der Anteil der passenden unter den gedruckten Artikeln eines Kompendiums, Recall der Anteil der
passenden Artikel, die es gedruckt hat, F1 ihr harmonisches Mittel, je Material gerechnet und über die Materialien
gemittelt; ein fehlendes Kompendium zählt Recall und F1 0. Für den Hauptartikel gilt das Gold: Precision ist der
Anteil der richtigen unter den gebauten Kompendien, Recall der unter allen 31 Materialien. Werte der 31 Materialien
mit klarem Thema, in Klammern mit den zweiten Noten:

| Weg | Hauptartikel P / R / F1 | Artikel P | Artikel R | Artikel F1 | Artikel-F1 gegen B je Material: besser, gleich, schlechter |
|---|---|---|---|---|---|
| B Begriff | 0,94 / 0,94 / 0,94 | 0,44 (0,41) | 0,57 (0,58) | 0,45 (0,43) | – |
| K0 Knoten wie heute | 0,28 / 0,16 / 0,20 | 0,17 (0,15) | 0,12 (0,11) | 0,10 (0,09) | 0, 7, 24 |
| K0b Knoten, `balanced` | 0,61 / 0,35 / 0,45 | 0,35 (0,32) | 0,27 (0,27) | 0,22 (0,20) | 3, 9, 19 |
| KL Knoten, Thema vom LLM | 0,97 / 0,97 / 0,97 | 0,47 (0,45) | 0,67 (0,66) | 0,50 (0,47) | 5, 26, 0 |
| KEl Entitäten, lokal | 0,45 / 0,45 / 0,45 | 0,17 (0,18) | 0,34 (0,35) | 0,22 (0,22) | 2, 13, 16 |
| KEa Entitäten wie im alten Dienst | 0,94 / 0,94 / 0,94 | 0,39 (0,40) | 0,82 (0,83) | 0,50 (0,50) | 13, 7, 11 |

Zum Vergleich Begriffe ohne Material: Im Gold der Artikelwahl (M9, 94 Anfragen, jede bekommt eine Antwort, also
Precision = Recall = F1) treffen die Regeln 0,91, mit LLM 0,97. B ist eine günstige Vergleichsgröße, weil derselbe
Beschrifter Begriff und Gold festlegte.

Den Hauptartikel trifft das Material mit LLM so sicher wie ein Begriff. Wählen KL und B denselben (24 von 31
Materialien), druckt KL genau dieselben Absätze: Beschreibung und Schlagwörter wirken heute nur über die Wahl des
Hauptartikels. Von den sieben übrigen ist KL bei fünf um mehr als 0,1 besser (zweimal *Scratch (Programmiersprache)*
statt *Scratch (Bahnradsport)*, *Galvanische Zelle*, *Division (Mathematik)*, *Getriebe*), bei zwei gleich.
Artikel-F1 und passender Anteil der Absätze messen Verschiedenes, denn F1 zählt Artikel, nicht Absätze: Zum Zahnrad
druckt B 22 Absätze, 18 davon aus *Zahnrad* (Artikel-F1 0,25, passend 82 %), KL mit *Getriebe* 26 Absätze aus acht
Artikeln rund ums Getriebe, 9 davon passend (Artikel-F1 0,50, passend 35 %).

Auf Artikelebene liegt auch der Begriff nur bei F1 0,45: Die Unschärfe sitzt in den Nebenartikeln (allen gedruckten
Artikeln außer dem Hauptartikel), nicht in der Eingabe. Der Hauptartikel trägt bei KL 31-mal Note 2, bei B 29-mal.
Von den rund drei Nebenartikeln je Kompendium tragen bei B 16 % Note 2 und 36 % Note 0, bei KL 18 % und 34 %; sie
liefern 46 und 53 % der gedruckten Absätze. Die Entitäten des alten Linkers (KEa) erreichen dieselbe Artikel-F1 wie
KL auf anderem Weg: Sie finden die meisten passenden Artikel (Recall 0,82), drucken aber 4,3 Nebenartikel je
Kompendium, aus denen drei Viertel der Absätze kommen. KL und KEa zusammen, als ein Weg gezählt (eine Abschätzung,
kein gebautes Kompendium, 8,2 Artikel je Material), kämen auf Recall 0,96, aber Precision 0,30 und F1 0,44: Die
Entitäten einfach dazuzunehmen, hebt F1 nicht. Bei den 7 unscharfen Materialien liegt KL unter dem Begriff
(Hauptartikel-F1 0,57 gegen 1,00, Artikel-F1 0,30 gegen 0,42); bei sieben Materialien und einem Begriff vom
Beschrifter des Golds ist das keine belastbare Aussage.

**Ergebnis und Optionen (zu entscheiden):** Die Metadaten eines Materials tragen ein Kompendium, wenn ein Schritt
das Thema aus ihnen bestimmt; der Titel allein trägt es nicht. Für Knoten ohne mitgeschicktes `topic`: (A) Das LLM
nennt das Thema (KL, Option A aus M21): so gut wie der Begriff, 17 statt 18 brauchbar, F1 des Hauptartikels 0,97
statt 0,94, der Artikel 0,50 statt 0,45, bei keinem Material um mehr als 0,1 schlechter; rund 440 Tokens und 3 s je
Material. (B) Die Entitäten des alten Linkers werden der Korpus (KEa): breiter (Recall 0,82), aber seltener brauchbar
(11); stark bei Ereignissen, Personen und Meinungsbeiträgen, 1.680 Tokens und 10 s. A mit den Entitäten als
zusätzlichen Quellen hebt F1 nach der Abschätzung nicht (0,44); lohnen könnte es nur mit einem Filter gegen
Plattform- und Formatentitäten wie *YouTube*, das ist nicht gemessen. (C) Ohne LLM bleibt der Titel (5 brauchbar, F1
des Hauptartikels 0,20); keiner der lokalen Wege aus M21 und M23 trifft mehr als 14 von 31 Hauptartikeln. (D)
Unabhängig davon: Findet keiner der Schritte ein Thema, sollte der Dienst kein Kompendium bauen statt eines falschen.
Die Messung spricht für A, wo ein LLM bereitsteht, und für D.

**Weitere Verfahren?** Für den Hauptartikel nicht, wo ein LLM bereitsteht: KL erreicht den Begriff. Ohne LLM müsste
ein neues Verfahren gemessen werden, falls Knoten ohne `topic` auch in der Stufe `llm-free` ein Kompendium bekommen
sollen; sonst genügt D. Messen sollte man als Nächstes die Nebenartikel, denn dort geht die Treffsicherheit verloren,
beim Begriff wie beim Material. Ein Material bringt mit Beschreibung und Schlagwörtern Kontext mit, den der Dienst
beim Auswählen der Nebenartikel heute nicht nutzt. Rohdaten: `m23_material_kompendium.json`, Noten
`eval/materialwahl/kompendium_noten.yaml` und `kompendium_noten_zweit.yaml`.

## M24 Artikel eines Materials ohne LLM: statische Embeddings und Verlinkung (25.09.2026)

**Aufbau:** Ohne LLM findet der Knoten-Eingang den Artikel eines Materials bisher schlecht: Hauptartikel-F1 0,20 mit
dem Titel, höchstens 0,45 mit den lokalen Entitäten (M21, M23). M24 prüft, ob ein statisches Embedding das besser
kann und ob Ähnlichkeit oder Verlinkung ohne LLM die Artikel der alten Entitäten und die Nebenartikel filtern. Das
Modell ist das des Dienstes, `m2v-gte-256-edu` mit 256 Dimensionen. Ein Index über alle Artikel passte auf dem
Entwicklungsrechner weder auf die Platte (4,6 GB frei) noch in den Speicher (2,4 GB frei). Deshalb läuft Stufe 1
blockweise über alle 5,35 Mio. Einträge der Wikipedia-ZIM, bettet ihre Titel ein (eine Weiterleitung steht für ihr
Ziel) und behält je Anfrage die nächsten; für diese Anfragen ist das dasselbe Ergebnis wie mit einem vollständigen
Index (`mc_material_embedding.py`). Stufe 2 bettet Titel und Anfang (600 Zeichen) der 200 nächsten Artikel ein und
rankt sie neu, ohne Begriffsklärungen. Die Material-Anfrage enthält, was das LLM in M21 und M23 las: Titel, Fächer,
Schlagwörter und Beschreibung bis 1.500 Zeichen.

| Weg | Anfrage | Kandidaten |
|---|---|---|
| D1 | Material | alle Titel des Archivs |
| D1k | Material ohne Beschreibung | alle Titel des Archivs |
| D2, D2k | wie D1 und D1k | die 200 nächsten, neu gerankt mit Titel und Anfang |
| E | Material | die zehn lokalen Entitäten aus M23 (KEl), gerankt mit Titel und Anfang |
| BD1, BD2 | der Begriff aus M23, zur Gegenprobe | wie D1 und D2 |

Werte der 31 Materialien mit klarem Thema; jeder Weg antwortet, Precision, Recall und F1 sind also gleich
(`mc_material_embedding_auswertung.py`):

| Weg | Hauptartikel-F1 | akzeptiert unter den ersten 3, 10, 20 | passende Artikel aus M23 unter den ersten 10 |
|---|---|---|---|
| D1 Material, Titel | 0,00 | 0, 1, 2 | 3 % |
| D1k ohne Beschreibung, Titel | 0,03 | 4, 7, 8 | 16 % |
| D2 Material, Titel und Anfang | 0,03 | 1, 2, 3 | 3 % |
| D2k ohne Beschreibung, Titel und Anfang | 0,00 | 2, 4, 5 | 10 % |
| E lokale Entitäten, nach Ähnlichkeit | 0,45 | 19, 21, 21 | 38 % |
| BD1 Begriff, Titel | 0,87 | 28, 28, 28 | 50 % |
| BD2 Begriff, Titel und Anfang | 0,06 | 6, 10, 12 | 17 % |

Zum Vergleich (M21, M23): Titel als Thema 0,20, lokale Entitäten nach Häufigkeit 0,42 und 0,45, Thema vom LLM 0,97,
Begriff mit den Regeln 0,94. Die zweiten Noten ändern die letzte Spalte um höchstens drei Punkte.

**Warum die Suche scheitert:** Ein statisches Embedding mittelt die Vektoren der Wortteile. Bei einem Material
bestimmen Format- und Allerweltswörter den Mittelwert: „Zahnrad und Riemen - Experiment“ landet bei
*Experimentalphysik*, ebenso der Versuch zum planckschen Wirkungsquantum. Lange Beschreibungen ziehen Titel mit
seltenen Wortteilen an (*ProSiebenSat.1 Media* zur Batterie, ein Protein zum Blitzeis mit Windeln). Beim Begriff
trifft der Titel meist genau, mit Gleichständen: *Mond Mond Mond* hat denselben Vektor wie *Mond*. Mit dem
Artikelanfang gewinnen kurze Komposita (*Zahnradbremse* statt *Zahnrad*). Als Rangfolge der lokalen Entitäten (E)
trifft die Ähnlichkeit so oft wie die Häufigkeit (14 von 31), unter den ersten drei steht der akzeptierte Artikel bei
19. Die Entitäten enthalten ihn bei 21 von 31; mehr als 0,68 erreicht auf diesen Kandidaten auch ein besseres lokales
Ranking nicht. Die zwei Materialien ohne Thema fallen über die Ähnlichkeit nicht auf: Ihr erster Treffer liegt bei
0,67 bis 0,80, der Median der klaren bei 0,69 bis 0,76.

**Ähnlichkeit als Filter:** Gemessen sind 599 der 603 in M23 benoteten Artikel; die vier übrigen sind
Klexikon-Artikel, deren Titel in Wikipedia eine Begriffsklärung ist. Die Ähnlichkeit zum Material liegt im Mittel
bei 0,49 (Note 0), 0,53 (Note 1) und 0,57 (Note 2); die AUC für passend gegen unpassend ist 0,63, mit den zweiten
Noten 0,66 (0,5 wäre Zufall). Eine Schwelle, die 90 % der passenden behält, entfernt 22 % der unpassenden. Als
Filter taugt die Ähnlichkeit nicht.

**Verlinkung als Filter:** Anker ist der Hauptartikel des LLM-Themas (KL). Verlinkt heißt, der Anker verweist auf den
Artikel oder der Artikel auf den Anker, Weiterleitungen aufgelöst. In Klammern die Werte mit den zweiten Noten:

| Artikel | Anzahl | verlinkt: Note 2, Note 0 | nicht verlinkt: Note 2, Note 0 | nur verlinkte behalten |
|---|---|---|---|---|
| Zusatzartikel der alten Entitäten (KEa gedruckt, KL nicht) | 166 | 75: 32 %, 5 % | 91: 14 %, 38 % | behält 65 % (56 %) der passenden, entfernt 90 % (85 %) der unpassenden |
| Nebenartikel des LLM-Themas (KL, ohne Hauptartikel) | 126 | 111: 19 %, 31 % | 15: 0 %, 73 % | behält alle passenden, entfernt 24 % (25 %) der unpassenden |

Abgeschätzt wie die Vereinigung in M23 (Artikelebene, aus den gedruckten Artikeln, kein gebautes Kompendium), 31
klare Materialien:

| Artikel | Precision | Recall | F1 |
|---|---|---|---|
| Thema vom LLM (KL) | 0,47 (0,45) | 0,67 (0,66) | 0,50 (0,47) |
| KL und alle Entitäten des alten Dienstes | 0,30 (0,30) | 0,96 (0,95) | 0,44 (0,44) |
| KL und die mit seinem Hauptartikel verlinkten | 0,39 (0,37) | 0,89 (0,87) | 0,51 (0,48) |

Die Verlinkung hält fast den ganzen Recall der alten Entitäten und kostet weniger Precision als die Vereinigung ohne
Filter; F1 bleibt gleich. Bei den Nebenartikeln sind die meisten unpassenden verlinkte Unterartikel (31 % der 111
verlinkten tragen Note 0), die 15 unverlinkten sind zu drei Vierteln unpassend. Unverlinkte wegzulassen entfernt ein
Viertel der unpassenden Nebenartikel und hier keinen passenden.

**Speicher und Geschwindigkeit:** Stufe 1 las die 5,35 Mio. Einträge (3,51 Mio. Artikel, 1,84 Mio. Weiterleitungen)
in 36 s, bettete sie in 110 s ein und verglich sie in 14 s; ein Titelindex wäre auf diesem Rechner in rund
zweieinhalb Minuten gebaut. Bei 256 Dimensionen hätte er 5,5 GB (float32), 2,7 GB (float16) oder 1,4 GB (int8), nur
die Artikel 3,6, 1,8 oder 0,9 GB, dazu das Modell (322 MB, rund 1 GB im Speicher je Worker). Eine Suche ohne
Näherungsindex braucht 4,5 ms je 100.000 Vektoren, 0,24 s über alle Einträge. Titel und Anfang zu lesen kostet 33 ms
je Artikel (Stufe 2: 16.934 Artikel in gut 9 Minuten), für alle Artikel rund 32 Stunden auf einem Kern. Bei den
gemessenen Trefferquoten lohnt keiner dieser Indizes. Ein Lauf dauerte 14 Minuten.

**Ergebnis und Optionen (zu entscheiden):** Ohne LLM gibt es mit den gemessenen Mitteln keinen Weg, der den Artikel
eines Materials verlässlich findet: Titel 0,20, lokale Entitäten 0,45, statische Embeddings höchstens 0,03. Ein
stärkeres lokales Modell könnte höchstens die Kandidaten der lokalen Entitäten besser ordnen und bliebe unter 0,68.
Für Knoten ohne `topic` in der Stufe `llm-free` bleibt der Titel wie heute (er trifft 5 von 31, nimmt bei 13 einen
falschen Artikel und findet bei 13 keinen), oder der Dienst verlangt dort das Thema vom Aufrufer. Die Kombination
aus LLM-Thema und den verlinkten Entitäten des alten Dienstes bringt Breite (Recall 0,89 statt 0,67) bei gleichem F1,
für den Linker-Aufruf (1.680 Tokens, 10 s); ob sie sich lohnt, hängt davon ab, ob mehrteilige Materialien breiter
abgedeckt werden sollen, und wäre im Ablauf des Dienstes mit neuen Noten zu messen. Bei den Nebenartikeln ist das
Weglassen unverlinkter eine lokale Regel ohne Kosten; für die verlinkten Unterartikel braucht es ein stärkeres Signal
als Ähnlichkeit oder Verlinkung. Rohdaten: `m24_material_embedding.json`.

## M25 Einbau nach M21 bis M24: Nebenartikel, Knoten-Eingang, QA-Paare (25.09.2026)

M21 bis M24 hatten Optionen gemessen; Jan entschied am 25.09.2026, die empfohlenen einzubauen (D47, D48) und danach
im Ablauf des Dienstes nachzumessen. Die Regeln, die auf den Materialien von M21 ausgewählt wurden, prüft eine zweite
Stichprobe, die vor jedem Lauf beschriftet wurde.

### Nebenartikel: Verlinkung und LLM-Prüfung (D48)

**Aufbau:** Für die 20 normalen Themen des Begriffs-Golds baut der Dienst seinen Korpus wie für ein Kompendium; jeder
Nebenartikel bekommt seine blinde Note aus `eval/artikelwahl/korpus_labels.yaml` (M8) und die Angabe, ob er und der
Hauptartikel einander verlinken (beide Richtungen, Weiterleitungen aufgelöst, `LinkedTo`). Das LLM (gpt-6-luna)
benotet mit der Trefferprüfung des Dienstes (`rate_articles`) den ganzen Korpus in einem Aufruf je Thema. Gezählt
sind die gedruckten Absätze nach Note ihres Artikels, Standardzuordnung `hybrid_light` mit Model2Vec, 12.000 Zeichen
(`mc_korpus_verlinkung.py`, gemessen am Korpus vor dem Einbau).

| 44 Volltexttreffer | Note 2 | Note 1 | Note 0 |
|---|---|---|---|
| mit dem Hauptartikel verlinkt (28) | 13 | 11 | 4 |
| nicht verlinkt (16) | 2 | 4 | 10 |

Die 104 verlinkten Unterartikel sind zu 5 % unpassend (5 mit Note 0, 59 mit Note 2); anders als bei den Materialien
in M24 (31 %), deren Hauptartikel breiter oder schiefer sind.

| Korpus | gedruckt: Note 2 | Note 1 | Note 0 | gefüllte Inhaltsbausteine | LLM-Aufrufe (20 Themen) | Tokens je Thema |
|---|---|---|---|---|---|---|
| heute ohne LLM | 252 | 80 | 25 | 122 | 0 | 0 |
| ohne unverlinkte Volltexttreffer | 263 | 77 | 12 | 118 | 0 | 0 |
| LLM prüft die Volltexttreffer (`balanced` bis M25) | 257 | 81 | 17 | 120 | 15 | 697 |
| LLM prüft Volltexttreffer und verlinkte Unterartikel | 259 | 80 | 11 | 119 | 20 | 842 |
| beides: ohne unverlinkte, dann LLM auf Treffer und Unterartikel | 264 | 77 | 5 | 117 | 20 | 752 |

Die unverlinkten Treffer wegzulassen halbiert ohne LLM die unpassenden Absätze; ihre Plätze nehmen passende ein (263
statt 252). Die Regel verliert zwei passende Treffer (*Klimapolitik*, *Schnittweite*) und vier Bausteine über 20
Themen. Bei *Lineare Funktion* druckten *Differenzierbarkeit*, *Markow-Operator* und *Probit-Modell* fünf unpassende
Absätze; das LLM ließ sie stehen, der Filter nimmt sie heraus. Die erweiterte LLM-Prüfung verwirft die unpassenden
Unterartikel (*System* und *Ökosystemischer Ansatz nach Bronfenbrenner* bei *Ökosystem*, die Verfilmung *Die
Französische Revolution*); einen passenden oder verwandten Artikel bewertete das LLM nie mit 0. Zusammen bleiben 5
statt 25 unpassende Absätze, bei 20 statt 15 Aufrufen und rund 55 Tokens mehr je Thema.

**Nebenbefund:** gpt-6-luna erkennt als Trefferprüfer nur 7 der 14 unpassenden Volltexttreffer (6 mit Note 1, einer
mit 2); in M10 waren es mit gpt-5.6-luna 11 von 16. Die Verlinkung fängt, was das Modell übersieht.

**Kosten der Verlinkung:** Die Links des Hauptartikels werden einmal aufgelöst (60 bis 300 ms kalt, 10 bis 50 ms warm
je Artikel); die meisten Paare entscheidet schon der wörtliche Linktitel. Je Nebenartikel im Median 0 ms, höchstens
213 ms, je Thema höchstens 0,5 s über alle Nebenartikel.

**Eingebaut (D48):** `build_corpus` lässt Volltexttreffer ohne Link zum oder vom Hauptartikel weg, in allen Stufen,
ohne die Plätze nachzufüllen, wie gemessen. Die Trefferprüfung von `article_choice=llm` verwirft Volltexttreffer und
verlinkte Unterartikel mit Note 0; Hauptartikel, Zwilling, der Artikel des Materials und die Materialien einer
Sammlung bleiben. Rohdaten: `m25_korpus_verlinkung.json`.

### Knoten-Eingang im Ablauf des Dienstes (D47)

**Aufbau:** `mc_material_knoten.py` ruft für jedes Material die Artikelwahl des Dienstes auf (`choose_main_article`,
wie Kompendium und `/knowledge`), jedes Material neu und anonym aus seinem Repository gelesen:

| Weg | Eingabe | Stufe |
|---|---|---|
| K0 | Material, Titel als Thema (bis D47) | ohne LLM |
| R | Material allein, Regeln über Titel und Beschreibung | ohne LLM (`llm-free`) |
| L | Material allein, das LLM nennt den Artikel | `article_choice llm` (`balanced`) |
| B | der Begriff einer Lehrkraft allein | ohne LLM |
| BR | Begriff und Material, der Begriff führt | ohne LLM |
| BL | Begriff und Material in einer Frage an das LLM | `article_choice llm` |

Gold 1 sind die 40 Materialien von M21 (`materialien.yaml`), auf denen die Regel ausgewählt wurde. Gold 2 sind 40
weitere (`materialien_m25.yaml`, Saat 25, ohne die ersten), am 25.09.2026 aus Titel, Beschreibung und Schlagwörtern
beschriftet, bevor ein Weg auf ihnen lief; danach wurde nur geprüft, ob die akzeptierten Titel Artikel des Archivs
sind. Hauptartikel der Materialien mit klarem Thema:

| Weg | Gold 1: richtig, falsch, keins | F1 | Gold 2: richtig, falsch, keins | F1 |
|---|---|---|---|---|
| K0 Titel als Thema | 5, 13, 13 | 0,20 | 0, 19, 11 | 0,00 |
| R Regeln (neu, `llm-free`) | 15, 8, 8 | 0,56 | 17, 7, 6 | 0,63 |
| L LLM (neu, `balanced`) | 30, 0, 1 | 0,98 | 26, 3, 1 | 0,88 |
| B Begriff | 29, 2, 0 | 0,94 | 25, 5, 0 | 0,83 |
| BR Begriff und Material, Regeln | 29, 2, 0 | 0,94 | 25, 5, 0 | 0,83 |
| BL Begriff und Material, LLM | 31, 0, 0 | 1,00 | 26, 4, 0 | 0,87 |

Die Regel ohne LLM hält auf den neuen Materialien, was sie auf den alten versprach (0,63 gegen 0,56), während der
Titel dort gar nichts mehr trifft. Materialien ohne Thema (2 und 4): Die Regeln geben bei 5 von 6 keinen Artikel, das
LLM nennt bei 5 von 6 einen (*Marokko* für eine Literaturliste, *Open Educational Resources* für eine Werkzeugliste)
und sagt nur einmal "", wie in M21. Unscharfe Materialien (7 und 6): Regeln 3 und 2 richtig, LLM 4 und 1, der Begriff
7 und 5. Der Begriff selbst trifft auf Gold 2 seltener (0,83): *Siddhartha* führt zum Religionsstifter,
*DNA-Rekombination* zur natürlichen Rekombination, *Photosynthesepigmente* ist kein Artikel.

**Zwei Fehler, die die zweite Stichprobe aufdeckte:** Im ersten Lauf auf Gold 2 lag das LLM bei 0,80, und die Hälfte
seiner Fehler lag nicht am LLM:

- Das LLM nannte „Kreis (Geometrie)“ und „Pong“; die Regeln machten mit dem Fach *Soziale Gruppe* und *Ping
  (Datenübertragung)* daraus. Den genannten Titel prüften die Regeln wie ein Thema, und ein exakter Titel, dessen Anfang
  das Fach nicht nennt, ging an eine Bedeutung der Begriffsklärung, die das Fach einmal im Text erwähnte. Über alle
  Golds griff diese Regel dreimal; richtig war sie nur, wo die Bedeutung das Fach im Titel trägt (*Baum
  (Datenstruktur)*, *Geschichte Indiens*). Seitdem muss sie das (`_meaning_for_subject`); der Begriff „Kreis“ mit dem
  Fach Mathematik bleibt beim Kreis.
- Namen, die kein Artikel sind, fanden über die Volltextsuche einen: „Photosynthesepigmente“ wurde *Engelmannscher
  Bakterienversuch*, „Einwanderung nach Israel“ *Einwanderung der dreihundert Rabbiner*. Ein genannter Titel zählt
  jetzt wie in der Artikelwahl (D35) nur, wenn das Archiv ihn hat; sonst entscheiden die Regeln.

Beide Korrekturen änderten Gold 1 kaum (L 0,97 → 0,98, BL 0,97 → 1,00) und hoben auf Gold 2 L von 0,80 auf 0,88, R
von 0,59 auf 0,63, BR von 0,80 auf 0,83 und BL von 0,83 auf 0,87 (Rohdaten vor der Korrektur:
`m25_knoten_materialien_m25_vor_korrektur.json`).

**Kosten:** Die Regeln brauchen je Material im Median 0,2 bis 0,4 s. Die Frage an das LLM kostete auf den frischen
Materialien von Gold 2 im Median 308 Tokens und 1,8 s, mit Begriff 554 Tokens und 2,6 s (erster Lauf; im zweiten kamen
die Antworten aus dem Zwischenspeicher der b-api).

**Begriff und Material zusammen:** Der Artikel des Materials unterschied sich vom Hauptartikel bei 18 (Regeln) und
12 (LLM) von 38 Materialien in Gold 1 und kam bei je 6 dazu, weil er mit dem Hauptartikel verlinkt ist. Soweit M23
diese Artikel benotet hat (je 5), passten sie oder waren verwandt (Regeln 3 und 2, LLM 4 und 1), keiner war
unpassend. In Gold 2 kamen 5 (Regeln) und 9 (LLM) dazu, ohne Noten. Ob die Kompendien dadurch besser werden, ist
nicht gemessen.

Rohdaten: `m25_knoten_materialien.json`, `m25_knoten_materialien_m25.json`.

### Zeit und Tokens von `balanced` nach D48

Mit `mc_zeit_artikelwahl.py --m25` auf 30 Themen, die keine frühere Messung gestellt hatte (wie M13, gpt-6-luna,
Model2Vec an, Dateicache warm): Teil 1 im Median 1,0 s mit den Regeln und 2,96 s mit `article_choice llm` (im Median
2,0 s mehr, 90. Perzentil 4,2 s, höchstens 5,0 s), im Median 935 Tokens (721 bis 1.175). Die Prüfung der
Nebenartikel lief bei allen 30 Themen, im Median 2,0 s; eine unsichere Artikelwahl kam nicht vor. Verworfen wurden
bei 13 Themen allgemeine oder fremde Artikel (*Geschichte* bei Monsun, *Modell* bei Marktwirtschaft, *Künstler* bei
Expressionismus, *Riemannsche Zeta-Funktion* bei Verschlüsselung). Gegen M13 (gpt-5.6-luna, 1,7 s und 930 Tokens mehr)
kostet `balanced` also gleich viele Tokens und 0,3 s mehr; die längere Zeit je Aufruf von gpt-6-luna kennt M19.
Rohdaten: `m25_zeit_artikelwahl.json`.

### QA-Paare und die übrigen Funktionen

Die Stufe `llm` von `/qa` übernimmt mit `node_id` die Bildungsstufen des Knotens, wenn die Anfrage keine nennt, und
fragt bevorzugt nach Titel und Schlagwörtern des Materials (`qa_pairs` v3); getestet, nicht gemessen. Eine Durchsicht
aller übrigen Endpunkte fand acht Fehler, die behoben sind: ein Template mit kaputtem Muster brach jedes Kompendium mit
500 ab, seine Kennung konnte über die CLI aus dem Template-Verzeichnis hinaus schreiben, eine Sammlung ohne
konfiguriertes Repository ergab 404 statt 503, `/qa` nahm Leerraum als Text, `/knowledge` fragte das LLM vor der
Prüfung des Templates, die CLI stürzte bei unbekanntem Template ab, der Sammlungsüberblick meldete einen Fehler mit
200, und gleichnamige Untersammlungen überschrieben einander in der Zusammenfassung. Dazu wartet der Lehrplan-Abgleich
nach einem Fehler eine Stunde statt sieben Tage, und vier Hilfetexte widersprachen dem Code. `/qa` nimmt jetzt
`subject`, `preset` und `article_choice`, `/knowledge` `subject`, so wie das Kompendium.

**Ergebnis:** Ohne LLM findet der Dienst den Artikel eines Materials mit klarem Thema jetzt bei rund der Hälfte (15
von 31 und 17 von 30; F1 0,56 und 0,63 statt 0,20 und 0,00); bei den übrigen nimmt er etwa so oft einen falschen
Artikel (8 und 7) wie keinen (8 und 6), und ohne Artikel sagt der 404, dass ein `topic` fehlt. Mit LLM trifft er
F1 0,98 und 0,88. Die Nebenartikel ohne Link zum Hauptartikel fallen in allen Stufen weg,
`balanced` prüft zusätzlich die verlinkten, bei gleichen Tokens. Offen: ob der Artikel eines Materials neben einem
Thema das Kompendium besser macht (nur auf Artikelebene gemessen), und die Vorschläge der Durchsicht, die Aufrufer
betreffen (siehe Entscheidungsvorlage, „Zu entscheiden“). Tokens der Messungen von M25 (gpt-6-luna): Nebenartikel
23.490, Knotenfragen 78.984 im ersten und 81.681 im zweiten Lauf (dieser großenteils aus dem Zwischenspeicher der
b-api), Zeitmessung 27.931.

## M27 Die vier Profile im Ablauf des Dienstes (25.09.2026)

Jan legte am 25.09.2026 vier Profile fest (D53, D54): `llm-free`, `balanced`, `best-quality` und
`best-quality-generated`. Diese Messung gibt jedem Profil Werte für Güte, Tokens und Zeit, mit `gpt-6-luna` und dem
Code nach D54, auf dem Entwicklungsrechner (Model2Vec an, `LLM_MAX_TOKENS_PER_REQUEST` 100.000 wie für
`best-quality` empfohlen).

### Zuordnung am Goldstandard: LLM-frei und ausgewogen

Die Entscheidungsvorlage nannte für `balanced` dieselbe Zuordnung wie für `llm-free` (0,43), ohne sie gemessen zu
haben: `compendium eval` bereitet jedes Goldthema ohne LLM-Artikelwahl vor, und `mc_grafiken.py` übernahm den Wert.
`mc_profile_zuordnung.py` misst beide Profile auf den zehn Goldthemen mit derselben Strategie (`hybrid_light` mit
Model2Vec), `balanced` mit der Artikelwahl, wie `/compendium` sie öffnet:

| macro-F1 | LLM-frei | ausgewogen |
|---|---|---|
| gelabelte Absätze (Goldpool) | 0,447 | 0,450 |
| alle Absätze des Korpus | 0,459 | 0,460 |
| bewertete Labels (alle Absätze) | 585 | 581 |

Bei allen zehn Themen wählen Regeln und LLM denselben Hauptartikel. Die Prüfung der Nebenartikel verwarf bei drei
Themen Artikel, nur bei *Französische Revolution* einen mit Absätzen (*Die Französische Revolution*, 20 Absätze
weniger; F1 dieses Themas 0,77 statt 0,68). `balanced` kostete im Median 877 Tokens (703 bis 1.006). Die Zuordnung
bleibt also gleich; `balanced` wirkt vor ihr: bei unsicheren Artikeln (91 statt 86 von 94, M9) und an den
Nebenartikeln (5 statt 12 gedruckte Absätze aus unpassenden Artikeln, M25). Der Wert 0,43 der Vorlage stammt aus M15;
dieselbe Rechnung ergibt heute 0,45. Rohdaten: `m27_zuordnung_gold.json`.

### Tokens: alle Profile auf denselben sechs Themen

`mc_profile.py` erzeugt zu sechs Themen, die keine frühere Messung gestellt hatte (Zellatmung, Elektrischer
Widerstand, Kolonialismus, Lineare Gleichung, Renaissance, Klimazonen), Teil 1 und Teil 2 in allen vier Profilen:

| Profil | Tokens, Median (Spanne) | LLM-Aufrufe | gefüllte Inhaltsbausteine | Sätze mit Modellwissen |
|---|---|---|---|---|
| `llm-free` | 0 | 0 | 8 | – |
| `balanced` | 905 (750 bis 1.103) | 1 | 8 | – |
| `best-quality` | 26.267 (4.942 bis 54.448) | 5 | 8,5 | – |
| `best-quality-generated` | 35.376 (9.223 bis 65.975) | 10,5 | 8,5 | 82 in 6 Themen (3 bis 25) |

Die Tokens wachsen mit der Zahl der Absätze: rund 170 je Absatz für die LLM-Zuordnung (18 Absätze bei Zellatmung,
323 bei Renaissance); das Umformulieren kostet je Thema 4.300 bis 11.600 Tokens mehr. Die LLM-Zuordnung füllt bei
großen Themen mehr Bausteine (Renaissance 11 statt 9, Klimazonen 10 statt 7), beim kleinen Thema Zellatmung weniger
(4 statt 7). Der Hauptartikel war in allen Profilen derselbe. Die Zeiten dieses Laufs gelten nicht: Artikelwahl und
Zuordnung schicken in mehreren Profilen denselben Prompt, und der Zwischenspeicher der b-api beantwortete ihn beim
zweiten Profil in Zehntelsekunden. Rohdaten: `m27_profile_tokens.json`.

### Zeit: jedes Profil auf eigenen Themen

`mc_profile_zeit.py` gibt deshalb jedem LLM-Profil sechs eigene Themen, 18 weitere, die keine Messung gestellt
hatte; `llm-free` läuft auf allen 18, weil es keinen Prompt schickt. Teil 1 und Teil 2 je Kompendium:

| Profil | `llm-free` plus LLM-Anteil, Median (Spanne) | gemessen, Median (Spanne) | Tokens, Median (Spanne) | Absätze je Thema |
|---|---|---|---|---|
| `llm-free` (18 Themen) | – | 1,6 s (1,1 bis 3,0) | 0 | 152 |
| `balanced` | 3,4 s (1,4 bis 5,3) | 5,8 s (2,1 bis 6,3) | 833 (767 bis 907) | 225 |
| `best-quality` | 14,2 s (11,4 bis 15,7) | 14,7 s (12,5 bis 19,6) | 19.484 (11.793 bis 35.447) | 105 |
| `best-quality-generated` | 23,5 s (18,6 bis 28,1) | 23,8 s (20,2 bis 28,7) | 41.641 (27.566 bis 67.892) | 205 |

Die lokalen Schritte (Korpus, Text, Teil 2) liefen in einigen LLM-Läufen um 0,3 bis 2 s langsamer als im Durchgang
ohne LLM auf denselben Themen: Während der Messung zog der Rechner ein Image und maß im Container QA-Paare (M29). Die
belastbarere Zahl ist deshalb die Zeit von `llm-free` auf demselben Thema plus dem LLM-Anteil aus den Phasen des
Audits (`mc_grafiken.py`, `profile_seconds`); bei `best-quality` und `best-quality-generated` liegen beide nah
beieinander, bei `balanced` nicht. LLM-Anteil im Median: Prüfung der Nebenartikel 1,5 s (0,1 bis 4,2), mit
LLM-Zuordnung 12,7 s, mit Umformulieren 21,4 s; M25 maß für `balanced` 2,0 s mehr, hier 1,5 s.
Die drei Sätze sind verschieden groß; die Tokens vergleicht die Tabelle davor besser. `/knowledge` (Auflösung,
Korpus, Prüfung der Nebenartikel) braucht danach 0,5 s ohne LLM und rund 2 bis 3 s mit. Rohdaten:
`m27_profile_zeit.json`.

## M28 Lesefassung: `best-quality-generated` gegen `best-quality` (25.09.2026)

Punkt 3 der Entscheidungsvorlage verlangte vor einer Lesefassung einen Richtervergleich. Die Texte von Teil 1 aus M27
zu den sechs Themen, einmal wörtlich (`best-quality`) und einmal vom LLM geschrieben und um Modellwissen ergänzt
(`best-quality-generated`), gingen ohne ihre Kennzeichen (Kommentare entfernt, Belegnummern stehen gelassen) als A und
B in zufälliger Reihenfolge an zwei Claude-Gutachter. Sie benoteten jeden Text von 1 bis 5 nach Lesbarkeit für eine
Lehrkraft, Zusammenhang und Themenbezug, zählten Füllsätze (Aussagen über Text, Baustein oder Kompendium,
Allgemeinplätze, Wiederholungen), listeten Fachfehler und wählten den besseren Einstieg. Danach bewerteten sie jeden
der 82 Sätze mit Modellwissen nach Richtigkeit und Nutzen.

| je Text, Mittel über beide Gutachter und sechs Themen | `best-quality` (wörtlich) | `best-quality-generated` |
|---|---|---|
| Lesbarkeit, 1 bis 5 | 2,5 | 4,0 |
| Zusammenhang, 1 bis 5 | 2,4 | 4,0 |
| beim Thema, 1 bis 5 | 3,6 | 3,5 |
| Füllsätze je Thema | 0,8 | 12,3 |
| Fachfehler, Summe beider Gutachter | 17 | 14 |
| als besserer Einstieg gewählt | 1 von 12 | 11 von 12 |

Die wörtliche Fassung verlor vor allem an Bruchstücken: Sätze ohne Bezug („Dabei …“), fehlende Formelzeichen,
zerbrochene Tabellen, Verweise auf Karten, die es nicht gibt. Die Fachfehler stehen meist schon in den Quellen und
kommen in beiden Fassungen vor (etwa die Unabhängigkeit der USA „1789“ aus dem Klexikon). Beide Fassungen verloren bei
*Lineare Gleichung* den Themenbezug (partielle Differentialgleichungen) und bei *Klimazonen* Absätze über
Winterhärtezonen. Von den 82 Sätzen mit Modellwissen nannten beide Gutachter 52 Füllsätze und 26 fachlich; zwei
hielten beide für falsch, 7 und 8 für fraglich. Die Füllsätze sind vor allem Aussagen über den Text („Der Baustein
behandelt …“, „Das Kompendium fragt …“) und Transfer- oder Unterrichtsfloskeln („Als Transferprinzip lässt sich
daraus ableiten …“), am häufigsten in Praxis (12 der 17 ergänzten Sätze), Gesellschaftlicher Kontext (11 von 13) und
Themendefinition (7 von 8), jeweils von beiden als Füllsatz gewertet; in Entwicklung & Ausblick waren es nur 4 von 19.

**Ergebnis:** Für Menschen, die den Text direkt lesen, ist die geschriebene Fassung klar besser. Das ergänzte
Modellwissen trägt dazu wenig bei: zwei Drittel davon sind Füllsätze, die den Text länger, aber nicht reicher machen.
Die Gutachter sind Sprachmodelle, keine Lehrkräfte; sechs Themen sind eine kleine Stichprobe. Rohdaten:
`m28_lesefassung.json` (Noten, Zählungen und Urteile je Satz, ohne Texte und Zitate).

## M29 QA-Paare je Profil (25.09.2026)

D54 gibt `llm-free` das Verfahren `parse-based` und den übrigen Profilen `llm`. Für `llm` gab es bis dahin keine
Messung (M25: „getestet, nicht gemessen“). `mc_qa_profile.py` fragt beide auf den Texten der vier Kompendien der
Messung vom 22.09.2026 (Optik, Ernst Abbe, Französische Revolution, Photosynthese; Teil 1 von `llm-free`, so wie
`/qa` ihn abfragt, 5.200 bis 8.600 Zeichen) nach je 20 Paaren: `parse-based` im Image, das das spaCy-Modell hat,
`llm` (`gpt-6-luna`) auf dem Entwicklungsrechner mit denselben Texten.

| | `parse-based` (`llm-free`) | `llm` (übrige Profile) |
|---|---|---|
| Paare, angefragt 4 × 20 | 29 (13, 5, 7, 4) | 80 |
| Zeit je Text | 0,14 bis 0,31 s | 3,9 bis 5,7 s |
| Tokens je Text | 0 | 1.972 bis 2.721 |
| mangelfrei, Gutachter 1 und 2 | 1 und 4 von 29 | 74 und 68 von 80 |
| mangelfrei bei beiden | 1 | 67 |
| ohne den Mangel „doppelt“ | 8 und 11 | 75 und 73 |
| Anfänge der Fragen | 2 (Was, Wer) | 21 |

Zwei Claude-Gutachter bewerteten blind: je Thema die Paare beider Verfahren gemischt in fester Zufallsordnung, ohne
Angabe des Verfahrens. Mangelfrei heißt, eine Lehrkraft kann das Paar ohne Änderung für eine Wissensabfrage zum Text
verwenden; sonst nennt das Urteil einen Hauptmangel (Sachfehler, unbelegt, Frage unklar, Antwort passt nicht,
trivial, doppelt). Die Gutachter waren sich bei 98 von 109 Paaren einig. Die Mängel von `parse-based`: Frage ohne
den Text unverständlich (10), trivial (5 und 7, etwa „Was ist die Lehre vom Licht? – Die Optik“), doppelt (7),
Antwort passt nicht (3 und 4). Beim LLM: doppelt oder unklar je 1 bis 5, zwei Antworten passen nicht, ein bis zwei
triviale; kein Sachfehler und keine unbelegte Antwort. Das Maß ist strenger als am 22.09. (dort 26 von 33 mangelfrei
für `parse-based`, gezählt nur Wiederholung, Rückverweis und Echo). „Doppelt“ zählt ein Paar, das dasselbe fragt wie
ein früheres desselben Themas; im gemischten Bogen trifft das auch Paare, deren Inhalt ein Paar des anderen
Verfahrens schon abfragte, deshalb die Zeile ohne diesen Mangel.

**Ergebnis:** Die LLM-Paare sind fast alle brauchbar, für rund 2.000 bis 2.700 Tokens und 4 bis 6 s je Text. Die
Paare aus dem Parse kosten nichts und sind schnell, aber nur wenige taugen ohne Nacharbeit. Rohdaten:
`m29_qa.json` (Zahlen, Verfahren je Paar und die Urteile; ohne Texte und Paare, die aus den Artikeln stammen).

## M30 QA-Stufen nach D55 (26.09.2026)

Jan fand die Paare der Standardstufe zu einseitig, fast nur Jahresfragen, und `count` nicht eingehalten: 20 verlangt,
rund 5 geliefert. D55 lässt `rule-based` aus dem spaCy-Parse fragen statt aus vier Vorlagen, gibt `balanced` die zwei
kleinen Modelle und macht Teil 1 immer ohne LLM. `mc_qa_stufen.py` fragt alle Stufen auf denselben Texten nach je 20
Paaren: Teil 1 von `llm-free` zu den vier Themen von M29 (Optik, Ernst Abbe, Französische Revolution, Photosynthese)
und zu zwei Themen, an denen keine Regel abgestimmt wurde (Zellteilung, Weimarer Republik), 4.900 bis 12.000 Zeichen;
die Regeln lesen dazu Glossar und Akteure. Die freien Stufen liefen im Image, `llm` (`gpt-6-luna`) auf dem
Entwicklungsrechner. Die vier Texte aus M29 sind unverändert; die b-api gab ihre LLM-Paare aus dem Cache zurück, es
sind also die Paare von M29.

| je Stufe, sechs Texte mit je 20 verlangt | `rule-based` neu (`llm-free`) | Vorlagen bis D55 | `parse-based` | `models` (`balanced`) | `llm` (`best-quality`) |
|---|---|---|---|---|---|
| Paare von 120 | 96 | 56 | 44 | 120 | 120 |
| Texte mit 20 von 20 | 3 | 1 | 0 | 6 | 6 |
| Fragen nach einer Zeit | 9 | 46 | 0 | 6 | 14 |
| verschiedene Frageanfänge je Text, Median | 5 | 1 | 1 | 7,5 | 8 |
| Zeit je Text, Median | 0,28 s | 0,02 s | 0,17 s | 25 s (18 bis 36 s) | 4 bis 6 s (M29), neu 7,2 und 7,5 s |
| Tokens je Text | 0 | 0 | 0 | 0 | 1.972 bis 3.870, Median 2.402 |
| mangelfrei, Gutachter 1 und 2 | 50 und 52 von 96 | nicht bewertet | 16 und 17 von 44 | 27 und 25 von 120 | 105 und 100 von 120 |
| mangelfrei bei beiden | 48 (50 %) | – | 16 (36 %) | 25 (21 %) | 99 (83 %) |

Die Regeln liefern 9 bis 20 Paare je Text: 20 bei Optik, Ernst Abbe und Weimarer Republik, 16 bei der Französischen
Revolution, 11 bei der Photosynthese und 9 bei der Zellteilung, deren Teil 1 mit 4.900 Zeichen der kürzeste ist. Die
Vorlagen fragten zu 82 % nach einer Zeit („Was geschah im Jahr …?“), die Regeln zu 9 %. Frageanfänge zählen nur das
erste Wort; bei den Regeln beginnen Definition, Objekt- und Subjektfrage alle mit „Was“, die Arten sind vielfältiger als
die Anfänge.

Zwei Claude-Gutachter bewerteten blind mit dem Auftrag von M29, je drei Themen auf einem Bogen, die Paare von Regeln,
Parse, Modellen und LLM je Thema gemischt in fester Zufallsordnung; die Vorlagen nicht, ihre Art zeigen M29 und D55.
Einig waren sie bei 364 von 380 Paaren. Die Mängel, Gutachter 1 und 2: bei den Regeln Frage ohne den Text
unverständlich (23 und 24, etwa „Was ist notwendig?“ oder „Wo befinden sich die Kurszentren?“), doppelt (11 und 9),
Antwort passt nicht (7 und 6), trivial (je 4), ein Sachfehler; bei den Modellen Antwort passt nicht (je 27), Sachfehler
(je 24, etwa „Wer war seit 1899 Hauptinhaber der Firma Carl Zeiss? – Jenaer Glaswerk Schott & Gen“), Frage unklar
(24 und 26), doppelt (11 und 10), trivial (5 und 6), unbelegt (je 2); beim LLM doppelt (7 und 6), Antwort passt nicht
(je 5), trivial (3 und 4), Frage unklar (0 und 5). Drei der 96 Regel-Paare waren Definitionsfragen zu einem Adverb
oder einer Präposition am Satzanfang („Was versteht man unter Daneben?“); der Smoke-Test des Images fand den Fehler, der
Fix `2542932` kam nach dieser Messung. Ohne sie sind 48 von 93 Regel-Paaren bei beiden mangelfrei (52 %).

Das Maß schwankt zwischen zwei Läufen: Die 80 LLM-Paare der vier M29-Themen bewerteten die Gutachter wie in M29
(67 bei beiden mangelfrei, damals 67), die 29 Paare aus dem Parse aber milder (9 statt 1). Es trennt die Stufen, die
Zahl einer Stufe ist auf einige Paare genau.

**Ergebnis:** Die Regeln von D55 halten `count` bei längeren Texten ein, fragen kaum noch nach Jahren und liefern die
Hälfte ihrer Paare mangelfrei, ohne Modell und in 0,3 s; ihr häufigster Mangel ist eine Frage, die ohne den Text nicht
verständlich ist. Die kleinen Modelle halten `count` immer ein und fragen am vielfältigsten, aber nur ein Fünftel ihrer
Paare ist mangelfrei, und sie brauchen rund 25 s je Text. Das LLM bleibt mit vier von fünf mangelfreien Paaren die
beste Stufe. Rohdaten: `m30_qa.json` (Zählung je Stufe und Thema, Verfahren je Paar und die Urteile; ohne Texte und
Paare).

## M31 Modellwissen mit Prompt v2 (26.09.2026)

M28 fand zwei Drittel des Modellwissens von `best-quality-generated` Füllsätze. D56 schärft den Prompt
`section_enrichment` (v2): eine konkrete, überprüfbare Sachaussage, die in den Belegen fehlt, oder nichts; keine Sätze
über Text, Baustein, Kompendium oder Unterricht, keine Transferfloskeln. `mc_modellwissen_v2.py` erzeugte die sechs
Themen von M27 noch einmal in `best-quality-generated`. Artikelwahl und Zuordnung stellten der b-api dieselben Fragen
wie damals und kamen aus ihrem Cache, alle sechs Hauptartikel sind dieselben; die beiden Fassungen unterscheiden sich
nur darin, wie die Bausteine geschrieben wurden. Zwei Claude-Gutachter bewerteten v1 (M27) und v2 blind mit dem Auftrag
von M28: je Thema beide Texte als A und B in fester Zufallsordnung, Kommentare und Kennzeichen entfernt, dann jeden
der 132 Sätze mit Modellwissen beider Fassungen in einer gemischten Liste.

| je Fassung, sechs Themen | v1 (M27, M28) | v2 (D56) |
|---|---|---|
| Sätze mit Modellwissen | 82 | 50 |
| davon Füllsätze nach beiden Gutachtern | 50 | 13 |
| davon fachlich nach beiden | 27 | 32 |
| davon falsch nach beiden | 2 | 0 |
| Füllsätze je Text, Mittel beider Gutachter | 11,5 | 5,4 |
| Lesbarkeit, Zusammenhang, beim Thema (1 bis 5) | 3,7; 3,5; 3,8 | 3,5; 3,3; 3,9 |
| Fachfehler, Summe beider Gutachter | 11 | 10 |
| als besserer Einstieg gewählt | 4 von 12 | 8 von 12 |
| Tokens je Kompendium, Median | 35.376 | 36.450 |

Die Sätze von v1 bewerteten die Gutachter fast wie in M28 (50 statt 52 Füllsätze, 27 statt 26 fachlich, dieselben zwei
falsch); das Maß ist hier stabil. Die 13 Füllsätze von v2 sind drei rhetorische Fragen („Wie wird die gewonnene Energie
verfügbar gemacht?“), fünf Zuordnungen zu Fachgebieten („Der Gegenstand gehört zur Klimatologie …“) und fünf
Allgemeinplätze über Berufe und Branchen; Fragen verbietet der Prompt noch nicht. Beim Elektrischen Widerstand und bei
der Linearen Gleichung zogen beide Gutachter v1 vor: v1 nennt dort Namen und eine Formel (Siemens, Ohm, R = ρ·l/A) oder
ordnet die Beispiele ein, v2 bleibt näher an den Auszügen. Ein Satz von v2 nannte sich selbst „Modellwissen: …“; der Fix
`a965dd0` nimmt das Präfix heraus, bevor der Dienst sein sichtbares Kennzeichen setzt. Der längere Prompt kostet rund
3 % mehr Tokens.

**Ergebnis:** v2 ergänzt weniger, und was es ergänzt, ist öfter Sache: 32 statt 27 fachliche Sätze, 13 statt 50
Füllsätze, keiner falsch nach beiden Gutachtern. Lesbarkeit und Zusammenhang bleiben gleich, im Vorzug liegt v2 vorn.
Ganz ohne Füllsätze ist auch v2 nicht: rund fünf je Text, gegen zwölf vorher. Die Gutachter sind Sprachmodelle,
keine Lehrkräfte, und sechs Themen sind eine kleine Stichprobe. Rohdaten: `m31_modellwissen.json` (Noten, Zählungen,
Urteile je Satz mit Fassung; ohne Texte und Sätze).

## M32 Lehrplanbezüge nach D58 (26.09.2026)

Jan nahm die Profile für Teil 2 an und gab die MEM-Daten ohne Einschränkung frei (D58): In allen Profilen stehen
Elemente, die nur ihre Überschrift zum Thema macht, gebündelt bei ihrem Bereich (B aus M22), in den beiden
`best-quality`-Profilen prüft zusätzlich das LLM jedes Element (`curriculum_check=llm`). `mc_lehrplan_pruefung.py`
stellt die 40 Anfragen von M22 (20 Themen, ohne und mit dem Fach, das eine Lehrkraft nennen würde) im Ablauf des
Dienstes, mit dem Profil `llm-free` - die Regeln wählen den Artikel wie in M22 - und `parts=["curricula"]`: einmal nur
mit den Regeln (A, `f5d8297`, und B), einmal mit der LLM-Prüfung (`gpt-6-luna`, Budget und Frist wie ausgeliefert:
60.000 Tokens und 120 s je Anfrage). Bewertet wird mit den Noten von M22 (zwei Gutachter, 175 Elemente) und dem
Schätzer von M22, eingeschränkt auf die Elemente, die Teil 2 einzeln zeigt: je Thema aus beiden Schichten
hochgerechnet, dann über die Themen gemittelt, Gutachter 1 und 2.

| Mittel über 20 Themen | alles (nach A) | B: einzeln gezeigt (`llm-free`, `balanced`) | LLM-Prüfung: einzeln gezeigt (`best-quality`) |
|---|---|---|---|
| Elemente ohne / mit Fach | 4.579 / 3.120 | 3.103 / 1.932 | 3.691 / 2.667 |
| passend, ohne Fach | 62 und 64 % | 70 und 72 % | 74 und 77 % |
| passend, mit Fach | 64 und 67 % | 77 und 81 % | 76 und 79 % |
| passt nicht, ohne Fach | 12 und 17 % | 8 und 9 % | 5 und 8 % |
| passt nicht, mit Fach | 11 und 17 % | 5 und 6 % | 5 und 9 % |
| passende Elemente der Stichprobe, die nicht einzeln stehen | 0 | 24 von 92 und 25 von 95 | 1 und 1 |
| Tokens je Anfrage, Median ohne / mit Fach | 0 | 0 | 9.564 / 7.817 |
| Sekunden je Anfrage, Median ohne / mit Fach | 0,7 / 0,1 | 0,7 / 0,1 | 6,4 / 6,0 |

B hebt den Anteil passender Elemente unter den einzeln gezeigten ohne Kosten und halbiert die unpassenden; ein Drittel
der Elemente ohne Fach und zwei Fünftel mit Fach stehen nur noch in der Bündelzeile ihres Bereichs, darunter ein
Viertel der passenden. Die LLM-Prüfung erreicht einen ähnlichen Anteil passender und unpassender Elemente, zeigt aber
fast alle passenden einzeln: Kein Element, das ein Gutachter passend nannte, bewertete das LLM mit 0. Von den
unpassenden der Stichprobe, die A noch findet, verwarf es 14 von 24 und 17 von 33, viele weitere bewertete es mit 1
(berührt das Thema) und behielt sie; seine Nullen trafen 14 von 18 und 17 von 18 Mal unpassende Elemente, der Rest
berührte das Thema. Verworfen hat es 400 von 4.579 Elementen ohne Fach und 177 von 3.120 mit Fach.

Die Prüfung kostet rund 75 bis 80 Tokens je Element. Ohne Fach im Median 9.564 Tokens und 6,4 statt 0,7 s je
Anfrage, höchstens 55.599 Tokens und 26 s (Demokratie, 819 Elemente); mit Fach 7.817 Tokens und 6,0 statt 0,1 s,
höchstens 47.970 Tokens und 13 s. Bei Demokratie ohne Fach reichte das Budget von 60.000 Tokens nicht: 180 der 819
Elemente blieben ungeprüft bei den Regeln. In `best-quality` teilt sich die Prüfung das Budget mit der LLM-Zuordnung
(rund 26.000 Tokens, M27); dann reicht es für rund 400 Elemente, und bei breiten Themen ohne Fach bleibt der Rest bei
den Regeln. Der ganze Lauf kostete 592.835 Tokens.

D1, die Ähnlichkeit von Thema und Element unter dem Model2Vec-Modell des Dienstes: AUC 0,74 bis 0,76 zwischen
passenden und unpassenden Elementen, 0,65 bis 0,69 zwischen passenden und dem Rest, mit der Überschrift nicht besser.
Eine Schwelle, die die Hälfte der unpassenden Elemente entfernt, nähme 25 bis 31 % der passenden mit.

**Ergebnis:** B bringt `llm-free` und `balanced` ohne Kosten von rund 63 auf 71 % passende Elemente ohne Fach und
auf 79 % mit Fach und halbiert die unpassenden; was es bündelt, ist über den Bereich erreichbar. Die LLM-Prüfung von
`best-quality` erreicht 74 bis 79 % passend und 5 bis 9 % unpassend, ohne passende Elemente zu verlieren, für rund
8.000 bis 10.000 Tokens und 6 s je Anfrage; bei breiten Themen ohne Fach reicht das Budget von 60.000 Tokens nicht für
alle Elemente. D1 wird nicht gebaut: Es verlöre ein Viertel der passenden Elemente. Die Gutachter sind Claude, keine
Lehrkräfte; je Thema und Schicht stehen höchstens fünf Elemente in der Stichprobe. Rohdaten:
`m32_lehrplan_pruefung.json` (je Anfrage Elemente, Verworfene, Tokens und Sekunden, je Stichprobenelement Fundort,
Note des LLM, beide Noten und die Ähnlichkeit; ohne Texte).

## M33 Budget von `best-quality` nach D59 (26.09.2026)

Jan hob das Budget je Anfrage der beiden `best-quality`-Profile auf 120.000 Tokens (D59); in M32 reichten 60.000 bei
Demokratie ohne Fach (819 Elemente) nicht für die Prüfung aller Lehrplanelemente. `mc_budget_best_quality.py` stellt
dasselbe Thema im Ablauf des Dienstes, über die API (`gpt-6-luna`, Frist 120 s), mit dem Budget der Befehlszeile: als
Kompendium mit Teil 1 und 2 in beiden `best-quality`-Profilen und im ersten Lauf als Lehrplansuche mit `mode=topic`.

| Demokratie ohne Fach: 382 Absätze, 819 Elemente | Budget | Tokens (Aufrufe) | Elemente geprüft, verworfen | Sekunden |
|---|---|---|---|---|
| Lehrplansuche, `best-quality` | 120.000 | 75.016 (15) | 819, 58 | 9,5 |
| Kompendium, `best-quality` | 120.000 | 112.626 (19) | 579, 40; 240 bei den Regeln | 20,9 |
| Kompendium, `best-quality` | 200.000 | 137.398 (23) | 819, 58 | 2,6 |
| Kompendium, `best-quality-generated` | 200.000 | 152.197 (32) | 819, 58 | 8,1 |
| Kompendium, `best-quality` | 180.000 | 137.398 (23) | 819, 58 | 2,0 |
| Kompendium, `best-quality-generated` | 180.000 | 152.197 (32) | 819, 58 | 1,5 |

In allen Kompendien ordnete das LLM alle 382 Absätze zu, in `best-quality-generated` schrieb es dazu 9 Bausteine.
Die Zuordnung eines so großen Themas braucht den größeren Teil des Budgets (im Median von M27 26.267 Tokens je
Kompendium). Ein Stapel der Prüfung reserviert vorab 8.500 bis 10.400 Tokens und verbraucht rund 5.000; passt die
Reservierung nicht mehr ins Budget, behält er die Entscheidung der Regeln: Bei 120.000 fanden vier Stapel keinen Platz
mehr (7.374 Tokens frei). Die Lehrplansuche prüft rund 90 Tokens je Element; ein Kompendium nur mit Teil 2 fragt
dasselbe. Der Lauf mit 200.000 zeigt den Bedarf ohne Grenze, 137.398 und 152.197 Tokens; Jan gab frei, das Budget zu
erhöhen, und 180.000 lassen dem schreibenden Profil 28.000 Tokens Luft für Reservierungen und längere Antworten. Die
b-api beantwortete Aufrufe, die sie schon kannte, aus ihrem Zwischenspeicher - dieselbe Antwort und dieselben Tokens:
Die Sekunden der späteren Läufe sind deshalb zu kurz, der erste zeigt die Dauer ohne Zwischenspeicher.

**Ergebnis:** Mit 180.000 Tokens je Anfrage prüfen beide `best-quality`-Profile beim breitesten Thema von M32 alle
Lehrplanelemente, auch neben der Zuordnung von 382 Absätzen und dem Schreiben; 120.000 reichten dafür nur in der
Lehrplansuche. Rohdaten: `m33_budget_best_quality.json` (je Lauf Budget, Tokens, Sekunden, Zahlen und die Gründe der
Rückfälle; keine Texte).

## M34 QA-Regeln nach D60 (26.09.2026)

Jan entschied, dass die Regeln mit Glossar und Akteuren auffüllen, wenn ein Text wenig hergibt (D60); dazu kamen die
Sperren aus Punkt 7 der Entscheidungsvorlage. `mc_qa_nachschaerfung.py` stellt die Regeln vor und nach D60 auf die
sechs Texte von M30 mit ihrem Glossar und ihren Akteuren, je 20 Paare, im Image (spaCy). Die Regeln vor D60 erzeugen
dort fast genau die Paare von M30: 93 von 95 kennen die Urteile von M30. Für die Regeln nach D60 ersetzt das Skript in
den Bögen von M30 die Paare der Regeln durch die neuen, lässt die der anderen Verfahren an ihrem Platz und nummeriert
alles neu; zwei blinde Claude-Gutachter bewerten mit dem Auftrag von M30.

| Regeln auf den sechs M30-Texten, je 20 verlangt | vor D60 (Urteile M30) | nach D60 (Urteile M34) |
|---|---|---|
| mangelfrei bei beiden Gutachtern | 46 von 95, 2 ohne Urteil | 58 von 95 |
| Erstfragen aus dem Text | 16 von 52 | 25 von 49 |
| Glossar-Definitionen | 8 von 13, 2 ohne Urteil | 10 von 15 |
| Füller aus Glossar und Akteuren | 20 von 23 | 22 von 29 |
| zweite Frage zu einem Satz | 2 von 5 | 1 von 2 |
| Mängel, Urteile beider Gutachter | frage_unklar 47, doppelt 20, antwort_passt_nicht 13, trivial 8, sachfehler 2 | frage_unklar 26, trivial 19, doppelt 10, antwort_passt_nicht 8, sachfehler 4 |

Weggefallen sind 13 Paare, 12 davon bemängelt: „Was ist notwendig?“, „Was lautet?“, „Was dauern
Prüfungsvorbereitungskurse … ungefähr?“, die Fragen mit einem zweiten Verb hinter „und“; eine mangelfreie Wiederholung
wich einem Füller. Neu kamen unter anderem „Seit wann war Ernst Abbe Alleininhaber der Firma Carl Zeiss?“ und „Was
versteht man unter Sauerstoff?“. Die Gegenprobe: Dieselben Paare der anderen Verfahren nannten die Gutachter von M34
etwas seltener mangelfrei als die von M30 (LLM 96 statt 99 von 120, Parse 12 statt 16 von 44, Modelle 24 statt 25 von
120); der Zuwachs kommt also nicht von milderen Urteilen. Mehr Füller heißt auch mehr Nachbarn: „Wer war Immanuel
Kant?“ im Kompendium zu Ernst Abbe nannten beide trivial, wie schon in M30, ebenso „Was beziffert sich auf 6,497
Milliarden Euro?“. Kurze Themen bleiben kurz: Photosynthese 12 statt 11, Zellteilung 8 statt 9 von 20, weil Glossar
und Akteure dort klein sind.

Modellwissen (Punkt 3): In den Texten von M31 sind 3 der 50 Sätze mit Modellwissen Fragen, nach beiden Gutachtern
alle drei Füllsätze. Seit D60 fallen sie weg; gezählt an den gespeicherten Texten, ohne neuen Lauf.

**Ergebnis:** 58 statt 46 von 95 Regel-Paaren mangelfrei, ohne Modell und ohne Tokens. Die meisten übrigen Mängel sind
Fragen, die ohne den Text nicht zu verstehen sind („Wo befinden sich die Kurszentren?“), und Nachbar-Personen. Die
Gutachter sind Claude, keine Lehrkräfte. Rohdaten: `m34_qa_regeln.json` (Kennungen, Verfahren, Urteile und Zahlen;
keine Texte und Paare).

Nachtrag nach zwei Reviews von D60 (26.09.2026, `6b39f9c`, `56f2904` und die Korrekturen des zweiten): Seit D60
lesen die Regeln auch den Text, den ein Aufrufer schickt. Sechs präparierte Texte der Höchstlänge (50.000 Zeichen,
lange Leerzeichenfolgen in Glossarzeile, Begriff, Definition, Akteursname, Akteurszeile und Prosa) brauchten vorher
3,7 s bis Stunden - die Glossarzeile kubisch, 13 s schon bei 3.000 Leerzeichen. Das zweite Review fand weitere Formen:
Folgen von „(“ in Begriff und Name (1,5 s) und in `parse_document` „### “ über und über (2,3 s bei 50.000, 9,5 s bei
100.000 Zeichen) oder abgebrochene Zitatzeilen (0,9 s). `parse_document` liest auch `existing_markdown` von
`/compendium`, bis 2.000.000 Zeichen: rund eine Stunde je Anfrage, eine Lücke älter als D60. Jetzt brauchen alle zwölf
Eingaben 1 bis 4 ms und 2.000.000 Zeichen Markdown rund 40 ms; `parse_document` liest acht echte Kompendien (Vorlagen,
Facetten, Hinweise leerer Bausteine, Teil 2) wie zuvor. Keine der Korrekturen ändert an den Kompendien der sechs
Themen ein Paar, weder über `topic` noch über das Markdown als `text` (bis 50 Paare je Thema, live im
Entwicklungscontainer verglichen), auch nicht die Mengensperre, die für „wiegen“ und „zählen“ wieder wie in D60 immer
gilt und für „messen“ nur bei einer eigenen Zahl des Objekts; M34 beschreibt also weiter den heutigen Stand.

## M35 Sichere Auflösungen mehrdeutiger Wörter (26.09.2026)

Punkt 5 der Entscheidungsvorlage: Mit `article_choice=llm` entscheidet das LLM nur, wo die Regeln unsicher sind (D35).
Soll es auch sichere Auflösungen mehrdeutiger Wörter prüfen? `mc_sichere_aufloesung.py` stellt die 94 Anfragen der drei
Gold-Dateien von `eval/artikelwahl` durch `choose_main_article`, den Auflösungsschritt des Dienstes, in vier Varianten:
die Regeln allein, das LLM für unsichere Fälle wie heute (`balanced`), dazu A für sichere Auflösungen über eine
Begriffsklärungsseite und B zusätzlich für sichere exakte Titel, zu denen es „<Titel> (Begriffsklärung)“ gibt. Das LLM
sieht dieselben Kandidaten wie bei einer unsicheren Auflösung. Modell `gpt-6-luna` an der Staging-b-api.

| Variante | richtig von 94 | Haupt / Validierung / Test | LLM gefragt | Tokens |
|---|---|---|---|---|
| Regeln (`llm-free`) | 87 | 56 / 22 / 9 | 0 | 0 |
| unsichere Fälle (`balanced` heute) | 91 | 57 / 23 / 11 | 18 | 17.707 |
| A: dazu sichere Begriffsklärungen | 92 | 58 / 23 / 11 | 47 | 49.653 |
| B: dazu exakte Titel mit Begriffsklärungsseite | 93 | 58 / 23 / 12 | 64 | 60.169 |

A behebt „Physik: Strom“ (*Strom (Physik)* statt *Elektrischer Strom*), B dazu „Informatik: Netzwerk“ (*Netzwerk* statt
*Rechnernetz*). Keine der 44 richtigen sicheren Auflösungen, die das LLM zusätzlich sah, hat es verdorben. Eine neue
Frage kostete im Median 818 Tokens (321 bis 2.064) und rund 1 s (0,1 bis 1,8 s, gemessen im ersten Lauf ohne Last
nebenher); B fragt bei 64 statt 18 von 94 Anfragen. Falsch bleibt nur „Lichtlehre“: Die Regeln finden per Volltext
eine Person, das LLM wählt aus zwei Kandidaten ebenfalls falsch.

Nebenbefund, behoben in `20aaca4`: Die Archive führen eine Weiterleitung auf einen Abschnitt eines anderen Artikels als
eigene Seite, mit einem Meta-Refresh auf „./Lyrik#Gedicht“ und dem Titel als einzigem Text. Die Auflösung nahm diese
Seite als Hauptartikel, sicher: Ein Kompendium zu „Gedicht“ baute auf 7 Zeichen, „Nenner“ auf 6, „Elektrischer Leiter“
auf 19. Seit `20aaca4` folgt sie der Seite zum Artikel (*Lyrik*, 32.394 Zeichen; *Bruchrechnung*; *Leiter (Physik)*).
Die Auswertung aller Gold-Messungen folgte solchen Weiterleitungen ebenso wenig; deshalb zählte „Physik: Leiter“ bisher
falsch, obwohl der Dienst *Leiter (Physik)* nahm, den Artikel, auf den *Elektrischer Leiter* weiterleitet. Mit der
korrigierten Auswertung stehen die Regeln bei 87 statt 86 und `balanced` bei 91 statt 90 von 94; „Gedicht“ bleibt
richtig, nun mit *Lyrik*. Der erste Lauf vor dem Fix ergab dieselben Unterschiede zwischen den Varianten.

**Ergebnis:** Die Prüfung sicherer Auflösungen lohnt sich an diesem Gold, ohne etwas zu verderben: B bringt zwei der
drei übrigen Fehler in Ordnung, kostet dafür 46 zusätzliche Aufrufe auf 94 Anfragen, rund 800 Tokens und 1 s je
betroffener Anfrage. Zwei Treffer auf 94 sind wenig; das Gold hat noch keine Redaktion gesehen (Punkt 4), und
Validierung und Test sind nicht unabhängig. Rohdaten: `m35_sichere_aufloesung.json` (Titel, Kennzeichen, Tokens und
Sekunden je Anfrage und Variante; keine Artikeltexte).
