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
| `TemplateManager.save()` und `.delete()` haben **keinen Aufrufweg** — weder API noch CLI (`compendium templates` listet nur) | Quelltext und `--help` |
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
Wortart aus dem spaCy-Modell, sobald es geladen ist. Bis dahin liefert `dictionary` viel und ungenau; wer
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
| U5 | `POST /api/v2/qa` mit `rule-based`, `models`, `llm`; `ml`-Profil im Bau | groß (torch, zwei Modelle) |
| U6 | Verwaltung: Template-Schreibwege, `ZIM_PATHS`-Warnung, `/health` je Modell | klein |

U1 bis U4 und U6 halten das Image bei 830 MB. Erst U5 bringt torch.

## Entscheidungen vom 2026-09-20

| Frage | Entscheidung |
|---|---|
| v1-Vertrag | **sofort ganz entfernen** — `app/api/v1/`, `MIGRATION.md`, die zugehörigen Tests |
| torch | **eigenes `ml`-Profil**; `base` bleibt bei 830 MB und kann QA per Vorlagen oder LLM |
| Wikidata | **optional, standardmäßig aus** — und, nach der Ergänzung vom selben Tag, **lokal statt live** |
| Netzzugriff zur Laufzeit | **keiner**: Alles muss offline gehen. Indizes und Modelle werden einmal erzeugt bzw. ins Image gebacken |
| spaCy-Modell | `de_core_news_md` als Standard, über eine Einstellung auf `lg` umstellbar |
