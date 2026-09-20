# Umbau: schlanke API, KI nur als Option

Vorschlag vom 2026-09-20, noch nicht umgesetzt. Ziel: ein Dienst, der **vollständig ohne generative KI**
arbeitet, daneben Entitäten und Frage-Antwort-Paare liefert, und bei dem ein LLM nur dort zugeschaltet wird,
wo der Aufrufer es ausdrücklich will — sichtbar in der Antwort. Der alte v1-Vertrag entfällt.

## Was geprüft wurde

| Befund | Beleg |
|---|---|
| 24 Endpunkte, davon 8 aus dem alten Vertrag | `/openapi.json` des laufenden Dienstes |
| **Die ZIM-Dumps führen keine Wikidata-IDs** — keine Q-Nummern, kein `wgWikibaseItemId`, keine DBpedia-Verweise | Artikel „Optik" aus `wikipedia_de_all_nopic_2026-01.zim`, 32.836 Zeichen HTML, null Treffer |
| Deutsche Modelle ohne generative KI existieren (siehe Tabelle unten) | Hugging-Face-API, 2026-09-20 |
| `TemplateManager.save()` und `.delete()` hatten **keinen Aufrufweg** — weder API noch CLI (`compendium templates` listete nur); mit U6 behoben | Quelltext und `--help` |
| ZIM-Verwaltung ist vollständig (Manifest, `active.json`, Sync-Sidecar, Admin-Endpunkte, Aufbewahrung) | `app/sources/zim/`, Endpunktliste |
| `ZIM_PATHS` umgeht `active.json` samt Wechsel ohne Neustart — als Entwicklungsweg gedacht, läuft aber auch produktiv (z. B. die lokale Einrichtung) | `app/main.py:build_registry` |

## Zielbild der Endpunkte

Aus 24 werden 17, und jeder hat genau eine Aufgabe.

| Neu | Ersetzt | Aufgabe |
|---|---|---|
| `POST /api/v2/compendium` | `/api/v1/compendium`, `/api/v1/pipeline*` | kompendialer Text, Teile 1–3 |
| `POST /api/v2/entities` | `/api/v1/linker`, `/api/v1/utils/synonyms` | Entitäten zu einer Eingabe, mit Artikelbezug (der Wikipedia-Linker) |
| `POST /api/v2/qa` | `/api/v1/qa` | Frage-Antwort-Paare zu einem Text oder Thema |
| `POST /api/v2/knowledge` | — (neu) | Wissenstexte zu einem Thema aus gewählten Archiven, ohne Kompendium |
| — | `/api/v1/utils/split` | Zerlegung ist ein internes Detail, kein Dienst |
| — | `/api/v1/utils/translate` | nur mit LLM sinnvoll; widerspricht dem Ziel |

