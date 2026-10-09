# Änderungsprotokoll

Neueste Version zuerst. Jedes Release nennt seine Entscheidungen (D-Nummern, beschrieben in [PLAN.md](PLAN.md),
Abschnitt 14) und Messungen (M-Nummern, [Messprotokoll](docs/entwicklung/05-messprotokoll.md)); was ein Betreiber beim
Update ändern muss, steht in [docs/betrieb.md](docs/betrieb.md#updates), Abschnitt „Updates“. Ab 2.0.0 zählen die
Versionen nach Semantic Versioning: eine neue Einstellung oder neues Verhalten in einer Minor-, eine Korrektur in einer
Patch-Version; einige frühe Patch-Versionen (2.2.2, 2.4.2, 2.6.1, 2.6.2) änderten auch Verhalten. Die Tags 0.1.0 bis
0.2.0 gehören zum Vorgängerdienst, dem alten Dienst im GitLab, und stehen nur kurz am Ende.

## Unveröffentlicht

- **Doku (M91):** Alle fünf Profile beim zehnfachen Bausteinbudget an neun Themen gemessen, Teil 1 und 2, blind
  bewertet: `best-coverage-generated` in jeder Note vorn, 5 s langsamer als `best-quality-generated`, 68 % Modellwissen.
  Die Entscheidungsvorlage beginnt mit einer Zusammenfassung zu Bausteinbudget, Quellen und Profil im Betrieb (Punkt 20)
  und zeigt die Grafiken `satzauswahl.svg`, `zusatzquellen_budget.svg` und `profiluebersicht_x10.svg`. Am Dienst ändert
  sich nichts.

## 2.20.0 – 2026-10-09

Die Satzauswahl der KI als Kästchen beim Profil der Prüfansicht (D103); dazu M89 und M90.

- **Neu (D103):** Die Prüfansicht hat direkt unter dem Profil das Kästchen „KI wählt die Sätze“ (`extraction=llm`).
  Es gilt für jedes Profil, im Vergleich für beide, und steht nicht mehr unter „Erweitert“; ohne KI auf dem Server
  ist es gesperrt. Am Dienst ändert sich nichts.
- **[Betrieb](docs/betrieb.md#updates):** Keine neue Einstellung.
- **Doku (M89, M90):** Die Satzauswahl der KI (`extraction=llm`) beim zehnfachen Bausteinbudget in `balanced` und
  `best-quality` an neun Themen und am Gold gemessen: kürzer, lesbarer, fehlerärmer, aber weniger nützlich, für rund
  31.000 bis 33.000 Tokens mehr; Entscheidungsvorlage Punkt 19. Wikibooks und Wikiversity bei ×1 und ×10 an 100
  Anfragen: ein Zwilling bei 6, dort bei ×10 eher besser; Nachtrag zu Punkt 16. Die Doku beschreibt genauer, was
  `extraction=llm` tut.

## 2.19.0 – 2026-10-09

Das Bausteinbudget mal zehn als einstellbare Vorgabe und 200.000 Tokens je Anfrage in den `best-quality`-Profilen
(D102, M86); dazu M87 und M88.

- **Neu (D102, M86):** `BLOCK_BUDGET_FACTOR` (Vorgabe 10, 1 bis 100) vervielfacht beim Zuschnitt der Zuordnung das
  Budget jedes Inhaltsbausteins, nach den Regeln wie nach dem LLM: die Absätze, die er behält (`max_chunks` der Vorlage,
  aufgerundet), und die Zeichen, ab denen er mit genug Absätzen schließt. Die Ziellänge des Schreibers bleibt die der
  Anfrage. In M86 stieg damit der Nutzen in jedem Profil (`llm-free` 1,5 auf 2,8, `balanced` 2,0 auf 4,3,
  `best-quality-generated` 3,8 auf 4,9), keine Anfrage dauerte länger, und die Precision am Gold blieb. Die wörtlichen
  Texte werden deutlich länger (`balanced` im Median 44.900 statt 11.100 Zeichen), die geschriebenen kaum; `1` stellt
  das Verhalten bis 2.18.2 her. `/qa` baut seinen Teil 1 weiter mit den Budgets der Vorlage.
- **Geändert (D102):** `LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY` hat die Vorgabe 200.000 statt 180.000. Am breitesten
  Thema, Demokratie, brauchte Teil 1 bei ×10 109.100 Tokens in `best-quality-generated` und 132.100 in
  `best-coverage-generated`, 47 und 38 % mehr als beim Budget der Vorlage.
- **[Betrieb](docs/betrieb.md#updates):** Eine neue Einstellung mit Vorgabe (`BLOCK_BUDGET_FACTOR`). Wer
  `LLM_MAX_TOKENS_PER_REQUEST_BEST_QUALITY` gesetzt hat, setzt 200000. Die Texte werden länger, die schreibenden Profile
  brauchen rund ein Drittel mehr Tokens.
- **Doku (M86):** Das Bausteinbudget mal 1, 2, 4 und 10 an vier Themen in `llm-free`, `balanced` und
  `best-quality-generated` gemessen, mit Zeit, Tokens, Text, blinden Noten und dem Gold der Zuordnung, dazu das Gold bis
  zur Sättigung (×1000), ein Urteil zu jedem gedruckten Absatz und jedem Beleg des Schreibers und die Grenze am
  breitesten Thema; Entscheidungsvorlage Punkt 17 mit den Grafiken `bausteinbudget.svg` (lineare Achse),
  `bausteinbudget_gold.svg` und `bausteinbudget_absaetze.svg`. Seite 04 nennt das eigene Budget der Lehrplanprüfung
  (D94) statt der 180.000 der Anfrage.
- **Doku (D101, M87):** Kein Vektorindex über die Absätze der Wikipedia; Umfang und Tempo der Einbettung geschätzt.
- **Doku (M88):** Wie oft ein Artikel, den die Frage N zu einem Thema nennt, eine andere Bedeutung hat (einer von 200),
  woher es kommt und was sechs Prüfungen an passenden Artikeln kosten; Entscheidungsvorlage Punkt 18. Am Dienst ändert
  sich nichts.

## 2.18.2 – 2026-10-09

Der Klexikon-Zwilling kommt nur noch über den exakten Titel (D100, M85); dazu die Quellen nach M84 (D99) und der
Plattenbedarf mit der Wikipedia-Ausgabe 2026-10.

- **Behoben (D100, M85):** Der Zwilling eines Themas aus einem weiteren Archiv, praktisch das Klexikon, kommt nur noch
  über den exakten Titel des Hauptartikels, eine Weiterleitung dieses Titels eingeschlossen, nicht mehr über dessen
  Aliasse. Über einen Alias kam oft eine andere Bedeutung, deren erster Absatz unter „Themendefinition“ stand: Flüsse
  bei „Elektrischer Strom“, Gefängniszellen bei „Zelle (Biologie)“. An den 59 Gold-Anfragen fielen die unpassenden
  Klexikon-Absätze von 12 auf 2 (`llm-free`) und von 13 und 10 auf 2 (`balanced`, zwei Läufe), an 35 zurückgehaltenen
  von 10 auf 2 und von 7 auf 1; vier passende Zwillinge (6 Absätze) fallen weg. Keine neue Einstellung.
- **Quellen (D99, M84):** Weitere deutsche Archive von Kiwix brachten keinen passenden Text; der Dienst bleibt bei
  Wikipedia und Klexikon. `config/zim_subscriptions.yaml` nennt `extended` (Wikibooks und Wikiversity) nicht empfohlen
  und die Größen mit der Wikipedia-Ausgabe 2026-10 (`standard` rund 18,7 GB, `extended` rund 22,8 GB).
- **Doku:** Mindestens 50 GB Platte statt 35 oder 45 GB, weil beim Update zwei Wikipedia-Ausgaben von je bis zu 18,6 GB
  nebeneinander liegen (installation.md, Übergabe, betrieb.md); Entscheidungsvorlage Punkt 16 mit den Grafiken
  `quellen_empfehlung.svg` und `kiwix_quellen.svg`.

## 2.18.1 – 2026-10-09

Die Befunde des Reviews der Routing-Anpassungen behoben (D98).

- **Behoben:** Eine 503 des Routers, die nur vorübergehend gescheiterte Versuche auflistet (429 oder 5xx des Providers),
  hielt alle Aufrufe eine Minute an, mit einem Modell ohne Chat in der Liste sogar zehn; der Dienst wiederholt sie jetzt
  wie jede 503, und zehn Minuten hält nur eine Liste aus lauter `NOT_ELIGIBLE`. Ein Stopp verkürzt keinen längeren mehr,
  auch ohne Routing, und ein verlängerter steht im Log. `B_API_MODEL=openai/gpt-6-luna` bekommt die Parameter von
  gpt-6-luna statt `max_tokens` und `temperature`. Eine b-api ohne Routing (404) sagt das in Modellprüfung und Grund des
  Stopps statt „nicht erreichbar“. Der Name des antwortenden Modells steht auf einer Zeile im Log, höchstens 32 Namen je
  Worker. Der Hinweis auf die Parameterfamilie kommt nur noch bei `unsupported_parameter`.
- **Neu:** `/health` nennt unter `components.llm.reason`, warum das LLM nicht verfügbar ist, auch nach einem Stopp zur
  Laufzeit; bisher stand dort nur `available: false`. Der Start warnt, wenn `B_API_ROUTE` als `provider/modell` ein
  Modell einer anderen Parameterfamilie nennt als `B_API_MODEL`.
- **[Betrieb](docs/betrieb.md#updates):** Keine neue Einstellung.
- **Doku:** README, docs/betrieb.md und die Übergabe beschreiben Wiederholung, Stopps, Rückweg und was `/health` bei
  Erfolg zeigt; M83 trägt die Zeiten der Antworten des Routers in den Rohdaten.

## 2.18.0 – 2026-10-09

Das Routing der b-api als Provider (D97); dazu die Messung aller Profile und Funktionen mit 2.17.0 (M82).

- **Neu:** `B_API_PROVIDER=router` fragt das Routing der b-api mit dem Namen einer Route, die vorab global oder für den
  Schlüssel angelegt wurde (`B_API_ROUTE`, ohne Eintrag eine Route, die wie `B_API_MODEL` heißt); `B_API_MODEL` nennt
  die Modellfamilie der Route und damit die Parameter. Die Modellprüfung sucht die Route, `/health` und das Frontmatter
  nennen sie, das Log sagt einmal je Modell, wer hinter der Route antwortet. Eine fehlende oder abgeschaltete Route und
  ein Modell ohne Preis oder ohne Chat halten die Aufrufe zehn Minuten mit dem Grund zurück, eine Route ohne freies
  Modell eine Minute, statt jede Frage einzeln scheitern zu lassen oder sie bei 503 bis zu dreimal zu versuchen; lehnt
  ein Modell der Route die Parameter ab, nennt die Warnung `B_API_MODEL`.
- **[Betrieb](docs/betrieb.md#updates):** Eine neue Einstellung, `B_API_ROUTE` (leer); ohne `B_API_PROVIDER=router`
  ändert sich nichts. `/health` nennt unter `components.llm` zusätzlich `route`.
- **Gemessen:** M83, der Dienst über eine eigene Route aus `gpt-6-luna` und `gpt-5.6-luna` als Reserve: praktisch
  dieselben Tokens wie direkt über `openai` (bis 1,3 % Abweichung), je Aufruf kein messbarer Aufschlag, die Reserve
  antwortet bei abgeschaltetem Hauptmodell. M82, Release 2.17.0 in allen Profilen und Funktionen nach Güte, Zeit und
  Tokens: Jede Funktion hält die Güte ihrer letzten Messung; ein Kompendium mit Teil 1 und 2 braucht im Median 2,6 / 4,6
  / 12,6 / 23,2 / 27,3 s und 0 / 314 / 59.335 / 63.117 / 87.225 Tokens (`llm-free` bis `best-coverage-generated`). Neue
  Messskripte für die Endpunkte, die Auswertung der KI-Fragen und den QA-Bogen; `mc_kompendium_profil.py` zählt das
  Modellwissen an den Markierungen im Markup, denn seit D76 steht der sichtbare Vermerk nur auf Wunsch im Text.
- **Doku:** die Entwicklungsdoku auf dem Stand 2.17.0 (Übersicht, Seiten 01, 07, 08 und 09, Grafiken, Messprotokoll
  und Ergebnisübersicht), im README die Werte der Profile und der KI-Schalter aus M82.

## 2.17.0 – 2026-10-09

Die Ergebniszeile des Kompendiums auch für die übrigen Endpunkte mit KI (D96; Nachtrag im
[Bericht](docs/audits/2026-10-08-logging.md)).

- **Neu:** `/qa`, `/entities`, `/knowledge` und die Lehrplansuche schreiben bei einer Anfrage, die ein LLM verlangte,
  die Zeile eines Kompendiums ohne Teile und Dauer: Profil, KI-Stufen, Aufrufe, Tokens, Rückfälle je Stufe und
  Ursache; eine WARNING, wenn Zeit oder Budget KI-Arbeit abschnitten oder das LLM fehlte. Die Rückfallzeile von `/qa`
  entfällt; ohne LLM schreiben diese Anfragen keine solche Zeile. Im JSON nennt das Feld `answer`, wofür eine
  Ergebniszeile steht, auch beim Kompendium.
- **Behoben (Logging):** Die Zeile eines Kompendiums zählt auch die Rückfälle der Trefferprüfung und der Frage nach den
  Artikeln eines Themas. Ein LLM, das fehlte, ist eine eigene Ursache (`unavailable`) statt eines Fehlers der b-api und
  macht die Zeile zur WARNING mit dem Grund, auch wo nur eine Stufe ihn nennt: Teil 2 mit `curriculum_check=llm`, wenn
  die Regeln den Artikel wählten.

## 2.16.0 – 2026-10-08

Die letzten Audit-Befunde und eine Prüfung des Loggings mit allen Befunden behoben (D95; M81;
[Bericht](docs/audits/2026-10-08-logging.md)).

- **Neu:** Jede Anfrage schreibt eine Zeile mit Methode, Pfad, Status, Dauer und Client, auch wenn der Aufrufer schon
  gegangen ist; eine Anfrage, die etwas erzeugt, nennt auch ihren Start. Proben, die antworten, schreiben keine; uvicorn
  schreibt keine eigene Zugriffszeile mehr.
- **Neu:** Jedes Kompendium schreibt eine Zeile mit Profil, Teilen, KI-Stufen, Aufrufen, Tokens, Rückfällen je Stufe und
  Ursache (Zeit, Budget, b-api, andere) und Dauer; eine WARNING, wenn Zeit oder Budget KI-Arbeit abschnitten oder das
  gewünschte LLM fehlte.
- **Neu:** Jeder Worker nennt beim Start Version, Revision und was er mitbringt; jede Updater-Schleife Job, Version und
  Revision. Jede Zeile nennt die Prozess-ID, im JSON als `pid`, und trägt dort die Felder ihres Ereignisses.
- **Geändert:** Das Log geht nach stderr; ein einmaliger Befehl druckt seinen Bericht weiter auf stdout. uvicorns
  Zeilen tragen auch im Format `text` Zeit, Logger und Anfrage-ID und bleiben unabhängig von `LOG_LEVEL` auf `INFO`;
  ein unbekanntes `LOG_LEVEL` hält den Start an, `WARN` gilt als `WARNING`.
- **Geändert:** Über der Treffergrenze der Lehrplansuche (20.000) kommen die Lehrpläne innerhalb einer Rolle reihum dran
  (Audit 2026-09-18, D-03); unterhalb bleibt jede Suche gleich (M81).
- **Behoben (Logging):** Der Schutzschalter der b-api meldet Öffnen, Probe und Wiederanlauf einmal statt jeden Aufruf,
  Wiederholungen mit ihrer Wartezeit. Ein unerwarteter Fehler steht einmal im Log, mit Typ und Meldung in der ersten
  Zeile und ohne doppelte Rahmen. Jede Antwort mit 5xx nennt ihre Ursache. Bei `DEBUG` schreibt httpcore keine
  Antwortköpfe mehr (das Sitzungs-Cookie des edu-sharing-Kontos stand darin). Unlesbare Materialtexte ergeben eine
  Zeile je Anfrage, ein unlesbarer Lehrplan-Cache eine je Datei, ein gescheiterter Statusabschnitt eine bei Beginn und
  Ende, ein gescheiterter QA-Aufruf eine statt drei. Fehlerseiten bleiben in einer Zeile, ein Transportfehler vor dem
  Ende der Frist geht nicht verloren, Fehler von libzim werden sichtbar. Die Updater melden Fehlschläge mit Namen und
  Ursache (erwartbare ohne Traceback), der ZIM-Sync einen Lauf mit Fehlern als WARNING mit dem nächsten Lauf, ein
  Download Start, Fortschritt und Ende; Sync- und Harvest-Anfragen über die API und abgelehnte Template-Schreibvorgänge
  stehen im Log. Ein Stopp während eines Harvests zählt nicht mehr als gescheiterter Harvest.
- **Abhängigkeiten:** `uvicorn` ohne das Extra `standard`, `uvloop` und `httptools` direkt erklärt; `watchfiles` und
  `websockets` sind nicht mehr im Image (Audit 2026-09-18, DEP-02).
- **Doku:** Abschnitt „Logs“ in docs/betrieb.md (was wo steht, wie man liest und filtert, vor einem Update sichern); die
  Messskripte sagen, wie man nachmisst (T-02); die Audits vom 18.09. und 27.09. nennen den Stand ihrer letzten Punkte.
- **[Betrieb](docs/betrieb.md#updates):** Keine neue Einstellung. Wer das Log über stdout auswertet statt über
  `docker compose logs`, liest jetzt stderr.
- **Gemessen:** M81, libzim unter paralleler Last (162 Anfragen zu 20 zugleich, kein Text anders als nacheinander) und
  die Treffergrenze von Teil 2.

## 2.15.0 – 2026-10-08

Offene Befunde der Audits behoben und ein Review aller Änderungen des Tages mit allen Befunden behoben (D94; M80).

- **Neu:** Die KI-Prüfung von Teil 2 rechnet aus einem eigenen Budget, `LLM_MAX_TOKENS_CURRICULUM_CHECK` (400.000 Tokens
  je Anfrage), neben dem der Anfrage: Lehrpläne weiterer Länder und Schularten nehmen Teil 1 nichts weg, und was das
  Budget nicht mehr prüft, bleibt nach den Regeln in Teil 2.
- **Neu:** `LOG_FORMAT=json` schreibt jedes Ereignis als ein JSON-Objekt je Zeile, auch die Zeilen von uvicorn und die
  Meldungen der Updater-Schleifen (Audit 2026-09-18, OPS-03).
- **Neu:** Ein Template trägt seine Version als `ETag`; `PUT` und `DELETE` mit `If-Match` gehen nur über diese Version
  (sonst 412), so überschreibt ein veralteter Entwurf keine neuere Bearbeitung (Audit 2026-10-03, F09). Die Version setzt
  der Dienst und zählt auch nach dem Löschen weiter.
- **Geändert:** `API_STOP_GRACE_PERIOD` hat die Vorgabe 630 s, genug für die 600 s einer Anfrage mit `academiccloud`.
- **Behoben (Review des Tages):** Eine komprimierte Antwort wird höchstens bis zu ihrer Grenze entpackt (gestapeltes
  gzip erreichte 558 MiB). Ein unerwarteter Fehler in Teil 2 oder 3 lässt Teil 1 stehen. Die Stichwörter einer Frage
  werden nur über ihren Titel nachgeschlagen, höchstens 50 (statt 1.462 Volltextsuchen bei einem langen Thema), und ihr
  Artikel gilt als unsicher. Eine abgeschnittene Antwort behält den fertigen Satz davor; die Zuordnung liest mehrere
  Angaben je Zeile und Tabellen; ein Aufruf, dessen Anfrage endete, während er auf einen Platz wartete, geht nicht mehr
  hinaus; die Knotenvorschau hält `REQUEST_TIMEOUT_S`; dazu Fehler in der Erkennung von JSON, Codezäunen, Sätzen und
  Cookie-Hinweisen.
- **Umbau:** Keine zwei Pakete von `app/` importieren einander (A-01), der Dienst wird in `app/wiring.py` gebaut (A-03),
  die Quellen schreiben ihr Markdown mit `app/markup` (A-04); Tests für die Fehlerpfade der Kommandozeile (T-03);
  dieses Protokoll und [CONTRIBUTING.md](CONTRIBUTING.md) (DOC-06).
- **[Betrieb](docs/betrieb.md#updates):** Zwei neue Einstellungen mit Vorgabe (`LLM_MAX_TOKENS_CURRICULUM_CHECK`,
  `LOG_FORMAT`), `API_STOP_GRACE_PERIOD` 630 s in der neuen `docker-compose.yml`. Eigene Skripte, die Module des Dienstes
  importieren, finden einige unter neuem Pfad (`app.locks`, `app.markup`, `app.prose`, `app.wiring`).
- **Gemessen, nicht gebaut:** die letzten Zahlen ohne Messung (Audit 2026-09-27, WA-02; M80). Die Schwelle der
  Zeichen-n-Gramme 0,1 und 16 gezählte Erwähnungen heben das Gold und werden erst blind beurteilt;
  `TOPIC_WORD_IN_TITLE` wirkt nie.

## 2.14.0 – 2026-10-08

Zeit, Tokens und kaputte Antworten des LLM (D93; M75 bis M79).

- **Neu:** Wie viele LLM-Aufrufe ein Worker zugleich stellt und wie lange eine Anfrage dauern darf, richtet sich nach
  dem Anbieter: `openai` 20 Aufrufe und 300 s, `academiccloud` 2 und 600 s (M75); `LLM_MAX_CONCURRENCY` und
  `REQUEST_TIMEOUT_S` überschreiben beide.
- **Neu:** Teil 2 und Teil 3 entstehen neben Teil 1; `audit.duration_ms` nennt die Dauer der ganzen Anfrage, die
  Schritte in `timings_ms` überlappen sich. Teil 1 und 2 teilen sich das Budget auch beim breitesten Thema ohne
  Rückfall (M79).
- **Neu:** Die KI-Zuordnung antwortet in Zeilen statt in JSON (Prompt `paragraph_assignment` Version 3, M77). Nach dem
  Bau braucht `best-quality` 15,1 statt 20,4 s, `best-quality-generated` 29,8 statt 33,9 s (M78).
- **Behoben:** Beim Schreiben gilt eine Antwort aus JSON nicht als Text, sondern als Rückfall mit Grund; eine Antwort,
  die das Ausgabelimit abschnitt, verliert den Satz, in dem sie abbrach (`audit.llm.generation.cut_off`).
- **Behoben:** Ein LLM-Aufruf wartet auf einen freien Platz so lange, wie seine Anfrage Zeit hat, und hat danach
  `LLM_TIMEOUT_S` für sich; ein Timeout nach langer Warteschlange sperrt die b-api im Worker nicht mehr.
- **[Betrieb](docs/betrieb.md#updates):** Keine neue Einstellung, aber neue Vorgaben je Anbieter (bisher 10 Aufrufe
  und 120 s); ein gesetzter Wert gilt weiter für jeden Anbieter. `API_STOP_GRACE_PERIOD` ist 330 s, mit
  `academiccloud` auf 630 s setzen und Aufrufer und Proxy länger warten lassen.
  `kompendium_http_request_duration_seconds` hat die Grenzen 300 und 600 s dazu; die Schwelle von
  `KompendiumSlowCompendia` (60 s) gilt für OpenAI.
- **Gemessen, nicht gebaut:** ein Deckel für die KI-Prüfung von Teil 2 (M76: jedes Element, das er strich, hatte die
  Note „passt“), kleinere Stapel der Zuordnung und eine längere Haltezeit des Caches (M75).

## 2.13.0 – 2026-10-08

Empfehlungen zum Audit vom 03.10. gemessen und, wo sie trugen, gebaut; Sammlungen im Themenbaum (D92; M71 bis M74).

- **Neu:** Gibt eine Sammlung das Thema (`node_id` oder `collection_id` ohne `topic`), liest der Dienst ihren Ort im
  Themenbaum: die Sammlungen darüber und, wo ein LLM ihn hört, Untersammlungen, erste Materialien und Nachbarn. Die
  KI-Artikelwahl und die Themenformulierung hören ihn, die Nachbarsammlungen als nicht gemeint (M71);
  `audit.topic_tree` nennt, was gelesen wurde.
- **Neu:** Ein inhaltsneutraler Titel wie „Grundlagen“ steht für die nächste sprechende Sammlung darüber; Überschrift
  und `topic` heißen dann „Grundlagen (Kernphysik)“ (M71).
- **Neu:** Ohne KI findet eine Frage ihren Artikel über ihre Stichwörter (M73: 43 bis 45 statt 22 bis 24 von 60 Fragen
  passend).
- **Behoben:** Antworten von edu-sharing liest der Dienst nur bis 32 MiB, die der b-api bis 16 MiB; eine größere gilt
  als Fehler (Audit vom 03.10., F12). Der Filter der Materialtexte erkennt Cookie-Hinweise auch mit dem Verb vor der
  Website (F08, M74); eine Knoten-ID mit einem Zeilenumbruch dahinter gilt nicht mehr als Knoten-ID.
- **[Betrieb](docs/betrieb.md#updates):** Keine neue Einstellung. Beim ersten Mal je Sammlung bis zu sechs
  Lesezugriffe mehr aufs Repository; die Cache-Schlüssel tragen Format 4, Einträge älterer Versionen liest der Dienst
  nicht mehr.
- **Gemessen, nicht gebaut:** eine Passungsprüfung der Artikel, die die Frage N nennt (F04, M72: 4 bis 5 von 277
  passen nicht), ein eigener Weg für Aspekt-Themen (M72), ein Filter wiederholter Absätze in Materialtexten (M74).

## 2.12.2 – 2026-10-04

Externes Audit vom 03.10.2026 (Stand 2.11.0) geprüft (D91; M67 bis M70; [Bericht](docs/audits/2026-10-03-audit.md)).

- **Behoben:** Ein Satz der Modellwissensprüfung zählt nur als geprüft, wenn die Antwort ihn behält, streicht oder
  berichtigt, sonst als `unchecked`; eine Prüfung ganz ohne Urteil gilt als Rückfall mit Grund (F06).
- **Behoben:** Teil 3 nennt den Grund, wenn eine Sammlungsliste am Seitenlimit, an einer doppelten Seite oder an einer
  nicht lesbaren Untersammlung endet, auch in `summary.incomplete_reasons` (F07).
- **Behoben:** Materialtexte verlieren Einwilligungstexte statt jeder Zeile mit „Cookie“ (F08, M68).
- **Behoben:** Eine Teilregeneration prüft den Alttext, bevor sie Archive oder LLM fragt, und lässt die KI Sätze nur
  für neue Bausteine wählen (F13). Die CI prüft mit `ruff check .` den ganzen Baum, wie dokumentiert (F16).
- **[Betrieb](docs/betrieb.md#updates):** Keine neue Einstellung. Die Sammlungslisten liegen unter einem neuen
  Cache-Schlüssel, die erste Anfrage je Sammlung liest sie neu. Eine Teilregeneration mit einem Altbaustein ohne Platz
  im Template antwortet 422 vor jedem LLM-Aufruf.
- **Gemessen, nicht gebaut:** Regeln für Verneinungen in der Belegprüfung (F01, M67: 0,3 % der belegten Sätze
  widersprechen ihrem Beleg), ein Anteil des Korpusdeckels für Nebenquellen (F02, M69), die Themenformulierung vor der
  Artikelwahl (F05, M70).

## 2.12.1 – 2026-10-04

Nachtrag zur Artikelwahl (D85).

- **Behoben:** Nennt die KI-Artikelwahl statt eines Kandidaten einen Titel, den das Archiv nicht als Artikel hat,
  gelten die Kandidaten ebenso als verworfen: Die Übersicht der Frage N nimmt den Platz, oder die Anfrage antwortet
  404. Live bei „Funktion“: jetzt *Funktion (Mathematik)* statt *Funktion (Objekt)*. Keine neue Einstellung.

## 2.12.0 – 2026-10-03

Formeln aus Wikipedia, Artikelwahl ohne passenden Kandidaten, offene Audit-Befunde (D84 bis D90; M61 bis M66).

- **Neu:** Formeln der Wikipedia-Artikel stehen als Text im Korpus, eine Formel auf eigener Zeile am Absatz davor
  („Das Gesetz lautet: …“); bisher verwarf der Parser sie (D84, M61: 99,6 % von 10.006 Formeln werden Text).
- **Geändert:** Sagt die KI-Artikelwahl, dass keiner der Kandidaten passt, fällt auch der Artikel der Regeln weg; die
  Übersicht der Frage N nimmt seinen Platz, oder die Anfrage antwortet 404 mit dem Rat, ein Fach anzugeben (D85, Audit
  vom 02.10., A01, M63).
- **Geändert:** Aus dem Audit vom 27.09.: eine Regel für die Stämme eines Themas (D87, KO-11, M66), drei Faktoren der
  Zuordnungsregeln gestrichen (D88, WA-02, M65), Themenauflösung und Korpusbau in `app/knowledge` (D90, AR-03, WA-01;
  Auflösung, Quellen und Absätze von 200 Themen vorher und nachher byteweise gleich).
- **Behoben:** Die Beispiele der Prüfansicht setzen nur, was ihr Titel nennt (U11).
- **[Betrieb](docs/betrieb.md#updates):** Keine neue Einstellung. Der Korpus von Artikeln mit Formeln wird größer (in
  80 Schulartikeln 5.770 statt 4.624 Absätze), der KI-Zuordner braucht dort mehr Tokens. In den Profilen mit LLM kann
  ein mehrdeutiges Einzelwort ohne Fach jetzt 404 geben.
- **Gemessen, nicht gebaut:** der KI-Zuordner ohne Denken (D86, M62: micro-F1 0,745 statt 0,788, je Anfrage 5,4 s
  schneller) und weitere Suchwörter für Teil 2 (D89, M64).

## 2.11.0 – 2026-10-03

Standardprofil `best-quality-generated` und Formeln des LLM als Text (D82, D83; M59, M60).

- **Neu:** Formeln, die das LLM in LaTeX schreibt, stehen als lesbarer Text mit Unicode im Kompendium
  („n₁ sin θ₁ = n₂ sin θ₂“) statt als Rohtext mit Backslashes (D83, M60).
- **Geändert:** Ohne Profil läuft eine Anfrage mit `best-quality-generated` statt `balanced`, solange ein LLM
  eingerichtet ist, ohne LLM weiter mit `llm-free`; die Prüfansicht wählt es vor (D82).
- **[Betrieb](docs/betrieb.md#updates):** Keine neue Einstellung, aber eine neue Vorgabe: Eine Anfrage ohne Profil
  braucht rund 37 s und 77.000 Tokens statt 4 s und 600 (M59). Wer das alte Verhalten will, setzt
  `PRESET_DEFAULT=balanced`.

## 2.10.0 – 2026-10-03

Teil 2 nach der KI-Prüfung, Denkaufwand je KI-Frage (D80, D81; M57 bis M59).

- **Geändert:** Mit der KI-Prüfung von Teil 2 (`curriculum_check=llm`, die `best-quality`-Profile) steht nur einzeln,
  was sie mit 2 bewertet; was sie mit 1 bewertet, zählt in der Bündelzeile seines Bereichs (D80).
- **Geändert:** Teil 2 und die Lehrplan-Suche im Themenmodus suchen ein Nebenwort eines Themas nicht, das im
  Lehrplan-Cache mehr als `LEHRPLAN_GENERIC_WORD_HITS` Elemente trifft; die Antwort nennt es unter `generic_keywords`
  (D80).
- **Geändert:** Fünf KI-Fragen stellt der Dienst ohne das Denken des Modells: Frage N, Artikelwahl, Lehrplanprüfung,
  Themenformulierung und QA-Paare; Schreiben, Zuordnung, `/entities` und die Artikelwahl eines Materials denken weiter
  (D81, M59). Die KI-Zuordnung liest 250 statt 400 Zeichen je Absatz.
- **[Betrieb](docs/betrieb.md#updates):** Zwei neue Einstellungen mit Vorgabe: `LEHRPLAN_GENERIC_WORD_HITS` (1000;
  `0` sucht jedes Wort) und `LLM_REASONING_EFFORTS` (die fünf Fragen mit `none`). `balanced` wird je Anfrage rund 2 s
  schneller, `best-quality` rund 8 s; wer alles wie bisher will, setzt `LLM_REASONING_EFFORTS=topic_articles=low`.

## 2.9.1 – 2026-10-03

Nachgang zum Audit vom 02.10.2026: Facette `Zugang`, drei Vorschläge gemessen (D79; M54 bis M56).

- **Behoben:** Die Facette `Zugang` steht bei jeder CC-Lizenz, auch mit NC oder ND, bei gemeinfreien Werken und bei
  „frei zugänglich (keine OER-Lizenz)“; `audit.lint` meldet `facet-required` nur noch für eine Quelle ohne bekannten
  Zugang (Sammlung Optik der Staging: eine statt 13 Quellen ohne Facette). Keine neue Einstellung.
- **Gemessen, nicht gebaut:** ein Link-Filter für die Artikel der Frage N (A02, M54), die Teile von N als Suchwörter
  für Teil 2 (A06, M55) und ein Teil 1 ohne Hauptartikel aus der Wissens-Sammlung (A05, M56); keiner der drei brachte
  eine Verbesserung.

## 2.9.0 – 2026-10-03

Audit vom 02.10.2026: sieben der elf Befunde behoben, A01, A02, A05 und A06 zur Entscheidung gestellt (D78).

- **Behoben:** Ein belegter Satz braucht jede Zahl, die er in Ziffern nennt, auch in seinem Beleg; sonst gilt er als
  ungestützt (A03).
- **Behoben:** Die Nebenartikel einer Stufe teilen sich, was `CORPUS_MAX_CHUNKS` lässt: Große Themen haben mehr Quellen
  im Korpus (Deutschland 9 statt 3), gleich viele Absätze (A04).
- **Behoben:** Quellen ohne freie Lizenz machen Teil 1 nicht mehr pauschal zu freien Inhalten unter CC BY-SA 4.0; der
  Quellenblock nennt sie (A09). Ein schreibendes Profil mit Rückfall in einzelnen Bausteinen nennt sie im Hinweis
  `topic-scope` (A10).
- **Behoben:** Materialtexte halten `KNOWLEDGE_MAX_CHARS` auch im ersten Absatz (A07), die ersten Lesezugriffe aufs
  Repository halten `REQUEST_TIMEOUT_S` (A08), ein unlesbarer Cache-Eintrag ist ein Fehltreffer (A11).
- **[Betrieb](docs/betrieb.md#updates):** Keine neue Einstellung. Hängt das Repository, endet eine Anfrage in der Frist
  statt nach bis zu drei mal zwei Versuchen à `EDU_SHARING_TIMEOUT_S`.

## 2.8.1 – 2026-10-02

Prüfansicht: Teil 3 nur mit Sammlung.

- **Behoben:** Teil 3 unter „Teile“ ist gesperrt und geht nicht in die Anfrage, bis eine Sammlung des
  Server-Repositorys erkannt ist; bisher ließ es sich ohne Sammlung ankreuzen und blieb dann ohne Hinweis leer
  (Nachtrag zu D77).

## 2.8.0 – 2026-10-02

Eine Sammlung, ein Feld (D77).

- **Neu:** Eine Sammlung des eingestellten Repositorys in `node_id` bekommt im Kompendium Teil 3 wie mit
  `collection_id`, wenn das Feld leer ist; bis dahin stand Teil 3 dann auf `unavailable`.
- **Neu:** Die Prüfansicht hat in allen Bereichen ein Feld „Sammlung oder Material“ statt dreier, liest den Knoten
  über `GET /api/v2/nodes/{id}` und sagt, wie er verwendet wird; bei einer Sammlung lassen sich ihre Materialien als
  Quelle zuschalten.
- **Geändert:** `parts: ["collection"]` mit einem Material in `node_id` ist ein 503 statt eines 422.
- **[Betrieb](docs/betrieb.md#updates):** Keine Einstellung in der `.env`, keine neue `docker-compose.yml`.

## 2.7.1 – 2026-10-02

Prüfansicht: Rückfall sichtbar.

- **Behoben:** Schrieben die Regeln ein Kompendium, für das das Profil die KI verlangt (etwa bei 502 der b-api), zeigt
  die Prüfansicht „ohne KI“ oder „teils ohne KI“ mit Grund statt der Profilbeschreibung; neben dem Formular steht, ob
  die KI erreichbar ist (`/ui/options.json` trägt die letzte Prüfung).

## 2.7.0 – 2026-10-02

Vermerk `[Modellwissen]` nur auf Wunsch (D76).

- **Neu:** `model_knowledge_label: true` in der Anfrage, die CLI-Option `--model-knowledge-label` und der Schalter
  „Vermerk [Modellwissen] im Text zeigen“ der Prüfansicht zeigen den Vermerk.
- **Geändert:** Sätze aus Modellwissen enden nicht mehr sichtbar mit `[Modellwissen]`, weder im Markdown noch im Text
  der Bausteine: So geht ein fertiger Text an Endkunden. Das Markup kennzeichnet sie weiter
  (`<!-- f: Evidenzgrad=Modellwissen -->`).
- **[Betrieb](docs/betrieb.md#updates):** Keine Einstellung in der `.env`, keine neue `docker-compose.yml`.

## 2.6.2 – 2026-10-02

Das angefragte Thema in jedem Profil als Überschrift (D75).

- **Geändert:** Überschrift, `topic` und `frontmatter.topic` nennen in jedem Profil das angefragte Thema, auch in
  `llm-free`, `balanced` und `best-quality`, die bisher den gedruckten Artikel nannten („Kompendium: Optik in Klasse 7“
  statt „Kompendium: Optik“). Den Artikel nennt `resolution.title`.

## 2.6.1 – 2026-10-02

Die Prüfung des Modellwissens in keinem Profil (D74).

- **Geändert:** `best-coverage-generated` prüft sein Modellwissen nicht mehr (in 2.6.0 eingeschaltet): rund 27.000
  Tokens und 5 s weniger je Kompendium (M53). Der Schalter `model_knowledge_check: llm` bleibt für Anfragen, die ihn
  setzen.

## 2.6.0 – 2026-10-02

Fünftes Profil, 30.000 Zeichen, das angefragte Thema in jedem Prompt, neue Vorgaben (D67 bis D73; M46 bis M53).

- **Neu:** Fünftes Profil `best-coverage-generated`: Das LLM schreibt jeden Baustein zum angefragten Thema, wo die
  Quellen nichts dazu sagen aus Modellwissen (`enrichment: model-knowledge-full`, D69, M47). Die Prompts
  `paragraph_assignment` und `section_coverage` tragen ihren gemeinsamen Teil in der System-Nachricht, die der
  Prompt-Cache des Anbieters hält; `audit.llm_tokens.cached` zeigt den Anteil (M46).
- **Neu:** In den schreibenden Profilen formuliert das LLM das Thema zuerst, wenn `topic` ein Text ist (mehr als sechs
  Wörter oder 60 Zeichen, ein Satz, eine Frage) oder ein Knoten ohne Thema kommt (Prompt `topic_wording`, D72).
- **Neu:** Schalter `model_knowledge_check` (`rule-based`, `llm`): Ein zweiter Aufruf je Baustein streicht oder
  berichtigt Sätze aus Modellwissen; in diesem Release in `best-coverage-generated` an (D73, M53).
- **Neu:** Wissens-Sammlung ohne Lizenzfilter; ohne `knowledge_fulltext: true` bringt ein Material nur seine
  Beschreibung mit, `knowledge_depth` (0 bis 5) liest Untersammlungen (D70).
- **Geändert:** Jedes Profil fragt Teil 1 mit 30.000 statt 12.000 Zeichen an; ein `target_length` der Anfrage geht vor
  (D70, M48).
- **Geändert:** Jeder Prompt hört das angefragte Thema statt des gefundenen Artikels. `best-quality-generated`
  schreibt darüber, füllt leere Bausteine aus Modellwissen und darf bis zur Hälfte eines Bausteins daraus schreiben;
  seine KI-Kennzeichnung (`ai_disclosure`) lautet wie die von `best-coverage-generated` (D70, D72, M51, M52).
- **Geändert:** Nach dem Review von D72 bleibt ein geschriebener Baustein ohne zitierten Beleg geschrieben, eine
  unlesbare Antwort der Zuordnung wird einmal neu gefragt, und `audit.lint` meldet `topic-scope`, wenn ein wörtlicher
  Text einen anderen Artikel behandelt (D73, M49).
- **[Betrieb](docs/betrieb.md#updates):** Neue Vorgaben: `LLM_DAILY_TOKEN_BUDGET` ist `0`, keine Tagesgrenze (bisher
  2.000.000, D67), und `.env.example` setzt `PRESET_DEFAULT=balanced` statt `llm-free` (D68); eine `.env` aus der
  alten Vorlage behält Grenze und `llm-free`. Ohne Budget und ohne `API_KEYS` kann jeder, der den Dienst erreicht,
  Tokens verbrauchen; der Start warnt. Eine Anfrage ohne `preset` läuft ohne LLM mit `llm-free` statt mit 503.
- **[Betrieb](docs/betrieb.md#updates):** Neu `B_API_RESPONSE_CACHE` (Vorgabe `false`): Die b-api beantwortet jeden
  LLM-Aufruf neu statt aus ihrem Speicher (D70). `docker-compose.yml` gibt der API 6 GiB statt 4 GiB (`API_MEMORY`),
  nach der Lastmessung der [Übergabe](docs/uebergabe/README.md).

## 2.5.0 – 2026-09-29

Befunde des Audits vom 29.09.2026 behoben (die Befund-IDs nennen die Commits); Lebenszeichen der Index-Sidecars.

- **Behoben:** Facettenmarker kodieren auch `%` und Anführungszeichen und lesen zurück, was sie schrieben. Eine
  Teilregeneration behält einen geprüften Baustein ganz; ein unbekannter Status oder ein Altbaustein ohne Platz im
  Template ist ein 422.
- **Behoben:** Eine Wiederholung reserviert ihren Prompt neu, eine unlesbare Antwort zählt wie ein Versuch, der das
  Modell erreichte, und ein am Ausgabelimit abgeschnittener Gedanke ist keine Antwort.
- **Behoben:** Ein Knoten wird über eine eigene Verbindung ohne Zugangsdaten und ohne Cookies gelesen; der
  Repository-Cache trennt seine Einträge nach Repository und Konto.
- **Behoben:** `GET /api/v2/lehrplan/search` und `GET /api/v2/nodes/{node_id}` antworten auf einen unbekannten
  Parameter mit 422; ein unlesbarer Körper ist ein 422 `json_invalid`, ein `topic` nur aus Leerraum ein 422 statt 404.
- **Behoben:** Die Prüfansicht setzt Hervorhebungen nach den Regeln von CommonMark und liefert ihre Dateien mit
  Inhalts-Tag (304, solange unverändert); `/docs` und `/redoc` kommen mit einer Content-Security-Policy.
- **[Betrieb](docs/betrieb.md#updates):** Wikidata- und GND-Updater schreiben ein Lebenszeichen, mit den Alarmen
  `KompendiumWikidataSyncSilent` und `KompendiumGndSyncSilent` (wirkt mit dem neuen Image beider Updater). Das Log beim
  Start warnt bei `UI_ENABLED` ohne `API_KEYS`, bei leerem `MODEL2VEC_PATH=` oder `SPACY_MODEL=`, mit LLM bei
  `REQUEST_TIMEOUT_S` bis 10 s und bei einem `LLM_REASONING_EFFORT` oder `LLM_VERBOSITY`, den die Modelle nicht kennen.
- **[Betrieb](docs/betrieb.md#updates):** Eigene Templates brauchen begrenzte Suchmuster in `heading_patterns`, ein
  `budget.weight` bis 100 und Facettennamen aus Wörtern; ein gespeichertes, das das verletzt, überspringt der Dienst
  beim Laden (Log „custom template … skipped“). Aufrufer, die eigene Query-Parameter anhängen (etwa `_=`), lassen sie
  weg.

## 2.4.2 – 2026-09-29

Markdown speichern; `/qa` meldet seine Tokens.

- **Neu:** „Markdown speichern“ in der Prüfansicht legt das Markdown eines Kompendiums unverändert als Datei ab, im
  Vergleich je Spalte (D66).
- **Neu:** `POST /api/v2/qa` meldet, was das LLM kostete (`llm_tokens`, in der Form von `audit.llm_tokens`); die
  Prüfansicht zeigt es wie bei den anderen Endpunkten.

## 2.4.1 – 2026-09-29

Prüfansicht nach ihrem Review (23 Befunde, D66).

- **Behoben:** Der Markdown-Leser braucht Zeit proportional zur Länge des Textes (ein präparierter Text von 60 KB
  vorher 5,8 s, jetzt unter 60 ms).
- **Behoben:** „Markdown kopieren“ geht auch über http; die Seite liest sich mit Screenreader, Tastatur und schmalem
  Fenster; Auswahllisten und Grenzen kommen aus `/ui/options.json`; Abbrechen eines Vergleichs behält fertige
  Antworten.
- **Behoben:** GitLab führt die Skript-Tests der Prüfansicht in einem eigenen Job aus (`ui-scripts`).

## 2.4.0 – 2026-09-29

Prüfansicht für Menschen, die die Texte prüfen (D66).

- **Neu:** Mit `UI_ENABLED` liefert der Dienst unter `/ui/` eine Seite, auf der Menschen die Antworten aller Endpunkte
  im Browser prüfen: Herkunft je Absatz, Qualität, Zeit und Kosten, zwei Profile im Vergleich, Markdown kopieren. Sie
  fragt die Endpunkte vom Browser aus mit dem Schlüssel ihres Lesers.
- **Neu:** Die Seite besteht nur aus Dateien, ohne Build-Schritt und Bibliothek: Ein eigener Markdown-Leser setzt
  jeden Text als Text, die Content-Security-Policy lässt nur die eigenen Dateien zu, und `/ui/options.json` liefert
  Auswahllisten, Grenzen und Beispiele aus den Modellen der Endpunkte.
- **[Betrieb](docs/betrieb.md#updates):** Neu `UI_ENABLED` (Vorgabe `false`); ohne Eintrag antwortet `/ui/` 404. Auf
  einem öffentlichen Server erst `API_KEYS` setzen, dann `UI_ENABLED=true`. `docker-compose.yml` bleibt, wie sie ist.

## 2.3.0 – 2026-09-28

Audit vom 28.09.2026 abgearbeitet (51 Befunde, [Stand je Befund](docs/audits/2026-09-28-audit.md); M45).

- **Geändert:** uv 0.12.19 an allen Stellen; GitLab-Images nennen ihren Commit und bestehen vor dem Push eine
  Startprobe.
- **Behoben:** Anfragen werden begrenzt, bevor sie Arbeit machen: Listen und Kennungen haben Obergrenzen, ein 422
  nennt höchstens 20 Fehler, Rate-Limit, Schlüssel und Admin-Token entscheiden vor dem Lesen des Körpers, uvicorn
  liest mit h11 (SE-15, SE-18, SE-19).
- **Behoben:** Text aus Quellen, Repository und MEM wird nach CommonMark maskiert; die Filterung der LLM-Sätze gilt für
  Bausteine und für die Paare von `/qa` (SE-16, SE-17).
- **Behoben:** Ein leerer Eintrag `NAME=` gilt wie keine Zeile, für jede Einstellung; bis 2.2.2 hielt etwa ein leeres
  `RATE_LIMIT=` alle fünf Container in einer Neustartschleife (BE-13).
- **Behoben:** Ein abgelöstes ZIM-Archiv geht nach `ZIM_RETENTION_HOURS`, vor einem Download räumt der Sync auf
  (BE-12); der Lehrplan-Harvest verweigert einen Verlust je Land und je Lehrplan, ohne MEM stündlich abzuziehen
  (KO-20, BE-11). ZIM- und Lehrplan-Updater geben ein Lebenszeichen, mit den Alarmen `KompendiumZimSyncSilent` und
  `KompendiumLehrplanHarvestSilent` (BE-15).
- **[Betrieb](docs/betrieb.md#updates):** Neu `REQUEST_BODY_MAX_BYTES` (Vorgabe 1.000.000 Byte, sonst 413; Kompendium
  und Templates nehmen bis 13.000.000), `UVICORN_HTTP` und `API_STOP_GRACE_PERIOD` (Vorgabe `150s`; wer
  `REQUEST_TIMEOUT_S` über 135 s setzt, setzt sie auf `REQUEST_TIMEOUT_S` plus 15 s).
- **[Betrieb](docs/betrieb.md#updates):** Eigene Templates brauchen Kennungen und Schlüssel nach Muster, höchstens 60
  Bausteine und Suchmuster ohne verschachtelte unbegrenzte Wiederholungen; ein gespeichertes, das das verletzt, wird
  beim Laden übersprungen: Log der API prüfen und das Template berichtigt neu speichern (AP-04).

## 2.2.2 – 2026-09-28

Mindestlänge für Token und Schlüssel.

- **Geändert:** `ADMIN_TOKEN`, `METRICS_TOKEN` und `API_KEYS` brauchen mindestens 16 statt 32 Zeichen; ein kürzerer
  Wert verhindert weiter den Start. Erzeugte, längere Werte (`openssl rand -hex 32`) bleiben die Empfehlung (Audit
  vom 27.09., SE-08).

## 2.2.1 – 2026-09-28

Leerer Eintrag `B_API_MODEL=`.

- **Behoben:** Ein leerer Eintrag `B_API_MODEL=` gilt als Vorgabe `gpt-6-luna`, wie ohne Eintrag; bis 2.2.0 lief der
  Dienst damit ohne LLM. Ein eingetragener Wert gilt weiter.

## 2.2.0 – 2026-09-28

Übrige Befunde des Audits vom 27.09.2026 abgearbeitet ([Stand je Befund](docs/audits/2026-09-27-audit.md); M44).

- **Geändert:** Ein Fehlermodell für alle Fehlerantworten, in OpenAPI beschrieben (AP-01); `service.py` ist in die
  Schritte der Erzeugung geteilt (AR-01); Bausteine eines Templates haben das Feld `role` (`definition`,
  `systematik`, `context`; AR-04).
- **Behoben:** Der b-api-Client hat eine Frist über alle Versuche, 429 und 5xx öffnen den Schutzschalter (KO-04,
  KO-05); jeder LLM-Aufruf zählt je Route (BE-04).
- **Behoben:** Kein Link, kein Bild und kein Markup aus Modellantworten oder MEM erreicht das Dokument (SE-04, SE-05);
  der Rate-Limiter hält eine begrenzte Zahl von Fenstern, IPv6 je /64 (SE-07).
- **Behoben:** Ein beschädigter lokaler Index antwortet nichts, und der Sync baut ihn neu (DB-01); `matcher=llm`
  versteht Bausteinschlüssel in jeder Schreibweise, doppelte Schlüssel eines Templates werden abgelehnt (KO-07).
- **[Betrieb](docs/betrieb.md#updates):** `docker-compose.yml` härtet die Dienste: keine Capabilities, bei der API ein
  nur lesbares Dateisystem außer Volumes und `/tmp`, Protokolle rotieren bei 10 MB, die API hat 4 GiB und 150 s für
  laufende Anfragen, die Sidecars bekommen keine Geheimnisse der `.env`. Wirkt erst mit der neuen Compose-Datei.
- **[Betrieb](docs/betrieb.md#updates):** Neue Alarme für den freien Platz der Volumes (`KompendiumVolumeFull`) und
  stehende Index-Sidecars (`KompendiumWikidataSyncStale`, `KompendiumGndSyncStale`).
- **[Betrieb](docs/betrieb.md#updates):** `:latest` von `f167a9f` bis vor `9c94d43` las sein Model2Vec-Modell nicht
  und ordnete ohne Embeddings zu; wer in dieser Zeit aktualisiert hat, braucht das neue Image. Die Releases 2.1.0 und
  2.2.0 sind nicht betroffen.

## 2.1.0 – 2026-09-28

Profile, LLM-Stufen, Knoten als Eingang, Kennungen für Entitäten, Zugriffsschutz (D34 bis D65; M1 bis M43).

- **Neu:** Profile (`preset`): `llm-free`, `balanced`, `best-quality` und `best-quality-generated` wählen die
  Verfahren; ohne `preset` gilt `PRESET_DEFAULT` (im Code `balanced`, in `.env.example` `llm-free`), ein Schalter der
  Anfrage geht vor, ein Profil mit LLM ist ohne eingerichtetes LLM ein 503 (D41, D53). Die `best-quality`-Profile
  rechnen mit 180.000 Tokens je Anfrage (D59).
- **Neu:** Das LLM ordnet Absätze zu (`matcher=llm`; D34, D36, D39), wählt den Artikel und prüft Volltexttreffer
  (`article_choice` `llm` und `llm-thorough`; D35, D37, D61) und nennt ab `balanced` Übersicht und Teile eines Themas
  (Frage N, D63).
- **Neu:** Ein Knoten eines edu-sharing-Repositorys als Eingang (`node_id`, `repository`) für Kompendium,
  `/knowledge`, `/qa` und `/entities`, dazu `GET /api/v2/nodes/{node_id}`; ein Material ohne Thema findet seinen
  Artikel über Regeln oder LLM (D45, D47).
- **Neu:** `/entities` nennt GND, Wikidata-Nummer und DBpedia-URI aus lokalen Daten und nimmt Profile; die Sidecars
  `wikidata-updater` und `gnd-updater` bauen die Indexe (D43, D46, D62, D64, D65).
- **Neu:** Teil 2 je Profil, mit KI-Prüfung der Lehrplanelemente in den `best-quality`-Profilen (D58); `/qa` wählt
  sein Verfahren nach dem Profil (D54, D55, D57, D60); Sätze aus Modellwissen tragen sichtbar `[Modellwissen]` (D56).
- **Geändert:** Vorgabemodell `gpt-6-luna` statt `gpt-5.6-luna` (D44, M19). Volltexttreffer ohne Link zum
  Hauptartikel fallen weg (D48). Unbekannte Felder sind ein 422, ein Fach wird gegen die Fachvokabulare von
  edu-sharing geprüft (D49, D51). Entfernt: `POST /api/v2/matching/compare` (D50) und die QA-Stufen `models` und
  `parse-based` samt torch, das Image hat 1,1 statt 2,74 GB (D57).
- **Behoben:** Die Texte der Materialien einer Wissens-Sammlung erreichen Teil 1; in 2.0.0 kamen nur ihre
  Kurzbeschreibungen an.
- **[Betrieb](docs/betrieb.md#updates):** Zwei neue Dienste in `docker-compose.yml`, `wikidata-updater` und
  `gnd-updater`; eine `.env` mit `B_API_MODEL=gpt-5.6-luna` aus einer alten Vorlage auf `gpt-6-luna` setzen.
  docs/betrieb.md hat seither den Abschnitt „Updates“.
- **[Betrieb](docs/betrieb.md#updates):** Neu `API_KEYS`, ein optionaler Schlüssel für alle Profil-Endpunkte; auf
  einem öffentlichen Server `API_KEYS` und `METRICS_TOKEN` setzen. Token und Schlüssel brauchen mindestens 32 Zeichen
  (ab 2.2.2: 16). `:latest` entsteht erst nach grüner CI, jeder Commit liegt auch als `:<sha>` bereit; `/health` nennt
  den Commit (Audit vom 27.09., SE-01, SE-08, BE-01, BE-03).
- **Gemessen, nicht gebaut:** laya-multilingual für Artikelwahl und Trefferprüfung (D42, M16), Wikibooks und
  Wikiversity als weitere Quellen (M11), kleine lokale Modelle für `llm-free` (M40).

## 2.0.0 – 2026-09-23

Erstes Release des Neubaus auf Kiwix-ZIM-Archiven, ohne LLM lauffähig (D1 bis D33; PLAN.md, Fassungen v1 bis v22).

- **Neu:** Teil 1 „Weltwissen“ aus lokalen Kiwix-ZIM-Archiven (Wikipedia, Klexikon, weitere über ein Abo-Manifest):
  Downloader mit Resume und SHA-256, `active.json` mit Wechsel ohne Neustart, Sync-Job im Sidecar `zim-updater`
  (D2, D6, D9).
- **Neu:** Zuordnung der Absätze zu den Bausteinen des Templates `sc26` mit Model2Vec im Image, Vertrauensschwelle 0,65
  und Abschnitts-Glättung (D20, D28); am Goldstandard macro-F1 0,45 und micro-F1 0,66, das Ziel 0,70 ist nicht
  erreicht (D21).
- **Neu:** Teil 2 „Lehrplanbezüge“ aus einem SQLite-Abzug aller MEM-Lehrpläne, den der Sidecar `lehrplan-updater`
  füllt; zur Inferenzzeit kein SPARQL (D5, D22, D23).
- **Neu:** Teil 3 „Die Sammlung im Überblick“ aus edu-sharing, je Knoten eine Zeile mit Art und nodeId, dazu die
  Wissens-Sammlung (`knowledge_collection_id`) als weitere Quelle für Teil 1 (D24).
- **Neu:** Optionale LLM-Schicht über die b-api: Schalter `extraction` und `generation`, `enrichment: model-knowledge`,
  Belegprüfung je Satz, Token-Budget und Rückfall auf die Regeln (D26, D27, D33).
- **Neu:** `POST /api/v2/compendium`, aus dem Umbau `POST /api/v2/knowledge`, `/entities` und `/qa` und Schreibwege
  für Templates; den Vertrag des alten Dienstes (v1) hat Umbau U1 wieder entfernt ([docs/umbau.md](docs/umbau.md)).
- **Neu:** Prometheus-Endpunkt `/metrics` mit getesteten Alarmregeln (D31), Request-IDs, Rate-Limit `RATE_LIMIT`
  (D30); Image auf GHCR, Installation auf Debian 13 ([docs/installation.md](docs/installation.md)) und
  Betriebshandbuch ([docs/betrieb.md](docs/betrieb.md)).
- **Behoben:** Befunde des Audits vom 18.09.2026 und zweier Review-Runden (D29, D30, D32;
  [Bericht mit Nachträgen](docs/audits/2026-09-18-audit.md)).

## Vorgängerdienst (0.1.0 bis 0.2.0)

Tags des alten Dienstes im GitLab, den dieser Neubau ablöst, mit Datum und Betreff des Tags (0.1.0 umschrieben).

- **0.2.0** – 2026-04-10: „Switch to B-API“
- **0.1.2** – 2025-08-19: „Merge branch 'increase_qa_pair_limits' into 'main'“
- **0.1.1** – 2025-08-14: „Merge branch 'develop' into 'main'“
- **0.1.0** – 2025-07-11: Zusammenführung eines Branches mit Korrekturen in „main“
