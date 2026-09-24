# Alter und neuer Dienst im Vergleich

[Übersicht](README.md) · Messaufbau: [Messprotokoll](05-messprotokoll.md), Abschnitte M1 bis M3, M9, M12 und M13

## Der alte Dienst (v0.2.0)

Der alte Dienst liegt als Referenz unter `alterCode/compendious`; sein README nennt ihn einen weitgehend
KI-generierten Proof of Concept. Er erzeugte nur das Weltwissen. Der Weg vom Thema zum Text
(`POST /api/v1/pipeline-compendium-only`):

1. **Begriffe:** Ein LLM-Aufruf nennt bis zu zehn Begriffe zum Thema, jeweils mit dem vermuteten exakten
   Wikipedia-Titel (`app/core/openai_wrapper.py`, Modus `generate`, Temperatur 0,7).
2. **Wikipedia:** Je Begriff fragt der Dienst die MediaWiki-API mit genau diesem Titel ab und holt nur den
   Einleitungsabschnitt als Klartext. Findet er nichts, probiert er bis zu acht Schreibvarianten und lässt ein LLM
   bis zu drei Synonyme vorschlagen. Die Begriffe laufen nacheinander (`app/services/wikipedia/`).
3. **Text:** Ein einziger LLM-Aufruf schreibt das ganze Kompendium: Ziel 6.000 Zeichen, höchstens 4.000
   Ausgabetokens, Temperatur 0,7 (`app/core/compendium.py`). Im Prompt stehen die Einleitungen, die 15 Aspekte des
   damaligen Kategorien-Templates als Liste von Überschriften und die Anweisung, mit „(1)“, „(2)“ auf die
   URL-Liste zu verweisen (`app/core/compendium_prompts.py`).

Die 15 Aspekte sind eine Empfehlung im Prompt. Das Modell hält sie meist ein (im Median 14,5 von 15 als
Überschrift), der Code prüft sie aber nicht, und es gibt keinen eigenen Schritt je Aspekt.

## Problemlagen

### Unzuverlässiger Wikipedia-Abruf

Am 23.09.2026 mit dem unveränderten alten Code nachgestellt:

- **Wikipedia weist den Dienst ab.** Sein Client meldet sich als `compendious-text-fastapi v0.2.0`, ohne
  Kontaktangabe. Wikipedia beantwortet seine Anfragen mit 403 und verweist auf die Robot-Policy; mit einer
  Kontaktadresse im User-Agent gehen dieselben Anfragen durch. Über `curl` kam auch der alte User-Agent durch,
  Wikimedia wertet also vermutlich Client und User-Agent zusammen aus. Im Lauf zu „Optik“ kamen auf 240 Anfragen
  240 Ablehnungen.
- **Abgelehnte Anfragen werden wiederholt statt gemeldet.** Der Client versucht auch ein 403 viermal mit wachsender
  Pause, obwohl sein eigener Kommentar das ausschließt. Der Lauf dauerte deshalb 374 s, davon rund fünf Minuten
  Warten.
- **Der Ausfall bleibt unsichtbar.** Der Dienst lieferte trotzdem eine normale Antwort (über HTTP ein 200) mit
  11.906 Zeichen Text ohne eine einzige Quelle. Darin stehen 15 Verweise „(1)“, das Literaturverzeichnis sagt
  „Keine Referenzen verfügbar“.
- **Titel werden geraten statt gesucht.** Die Artikelwahl hängt davon ab, dass das LLM exakte Titel trifft.
  Begriffsklärungsseiten erkennt der Dienst nicht: In drei von zehn Themen waren zusammen zehn der „Quellen“
  Begriffsklärungen. Bei „Optik“ bekam das Modell unter „Brechung“ den Text „Brechen … steht für: Erbrechen, …“.
  Über Ausweichtitel landete „Emblem (Literatur)“ beim Artikel *Symbol*, und zu „Barockliteratur“ fehlte der
  Hauptartikel selbst.

### Schwache Quellenbindung

Selbst wenn Wikipedia antwortet, bekommt das Modell nur die Einleitungen der gefundenen Artikel, im Median rund
12.200 Zeichen, und schreibt daraus einen Text von im Median 13.200 Zeichen. Über zehn Themen tragen 220 von 916
Sätzen (24 %) eine Quellenangabe, und nur 192 (21 %) werden vom zitierten Text nachweislich gestützt. Geprüft wurde
mit derselben Regel, die der neue Dienst für LLM-Text anwendet: Mindestens 20 % der Inhaltswörter eines Satzes
müssen im zitierten Text vorkommen. Die übrigen Sätze sind nicht belegt; woher ihr Inhalt stammt, lässt sich am
Text nicht prüfen. Die Verweise zeigen auf ganze Artikel-URLs, nicht auf eine Textstelle.

### Dauer und Kosten