Verwaltung bleibt, wo sie ist (`/api/v2/zim/*`, `/api/v2/lehrplan/*`, `/api/v2/templates*`, `/api/v2/matching/*`,
`/api/v2/collections/*`), bekommt aber die fehlenden Schreibwege (siehe „Verwaltung").

## 1. Entitäten (und der Linker)

**Zwei Schichten, die unabhängig voneinander ausfallen dürfen.** Der erste Entwurf hing an den Archiven: Er
las den Titelindex als Wörterbuch. Das ist nicht generisch — ohne das Wikipedia-ZIM findet er fast nichts, und
dieselbe Eingabe ergibt auf zwei Installationen verschiedene Entitäten. Erkennen und Verknüpfen gehören
deshalb getrennt.

### Schicht 1: Erkennen — ohne Archive, ohne Netz

| Verfahren | Was es findet | Hängt ab von |
|---|---|---|
| `ner` (Standard) | benannte Entitäten: Personen, Orte, Organisationen, Sonstiges — spaCy `de_core_news_md`, statistisch, kein torch | nur vom Modell im Image (35 MB spaCy + 44 MB Modell) |
| `dictionary` | Fachbegriffe und Themen, die einen Artikel haben — der Titelindex der Archive über `Archive.suggest()` | den geladenen Archiven |

Die beiden schließen einander nicht aus, sie ergänzen sich: NER liefert **Namen** (Ernst Abbe, Jena, Zeiss),
das Wörterbuch liefert **Begriffe** (Photosynthese, Brechungsindex) — und Begriffe sind in Lehrtexten meist
die interessanteren Entitäten. Jede Entität sagt in der Antwort, woher sie kommt (`source: "ner" | "dictionary"`).

**Ausfallverhalten:** Ohne Archive liefert `ner` weiterhin Entitäten, nur ohne Artikelbezug. Ohne
spaCy-Modell bleibt `dictionary`, und `/health` meldet das fehlende Modell — wie heute schon
`matching.components` die fehlenden Embeddings meldet. Der Endpunkt antwortet in beiden Fällen, statt
auszufallen.

**Gemessen am 2026-09-20 gegen die echte Wikipedia** (5.042.001 Artikel): 216 Wörter in 58 ms — das Tempo
trägt. Die Genauigkeit noch nicht: Von 20 gefundenen Begriffen eines Physik-Absatzes waren rund zehn echte
Entitäten (Brechungsindex, Hornhaut, Netzhaut, Lupe, Regenbogen), die übrigen Allerweltswörter mit eigenem
Artikel („Fach", „Thema", „Richtung", „Prinzip", „Schule", „Medien"). **Offener Punkt U3b:** Ein Filter dafür
braucht ein Kriterium, das nicht geraten ist — etwa Worthäufigkeit aus einer Frequenzliste oder die
Wortart aus dem spaCy-Modell, sobald es geladen ist.

**Nachgemessen am 2026-09-20: Die Wortart hilft hier nicht.** Ich hatte vermutet, ein Kriterium behebe die
Ungenauigkeit des Wörterbuchs und die schiefen Fragevorlagen in U5a zugleich. Die Messung mit
`de_core_news_md` im Image widerlegt das: „Fach“, „Thema“, „Richtung“,
„Prinzip“, „Schule“ und „Medien“ sind allesamt `NOUN` — genau wie die
echten Treffer „Brechungsindex“ und „Linse“. Die Wortart trägt an dieser Stelle kein
Signal, weil die Fehltreffer **echte Substantive** sind. **Und die Worthäufigkeit hilft auch nicht.** Zweite Messung am selben Tag, mit `Lexeme.rank` aus demselben
Modell (kein neues Paket nötig). Die Trennung sah zunächst hervorragend aus — Allerweltswörter 114 bis 1557,
Fachbegriffe 7927 bis 19685, unbekannte Wörter am Maximum. Dann die Gegenprobe mit Themenwörtern, und sie
verwirft den Ansatz: bei einer Schwelle von 6000 fielen **19 von 22** Themenwörtern weg — „Licht“ (973),
„Kraft“ (988), „Auge“ (1844), „Optik“ (3820), „Physik“ (5875) — dazu
„Berlin“ (307) und „Abbe“ (4687). Der Grund ist grundsätzlich, nicht eine Frage der Schwelle:
**Ein Lehrtext handelt von häufigen Begriffen.** Häufigkeit kann nicht zwischen „häufiges Füllwort“ und
„häufiger Gegenstand des Textes“ unterscheiden.

**Was stattdessen greift: der eigene Vertrag der Methode.** `dictionary` verspricht „Begriffe, die einen
Artikel haben“. Eine Begriffsklärungsseite ist kein Artikel. Gemessen gegen die echte Wikipedia sind 6 der
11 geprüften Fehltreffer Begriffsklärungsseiten (Fach, Thema, Medien, Bereich, Mittel, Weise) und **kein
einziger** der 10 echten Treffer. Anders als bei den beiden verworfenen Kriterien ist das Verlustrisiko damit
null. Der Filter nutzt den Parse, den das Verknüpfen ohnehin macht, kostet also nichts; `ner` bleibt unberührt,
weil das Erkennen kein Versprechen über Archive macht. Mit `link: false` findet keine Prüfung statt, und die
Antwort sagt es unter `note`.

Was der Filter **nicht** löst: „Richtung“, „Prinzip“, „Schule“, „Form“ und
„Grund“ haben echte Artikel und bleiben. Die andere Hälfte des Rauschens ist also **weiterhin offen** —
und beide naheliegenden Kriterien sind gemessen und erledigt. Wer heute Genauigkeit braucht, fragt `methods: ["ner"]`.

Bei den Fragevorlagen in U5a war die Wortart dagegen genau richtig, weil die Fehlgriffe dort **keine**
Substantive sind (Adverbien am Satzanfang); das ist behoben, siehe unten. Bis dahin liefert `dictionary` viel
und ungenau; wer
Genauigkeit braucht, fragt `methods: ["ner"]`. Zweiter Punkt derselben Art: Ein Begriff kann einen Eintrag
haben, der eine Begriffsklärungsseite ist („Brechung", „Carl Zeiss"). Das Wörterbuch findet ihn über den
Titel, die Verknüpfung lehnt ihn ab — die Entität kommt dann mit `linked: false` zurück, obwohl es etwas
gibt. Richtig wäre, die Alternativen der Begriffsklärung mitzugeben.

### Schicht 2: Verknüpfen — nutzt, was da ist

1. `ZimRegistry.resolve_topic()` bildet jede Entität auf einen Artikel ab (Titel, Weiterleitungen,
   Volltextsuche) und liefert Titel, Archiv-ID, Lead und Link.
2. `classify_entity()` aus `app/knowledge/entities.py` schärft die Art aus dem Lead: Person, Organisation,
   Projekt, Netzwerk, Werk.
3. Optional die Wikidata-QID aus dem lokalen Index (siehe unten).

Jede Entität trägt `linked: true|false`. Ohne passende Archive ist das Ergebnis also ärmer, aber nicht leer —
und die Antwort sagt, welche Archive befragt wurden.

4. **Verknüpfen mit Wikidata** (optional, ohne Netz): Die Dumps führen keine Q-Nummern (siehe Befund), also
   kommt die Zuordnung aus einem **lokalen Index**, einmal erzeugt und danach offline:

   | Weg | Was er leistet | Preis |
   |---|---|---|
   | `wikimapper` 0.2.0 | Wikipedia-Titel ↔ Wikidata-QID aus den Wikipedia-SQL-Dumps; SQLite im Zustandsvolume | Dumps einmal laden, Index bauen |
   | `spacy-entity-linker` 1.0.3 | Entitäten direkt auf Wikidata, eigene lokale Wissensbasis | rund 1,3 GB einmalig |
   | `Babelscape/wikineural-multilingual-ner` | NER auf Wikipedia trainiert, mehrsprachig, 675.000 Abrufe/Monat | braucht torch (`ml`-Profil) |

   Empfehlung: `wikimapper` — der Index wird wie die ZIM-Dumps gepflegt und hält den Dienst offline. Die
   DBpedia-URI lässt sich aus dem Titel bilden, ohne dass ihre Existenz geprüft wäre; sie wird nur auf Wunsch
   mitgegeben und als „konstruiert" gekennzeichnet.

   **Die Testapp (`../kompendium-test`) löst das anders:** Sie holt QIDs live über `pageprops` der
   Wikipedia-API und die Entitätsdaten von `wikidata.org/wiki/Special:EntityData/{qid}.json`
   (`kompendium/adapters/wikipedia.py`, `wikidata.py`). Die **Form** der Ausgabe (QID, Label, Beschreibung,
   URL, Kategorien) ist übernehmenswert, die **Quelle** nicht — sie widerspricht dem Offline-Ziel.

```
POST /api/v2/entities
{"text": "...", "methods": ["ner", "dictionary"], "link": true, "wikidata": false,
 "archives": ["wikipedia_de_all_nopic"]}
```

Die Antwort nennt `methods`, die befragten `archives` und je Entität `source`, `kind`, `linked` und —
falls verknüpft — Artikel, Lead und Link. Damit ist ablesbar, was aus dem Modell und was aus den Archiven kam.

## 2. Wissenstexte je Archiv

```
POST /api/v2/knowledge
{"topic": "Optik", "archives": ["wikipedia_de_all_nopic", "klexikon_de_all_maxi"], "max_chars": 20000}
```

Gibt die aufgelösten Artikel mit ihren Abschnitten zurück — kein Template, keine Bausteine, keine Synthese.
Das ist der Baustein, den ein anderer Dienst braucht, wenn er nur die Quelle will. Die Auswahl der Archive
beantwortet zugleich deine Frage nach „gezielt zu einem oder mehreren ZIM-Archiven".

## 3. Frage-Antwort-Paare in drei Stufen

| Stufe | Womit | Braucht |
|---|---|---|
| `rule-based` (Standard) | Fragevorlagen über die Sätze des Textes — das gibt es heute schon | nichts |
| `models` | **Fragen**: `dehio/german-qg-t5-quad` (MIT, T5, auf GermanQuAD trainiert). **Antworten**: `deepset/gelectra-base-germanquad` (MIT, extraktiv, 1.900 Abrufe/Monat) oder `-large` für mehr Güte | torch + transformers |
| `llm` | b-api, wie heute | b-api-Schlüssel |

Die Antwortmodelle sind **extraktiv**: Sie markieren die Stelle im Text, die die Frage beantwortet. Damit bleibt
auch diese Stufe belegbar — nichts wird erfunden.

### Wie U5b am 2026-09-20 gebaut wurde

**Der Fragengenerator ist antwortbewusst — das stand nicht im Entwurf oben.** `german-qg-t5-quad` liest keinen
Text und denkt sich Fragen aus; es bekommt einen Satz mit der gewünschten Antwort zwischen `<hl>`-Marken und
schreibt die Frage dazu. Die Antworten müssen also **zuerst** gewählt werden. Sie kommen aus den Nominalphrasen,
die spaCy findet (`doc.noun_chunks`, auf Deutsch unterstützt, gemessen 15 brauchbare Kandidaten in vier Sätzen)
— wonach eine Verständnisfrage fragt, ist fast immer eine Nominalphrase.

**Der Antwortkontext ist der eigene Satz, nicht der ganze Text.** A/B im Image: Mit dem ganzen Text wurde aus
„Was ist das beste Medium, um Licht zu brechen?“ die Antwort „Die Optik“ (aus einem anderen
Satz), mit dem eigenen Satz „Der Brechungsindex eines Mediums“. Richtiger **und** schneller (6,8 s statt
9,3 s für fünf Paare). Die Frage entstand aus genau diesem Satz; der ganze Text lädt das Modell nur ein,
woanders zu suchen. Der `context`-Parameter ist damit widerlegt und wieder entfernt.

**Gemessen im Image** (CPU): Modelle laden 7,9 s, danach rund 2,2 s je Paar. Die Modelle werden erst bei der
ersten Anfrage geladen, die sie braucht — 1,3 GB je Worker sollen nicht in jedem Dienst liegen, der die Stufe
nie anfragt. Qualität gemischt: „Welche Bedeutung hat der Brechungsindex?“ ist gut,
„Zu welcher Physik gehört die Optik?“ ist schiefes Deutsch. Das ist die Güte eines kleinen Modells; die
Antworten bleiben in jedem Fall Textstellen.

**Nachtrag am selben Tag: Die Antworten waren keine Textstellen.** Bei einer Live-Probe fiel
„Die Optik ( von altgriechisch optikós ) ist ...“ auf. Erste Vermutung: Artefakte in der
ZIM-Extraktion. **Falsch** — gemessen an fünf echten Artikeln (290.000 Zeichen) enthält der extrahierte
Text 0 bis 1 Artefakt. Die Ursache lag im eigenen Code: `tokenizer.decode(token_ids)` gibt keine Textstelle
zurück, sondern eine Rekonstruktion — Zeichen außerhalb des Modellvokabulars (hier das Griechische)
verschwinden, und die Wortabstände werden neu gesetzt. Behoben über `return_offsets_mapping`: die
Antwort wird jetzt per Zeichenbereich aus dem Quelltext geschnitten. Gegenprobe im Image: von drei Fragen
waren mit dem alten Weg **zwei Antworten keine Textstellen**, mit dem neuen alle drei. Der Rauchtest
prüft das jetzt („every answer a span of the text“) mit einem Text, der absichtlich
Griechisch enthält. Die Auswahl des Bereichs liegt als reine Funktion `answer_span` im Modul, weil der
Fehler ausgerechnet im untestbaren Teil des ersten Entwurfs steckte.

**Image 3,4 GB, gemessen** (Schätzung war 2,5–3 GB, sie rechnete mit Radgrößen statt entpackten): torch 769 MB,
QG-Modell 853 MB, QA-Modell 418 MB, Embedding-Modell 322 MB, transformers 114 MB. **Offen:** Das QG-Modell
liegt als fp32-`.bin` vor; safetensors in fp16 wären rund 430 MB, das ändert aber das Modell und müsste
nachgemessen werden.

### Wie U5a am 2026-09-20 gebaut wurde

**`app/synthesis/qa.py` hatte seit U1 keinen Aufrufweg mehr** — der v1-Endpunkt war weg, die Tests mit ihm.
U5a belebt das Modul wieder, statt Neues zu schreiben, und gibt ihm seine Tests zurück (12 Einheitentests).

**`models` steht nicht im Schema.** Ein Aufzählungswert, der nie funktionieren kann, ist schlimmer als ein
fehlender; U5b fügt ihn hinzu. Einen Wert zu ergänzen bricht keinen Aufrufer.

**Die Stufenverteilung (`level_property`, `level_values`) bleibt ungenutzt.** Gemessen am 2026-09-20:
`_level()` bildet über Teilstrings ab und setzt sonst stillschweigend die **erste** angebotene Stufe — aus
„Sekundarstufe II“ wird „Primar“. Das ist ein falsches Etikett, kein fehlendes.
Der Endpunkt bietet Stufen deshalb nicht an; wer sie braucht, braucht zuerst eine Abbildung, die scheitern
darf. **Offener Punkt.**

**Gemessen gegen die echten Archive** (Wikipedia 5 Mio. Artikel + Klexikon): „Optik“ HTTP 200 in
0,38 s, „Photosynthese“ in 0,88 s, je 50.000 Zeichen Quelltext, unbekanntes Thema 404. Die
Geschwindigkeit trägt. Die Fragequalität der Vorlagen nicht: Deutsch schreibt am Satzanfang groß, also griff
„Großbuchstabe + ist/sind“ auf jedes satzanfängliche Adverb — es entstanden „Was versteht man
unter Daneben?“, „… unter Beispielsweise?“ und „Wozu dienen Als Reduktionsmittel?“.

**Behoben mit der Wortart, gemessen statt geraten.** Getaggt mit `de_core_news_md` im Image begann jeder
falsche Betreff mit `ADV` oder `ADP`, jeder richtige trug ein `NOUN` oder `PROPN` — bei allen acht Fällen des
Live-Laufs, und die Prüfung des Betreffs allein (ohne Satzkontext) reichte bei allen zwölf Proben. Die Regel
lautet deshalb: Der Betreff darf nicht mit `ADV`/`ADP` beginnen und muss ein `NOUN`/`PROPN` enthalten. Ohne
geladenes Modell bleibt es beim alten Verhalten, und die Antwort sagt es unter `note` — eine stille
Qualitätsabhängigkeit von einem optionalen Modell wäre schlimmer als eine genannte. Der Rauchtest prüft es
im Image, weil nur dort das echte Modell läuft.

**Gegenprobe gegen die echten Archive nach der Behebung:** „Optik“ liefert jetzt „Was versteht
man unter Auge?“ und drei Jahreszahlfragen, „Photosynthese“ „Was versteht man unter
Photosynthese?“ und drei Jahreszahlen; kein Betreff ist mehr ein Adverb. **Beobachtung, nicht behoben:**
Weil die Definitionsvorlage seltener greift, überwiegen jetzt Jahreszahlfragen. Die sind sachlich richtig,
aber eintönig — eine Mischungsregel wäre eine eigene Entscheidung und steht nicht in diesem Schritt.

## 4. Kompendium: die zwei KI-Optionen

| Option | Feld | Was das Modell tut | Wortlaut |
|---|---|---|---|
| **A — semantisches Routing** | `extraction: llm` | wählt je Baustein aus den Kandidaten die passenden Sätze | bleibt der Quelle |
| **B — Veredlung** | `generation: llm` (oder `llm-fast`) | formuliert die Bausteine aus den Belegen | neu formuliert, **jeder Satz belegt** |
| **B+ — Veredlung mit Modellwissen** | `generation: llm` **plus** `enrichment: model-knowledge` | darf über die Quellen hinaus ergänzen | neu, teils unbelegt |

`enrichment` ist neu und steht standardmäßig auf `sources-only`. Nur mit `model-knowledge` darf das Modell
eigenes Wissen einbringen — und dann gilt:

- Der Prompt verlangt, ergänzte Sätze zu kennzeichnen.
- Die Belegprüfung streicht sie nicht mehr, sondern markiert sie im Text.
- Die Antwort sagt es: `enrichment: "model-knowledge"`, je Baustein die Zahl der ergänzten Sätze, und im
  Frontmatter ein Hinweis. Ein Leser sieht damit, welcher Teil aus den Archiven stammt und welcher aus dem
  Modell.

**Nebenläufigkeit**: `LLM_MAX_CONCURRENCY` steigt von 4 auf **10**. Die Aufrufe je Baustein laufen bereits
parallel; die Grenze war nur konservativ gesetzt.

### Wie U4 am 2026-09-20 gebaut wurde

Zwei Abweichungen vom Entwurf oben, beide mit Grund:

**Kein Prompt v3, sondern ein zweiter Prompt.** Der bestehende `section_synthesis@v2` ändert sich nicht — eine
Versionserhöhung ohne Textänderung wäre falsche Herkunftsangabe. Die Veredlung bekommt `section_enrichment@v1`.
Damit steht im Frontmatter unter `llm.prompts`, welcher der beiden einen Baustein geschrieben hat, statt nur,
dass sich ein Prompt geändert hat.

**Kein zweiter Kennzeichnungsweg.** Den gab es schon: `LLM_UNSUPPORTED_SENTENCES=mark` hält Sätze ohne Deckung
als `<!-- f: Evidenzgrad=Schlussfolgerung -->` … `<!-- /f -->` im Text. U4 macht aus dem Ja/Nein einen **Grad**:
`Schlussfolgerung` wie bisher, `Modellwissen` unter Veredlung. Gezählt wird weiter in `marked_sentences`; was die
Zahl bedeutet, sagt `enrichment` daneben.

Eine Festlegung, die der Entwurf offen ließ: **Ein Baustein braucht weiterhin mindestens einen belegten Satz.**
Ein Baustein ganz aus Modellwissen wäre kein Kompendiumsbaustein mehr; er fällt auf den extraktiven Text zurück
und steht mit Grund in `audit.llm.generation.fallbacks`.

**Kennzeichnung folgt dem Text, nicht der Erlaubnis.** Bei der Selbstprüfung gefunden: Wer `model-knowledge`
erlaubt bekommt, aber in den Quellen bleibt, hätte eine KI-Kennzeichnung mit „ergänzt um Modellwissen“
bekommen, obwohl nichts ergänzt wurde — eine Falschaussage in genau dem Feld, das nach Art. 50 stimmen muss.
`ai_disclosure` und der erklärende Frontmatter-Hinweis hängen jetzt an der Zahl der gekennzeichneten Sätze;
`enrichment` selbst bleibt der gewährte Modus.

**Nicht gemessen:** Wie oft ein Modell die Regel „höchstens jeder dritte Satz aus eigenem Wissen“ einhält, ist
offen — das braucht einen Lauf gegen die echte b-api und kostet Tokens.

## 5. Verwaltung

- **Templates**: `PUT /api/v2/templates/{id}` und `DELETE /api/v2/templates/{id}` hinter `ADMIN_TOKEN`. Der
  Manager kann es längst, es fehlt nur der Weg. Dazu `compendium templates save|delete` in der CLI.
- **ZIM**: bleibt. Ergänzt um eine Warnung beim Start, wenn `ZIM_PATHS` gesetzt ist — dann gibt es keinen
  Wechsel ohne Neustart und keine Verwaltung durch den Sync-Job.
- **Modelle** (spaCy, QA): wie das Embedding-Modell zur Bauzeit ins Image, mit festgelegter Revision; `/health`
  meldet je Modell, ob es geladen ist — wie jetzt schon `matching.components`.

### Wie U6 am 2026-09-20 gebaut wurde

**Der dritte Punkt war schon erledigt.** `/health` meldet seit U3 je Modell, ob es geladen ist:
`matching.embeddings` für Model2Vec, `entities.ner` für spaCy. Das sind die beiden Modelle, die das
`base`-Image hat; die QA-Modelle kommen erst mit U5 und bringen ihren Eintrag dann mit. Hier war nichts
zu bauen, nur nachzusehen.

**Die CLI behält ihren alten Befehl.** `compendium templates` listet weiter ohne Verb; `save` und `delete`
kommen als optionale Unterbefehle dazu. Der Weg über `add_subparsers(required=True)` wie bei `zim` hätte
eine bestehende Gewohnheit gebrochen, ohne etwas zu gewinnen.

**Die id steht im Pfad und im Body** und muss übereinstimmen (422). Den Body stillschweigend auf die
Pfad-id umzuschreiben wäre bequemer, würde aber ein Template irgendwohin legen, wo der Aufrufer es nicht
haben wollte.

**Eingebaute Templates antworten 409**, nicht 403: Es fehlt kein Recht, das Ziel ist schreibgeschützt. Die
Meldung des Managers sagt, was stattdessen geht (unter neuer id kopieren).

## Image-Profile

| Profil | Inhalt | Größe | kann |
|---|---|---|---|
| `base` | Python, libzim, numpy, scikit-learn, Model2Vec, **spaCy + `de_core_news_md`** | 830 MB heute, rund 950–980 MB mit spaCy (35 MB Rad, 44 MB Modell, dazu thinc und Kleinteile) | Kompendium, Entitäten, QA `rule-based` |
| `ml` | dazu torch, transformers, QG- und QA-Modell | geschätzt 2,5–3 GB | zusätzlich QA `models` |

spaCy braucht kein torch und passt deshalb in `base`. Die QA-Modelle brauchen torch — das ist die eine
Entscheidung, die das Image wirklich schwer macht.

## Phasen

| Phase | Inhalt | Aufwand |
|---|---|---|
| U1 ✓ | v1 entfernt (8 Endpunkte, `app/api/v1/`, `MIGRATION.md`, Tests) — erledigt am 2026-09-20 | klein, viel Löschung |
| U2 ✓ | `POST /api/v2/knowledge` — erledigt am 2026-09-20; `ZimRegistry.only()` grenzt auf Archive ein | klein |
| U3 ✓ | `POST /api/v2/entities` mit spaCy und Auflösung — erledigt am 2026-09-20; Wikidata bleibt offen | mittel |
| U4 ✓ | `enrichment: model-knowledge` samt Kennzeichnung, Bericht und eigenem Prompt; Nebenläufigkeit 10 — erledigt am 2026-09-20 | mittel |
| U5a ✓ | `POST /api/v2/qa` mit `rule-based` und `llm` — erledigt am 2026-09-20; kein neues Gewicht, kein zweites Image | mittel |
| U5b ✓ | Stufe `models` (QG- und QA-Modell), torch im Basis-Image statt eines zweiten Profils — erledigt am 2026-09-20 | groß (torch, zwei Modelle) |
| U6 ✓ | Verwaltung: Template-Schreibwege, `ZIM_PATHS`-Warnung — erledigt am 2026-09-20; `/health` je Modell war mit U3 schon da | klein |

U1 bis U4 und U6 halten das Image bei 830 MB. Erst U5 bringt torch.

## Entscheidungen vom 2026-09-20

| Frage | Entscheidung |
|---|---|
| v1-Vertrag | **sofort ganz entfernen** — `app/api/v1/`, `MIGRATION.md`, die zugehörigen Tests |
| torch | ~~eigenes `ml`-Profil~~ → **am 2026-09-20 umentschieden: ein einziges Image**. Zwei Images hätten zwei CI-Bauten und je Deployment eine Wahl bedeutet; der Betrieb wiegt schwerer als die 2,3 GB. Das Image läuft **rein auf CPU** (belegt: `torch 2.14.0+cpu`, CUDA nicht einkompiliert, kein NVIDIA-Paket) |
| Wikidata | **optional, standardmäßig aus** — und, nach der Ergänzung vom selben Tag, **lokal statt live** |
| Netzzugriff zur Laufzeit | **keiner**: Alles muss offline gehen. Indizes und Modelle werden einmal erzeugt bzw. ins Image gebacken |
| spaCy-Modell | `de_core_news_md` als Standard, über eine Einstellung auf `lg` umstellbar |
