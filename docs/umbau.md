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

Ein Endpunkt, vier Stufen — jede für sich abschaltbar. Die ersten drei nutzen Technik, die es im Dienst
schon gibt:

1. **Erkennen — mit dem, was schon da ist.** Der Titelindex der Archive ist ein Wörterbuch: `Archive.suggest()`
   (libzim-Titelsuche) sagt zu jeder Zeichenkette, ob es einen Artikel dieses Namens gibt. Also aus dem
   Eingabetext Wortgruppen bilden (ein bis vier Wörter), jede gegen den Index halten, den längsten Treffer
   nehmen. Das braucht **kein Modell**, keine zusätzliche Abhängigkeit und arbeitet offline — und es findet
   genau die Entitäten, die sich anschließend auch belegen lassen.
2. **Auflösen** (ohne Netz): `ZimRegistry.resolve_topic()` — dieselbe Auflösung, die heute das Thema eines
   Kompendiums findet: Titel, Weiterleitungen, Volltextsuche, Zwilling im zweiten Archiv. Liefert Titel,
   Archiv-ID, Lead und Link.
3. **Einordnen** (ohne Netz): `classify_entity()` aus `app/knowledge/entities.py` bestimmt aus dem Lead, ob ein
   Artikel eine Person, eine Organisation, ein Projekt, ein Netzwerk oder ein Werk ist. Das ist die
   Entitätsart — heute schon im Einsatz für den Baustein Akteure und für die Matching-Policy.

   **spaCy wird damit optional.** Es hilft nur noch bei Namen, die in keinem Archiv stehen (dann gibt es
   ohnehin keinen Beleg) und beim Aussieben von Wortgruppen, die zufällig einen Artikeltitel treffen. Erster
   Schritt also ohne Modell; spaCy `de_core_news_md` (45 MB, kein torch) kommt nur dazu, wenn die Messung zeigt,
   dass das Wörterbuch zu grob ist.
4. **Verknüpfen** (optional, ohne Netz): Die Dumps führen keine Q-Nummern (siehe Befund), also kommt die
   Zuordnung aus einem **lokalen Index**, einmal erzeugt und danach offline:

   | Weg | Was er leistet | Preis |
   |---|---|---|
   | `wikimapper` 0.2.0 | Wikipedia-Titel ↔ Wikidata-QID aus den Wikipedia-SQL-Dumps; SQLite im Zustandsvolume | Dumps einmal laden, Index bauen |
   | `spacy-entity-linker` 1.0.3 | Entitäten direkt auf Wikidata, eigene lokale Wissensbasis | rund 1,3 GB einmalig |
   | `Babelscape/wikineural-multilingual-ner` | NER auf Wikipedia trainiert, mehrsprachig, 675.000 Abrufe/Monat | braucht torch (`ml`-Profil) |

   Empfehlung: `wikimapper` — der Index passt zum Archivbestand, wird wie die ZIM-Dumps gepflegt und hält den
   Dienst vollständig offline. Die DBpedia-URI lässt sich aus dem Titel bilden, ohne dass ihre Existenz geprüft
   wäre; sie wird nur auf Wunsch mitgegeben und als „konstruiert" gekennzeichnet.

   **Die Testapp (`../kompendium-test`) löst das anders:** Sie holt QIDs live über `pageprops` der
   Wikipedia-API und die Entitätsdaten von `wikidata.org/wiki/Special:EntityData/{qid}.json`
   (`kompendium/adapters/wikipedia.py`, `wikidata.py`). Die **Form** der Ausgabe (QID, Label, Beschreibung,
   URL, Kategorien) ist übernehmenswert, die **Quelle** nicht — sie widerspricht dem Offline-Ziel.

```
POST /api/v2/entities
{"text": "...", "resolve": true, "wikidata": false, "archives": ["wikipedia_de_all_nopic"]}
```

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
| `base` (heute) | Python, libzim, numpy, scikit-learn, Model2Vec | 830 MB | Kompendium, Entitäten (spaCy `md`: +45 MB), QA `rule-based` |
| `ml` | dazu torch, transformers, QG- und QA-Modell | geschätzt 2,5–3 GB | zusätzlich QA `models` |

spaCy braucht kein torch und passt deshalb in `base`. Die QA-Modelle brauchen torch — das ist die eine
Entscheidung, die das Image wirklich schwer macht.

## Phasen

| Phase | Inhalt | Aufwand |
|---|---|---|
| U1 | v1 entfernen (8 Endpunkte, `app/api/v1/`, `MIGRATION.md`, Tests), Endpunktliste aufräumen | klein, viel Löschung |
| U2 | `POST /api/v2/knowledge` — die Bausteine dafür gibt es alle | klein |
| U3 | `POST /api/v2/entities` mit spaCy und Auflösung; Wikidata optional | mittel |
| U4 | `enrichment: model-knowledge` samt Kennzeichnung, Bericht und Prompt v3; Nebenläufigkeit 10 | mittel |
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