Im besten Fall, also mit erreichbarem Wikipedia, brauchte der alte Dienst im Median 35 s (29 bis 62 s) und
7.900 Tokens (7.200 bis 11.000) je Kompendium. Gemessen wurde mit `gpt-4.1-mini`, das seine Beispielkonfiguration
nennt; das Standardmodell im Code, `deepseek-r1`, bietet die b-api nicht mehr an. Fast die ganze Zeit entfällt
auf das Warten auf das Modell, im Median 32 s. Seine Endpunktbeschreibung nennt 45 bis 90 s.

### Struktur und fehlende Bereiche

- keine festen Bausteine, keine maschinenlesbaren Abschnitte oder Facetten
- keine Lehrplanbezüge und kein Sammlungsüberblick; beides hätte eigene Quellen, Abfragen und Darstellungen
  gebraucht
- kein Weg, einzelne Abschnitte neu zu erzeugen oder redaktionell geprüfte Teile zu behalten

### Fehlerverhalten und Betrieb

- Fehler der Erzeugung kommen als Markdown in einer normalen Antwort zurück („# Fehler bei der Generierung …“).
- Der synchrone LLM-Client blockiert die Event-Loop des Servers.
- Die Tests ersetzen jeden LLM- und Wikipedia-Aufruf durch Attrappen; keiner prüft das echte Zusammenspiel.

## Was der neue Dienst dagegen setzt

| Problem | Lösung im neuen Dienst |
|---|---|
| Wikipedia sperrt, drosselt oder ist nicht erreichbar | Wikipedia und Klexikon liegen als ZIM-Archive beim Dienst; zur Anfragezeit gibt es keinen Wikipedia-Zugriff. Neue Archive holt ein Sidecar mit Prüfsumme und wechselt atomar. |
| LLM rät Titel; Begriffsklärungen und Fehlgriffe | Auflösung über den Index des Archivs: exakter Titel, Weiterleitung, erkannte Begriffsklärung, Titelvorschläge, Volltextsuche. Alternativen stehen in der Antwort. Wo die Regeln unsicher sind, entscheidet ein LLM (`article_choice=llm`, seit D37 Vorgabe, wo eines konfiguriert ist). |
| nur Einleitungen als Quelle | ganze Artikel, dazu verlinkte Unterartikel und derselbe Artikel aus Klexikon, bis 12 Artikel und 400 Absätze |
| Text großteils unbelegt, Verweise nicht prüfbar | Absätze werden wörtlich übernommen; jede Belegnummer führt zu Artikel, Abschnitt und Textstelle |
| 35 bis 374 s, rund 7.900 Tokens | 2 bis 3 s und 0 Tokens ohne LLM; ist eines konfiguriert, prüft es seit D37 die Artikelwahl (rund 1,7 s und 930 Tokens mehr); weitere LLM-Schalter nur auf Wunsch |
| Aspekte nur als Hinweis | Template SC26 mit 13 Bausteinen, Längenbudgets, Facetten, Prüfung der Regeln (Lint) |
| nur Weltwissen | Teil 2 Lehrplanbezüge, Teil 3 Sammlungsüberblick |
| Fehler in einer normalen Antwort | passende Statuscodes, `parts_status` je Teil, Request-ID in jeder Antwort, Prometheus-Metriken und Alarme |
| Tests nur mit Attrappen | 821 Tests (94 % Abdeckung, Stand 24.09.2026), Linux-CI, Rauchtest des fertigen Images |

## Messvergleich

Dieselben zehn Themen aus zehn Schulfächern, gemessen am 23.09.2026. Der alte Dienst lief unverändert über die
b-api, der neue auf dem Server im Standardmodus ohne Sprachmodell.

| | Alt, wie ausgeliefert | Alt, bester Fall | Neu, Standard |
|---|---|---|---|
| Themen | 1 (Optik) | 10 | 10 |
| Dauer | 374 s | Median 35 s (29–62 s) | Teil 1: Median 2,0 s (1,1–2,5 s) |
| Modellaufrufe | 12 | Median 3,5 (2–7) | 0 |
| Tokens | 4.926 | Median 7.913 | 0 |
| Wikipedia-Anfragen | 240, alle abgelehnt | Median 14, alle beantwortet | keine |
| Quellen | keine | Median 10 Einleitungen | Median 10,5 ganze Artikel |
| Begriffsklärungsseiten als Quelle | – | 10 (in 3 Themen) | 0 von 87 Quellen |
| Hauptartikel des Themas dabei | – | 9 von 10 | 10 von 10 |
| Sätze mit Quellenangabe | 0 (15 Verweise ins Leere) | 24 % | jeder Absatz belegt |
| Sätze durch ihre Quelle gestützt | 0 % | 21 % | 100 %: jeder Satz steht wörtlich im zitierten Absatz |
| Umfang | 11.906 Zeichen | Median 13.200 Zeichen | Median 7.600 Zeichen Bausteintext, 25.200 mit Akteuren, Quellen und Glossar |

„Bester Fall“ heißt: Nur über die Konfiguration steht eine Kontaktadresse im User-Agent, sodass Wikipedia antwortet.
Der alte Text ist länger, weil das Modell frei schreibt; der neue enthält nur, was die Quellen hergeben, und lässt
Bausteine ohne passenden Absatz weg. Zweimal dieselbe Anfrage an den neuen Dienst ergab in der Stichprobe
(Photosynthese) denselben Text.

### Mit den LLM-Schaltern für Artikelwahl und Zuordnung

Nach v2.0.0 kamen zwei Schalter hinzu. Ihre Zeit wurde am 24.09.2026 an 30 anderen Themen im Prozess auf dem
Entwicklungsrechner gemessen (M13), ihre Güte an den Goldsätzen (M9, M12). Mit der Tabelle oben, gemessen über HTTP
auf dem Server, ist die Dauer nur der Größenordnung nach vergleichbar.

| Teil 1 je Kompendium | Dauer | Tokens | Hauptartikel richtig, 94 Anfragen | Zuordnung, macro-F1 |
|---|---|---|---|---|
| nur Regeln (`article_choice=rule-based`, `hybrid_light`) | Median 1,35 s | 0 | 86 | 0,43 |
| `article_choice=llm`, Vorgabe, wo ein LLM konfiguriert ist (D37) | im Median 1,7 s mehr | Median 927 | 91 | 0,43 |
| `matcher=llm`, wählbar (D36, D38) | Median 12,0 s | im Mittel 29.400 | 86 | 0,72 und 0,69 |
| zum Vergleich: alter Dienst, bester Fall | Median 35 s | Median 7.913 | – | – |

Mit `matcher=llm` braucht der neue Dienst mehr Tokens als der alte, bleibt aber schneller, und jeder Satz bleibt
belegt. Beide Schalter zusammen wurden nicht gemessen; sie laufen nacheinander, Zeit und Tokens addieren sich also
ungefähr. Die Zeile `matcher=llm` lief mit den Regeln für die Artikelwahl.

## Funktionsumfang des neuen Dienstes

| Endpunkt | Zweck |
|---|---|
| `POST /api/v2/compendium` | Kompendium aus den Teilen 1 bis 3; Schalter für Satzauswahl und Umformulierung durch ein LLM, nach v2.0.0 auch für Artikelwahl (`article_choice`) und Zuordnung (`matcher`); Teile gezielt neu erzeugen, geprüfte Bausteine behalten |
| `POST /api/v2/knowledge` | Wissenstexte zum Thema ohne Template: die Artikel des Korpus mit ihren Abschnitten, gewählt wie beim Kompendium (`article_choice`) |
| `POST /api/v2/entities` | Begriffe in einem Text, mit dem passenden Artikel und seiner Einleitung verknüpft |
| `POST /api/v2/qa` | Frage-Antwort-Paare zu einem Text oder Thema in vier Stufen: Vorlagen, Satzanalyse, kleine Modelle im Image, LLM |
| `GET /api/v2/collections/{id}/overview` | Teil 3 allein |
| `GET /api/v2/lehrplan/status`, `/search` | Stand und Suche im Lehrplan-Cache |
| `/api/v2/templates` | Templates lesen; eigene anlegen und löschen (Admin-Token) |
| `/api/v2/matching/strategies`, `/compare` | Zuordnungsverfahren auflisten und auf einem Thema vergleichen, mit Gold-Metriken (Vergleich mit Admin-Token) |
| `/api/v2/zim/…` | Archive: Stand; Kiwix-Katalog und Aktualisierung mit Admin-Token |
| `/health`, `/ready`, `/metrics` | Betrieb und Überwachung |

**Weiterverwendet und verbessert:**

- **Entitätenerkennung als Ersatz für den KIDRA-Wikipedia-Linker.** Der alte Linker ließ ein LLM Begriffe nennen
  und schlug sie live bei Wikipedia nach. `POST /api/v2/entities` arbeitet ohne LLM und ohne Netz in zwei Schichten:
  Named-Entity-Erkennung mit spaCy (`de_core_news_md`) und ein Wörterbuch aus den Artikeltiteln der Archive.
  Begriffe, hinter denen nur eine Begriffsklärung steht, fallen heraus. Auf dem Server dauerte ein Beispielsatz
  0,07 bis 0,15 s.
- **Frage-Antwort-Paare.** Der alte Dienst ließ sie ein LLM schreiben. Der neue hat vier Stufen; die Modellstufe
  (deutscher T5-Fragegenerator und ein extraktives Antwortmodell im Image) lieferte in der Messung aus
  `docs/umbau.md` 94 % mangelfreie Paare bei rund 1 s je Paar, ganz ohne b-api.
- **Aus der Testapp** kamen der ZIM-Zugriff, die Segmentierung, die Ranker BM25, Zeichen-TF-IDF und Model2Vec, die
  extraktive Synthese und die Idee, jeden Satz gegen seine Quelle zu prüfen.
- **Entfallen** sind die alten Hilfsendpunkte für Textteilung, Synonyme und Übersetzung.
