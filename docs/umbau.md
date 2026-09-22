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
einziger** der 10 echten Treffer — mit dem weiteren Suchfenster von unten sind es 8 von 11 (dazu Form und
Grund). Anders als bei den beiden verworfenen Kriterien ist das Verlustrisiko damit
null. Der Filter nutzt den Parse, den das Verknüpfen ohnehin macht, kostet also nichts; `ner` bleibt unberührt,
weil das Erkennen kein Versprechen über Archive macht. Mit `link: false` findet keine Prüfung statt, und die
Antwort sagt es unter `note`.

Was der Filter **nicht** löst: „Richtung“, „Prinzip“ und „Schule“ haben echte Artikel und bleiben. Wer dort
Genauigkeit braucht, fragt `methods: ["ner"]`.

**Nachgebessert am 2026-09-20: Das Suchfenster war zu klein.** „Form“ und „Grund“ standen hier als Rauschen —
in Wahrheit sind beide Begriffsklärungsseiten, die der Filter nur nicht gesehen hat. Er suchte den Hinweis
„Begriffsklärungsseite“ in den ersten 2000 Zeichen der ersten beiden Abschnitte; die Vorlage steht aber am
**Ende** der Seite: bei „Form“ ab Zeichen 2281 von 2589, bei „Grund“ ab 5291 von 5599, bei „Feld“ ab 5815 von
6124. Gemessen an 807 echten Wörterbuch-Treffern aus sieben Themen fängt der ganze Text **30 weitere**
Begriffsklärungsseiten — „Fall“, „Lage“, „Ordnung“, „Punkt“, „Rolle“, „Schicht“, „Sohn“, „Abbe“, „Faust“
unter ihnen —, und jede trägt die typische Eröffnung („… steht für:“, „… ist der Familienname folgender
Personen:“). Gegenprobe auf Fehltreffer: von 600 zufälligen Artikeln kippte **keiner**.

**Nachgebessert am 2026-09-21: Wo ein Link steht, ist keine Frage des Textvergleichs.** Die erste Fassung
von `listed_meanings` suchte den Linktitel im *Text* der Listenabsätze. Gemessen an 1207 Links aus 31 echten
Seiten warf das **22** weg, davon nur drei die gewollten Etymologie-Links — die übrigen 19 waren echte
Bedeutungen, weil die angezeigte Beschriftung nicht der Titel ist („Punktierung (Musik)“ steht als
„Punktierung“, „Bezirk Friedrichshain-Kreuzberg“ als „Friedrichshain-Kreuzberg“). Der Parser weiß beim
Erfassen, ob ein Link in einem Listeneintrag steht, und merkt sich das jetzt (`ParsedArticle.list_links`).
Danach fallen **11** statt 22 weg, die drei Etymologie-Links weiterhin darunter; die restlichen acht stehen
nachweislich in Überleitungssätzen („in der Geographie“, „in der Astronomie“, „Furchen, Rillen“) und sind
keine Bedeutungen.

**Und die Alternativen kamen aus einer anderen Liste als die Auswahl.** `resolution.alternatives` las die
ungefilterten Links weiter, obwohl daneben schon gefiltert gewählt wurde — „Punkt“ meldete `Latein`,
„Wende“ meldete `Althochdeutsch`, „Rinne“ meldete `Mulde`. Diese Liste ist sichtbar: im 404 des Dienstes
und als „Vorschläge“ im CLI. Jetzt wird sie einmal berechnet und zweimal benutzt, womit das Auseinanderlaufen
nicht mehr möglich ist statt bloß behoben.

**Die Rückwirkung auf die Themenauflösung ist gewollt, aber nicht gratis.** Von 27 geprüften Themen ändern
sich 11, alle davon mehrdeutige Wörter. Vorher baute ein Kompendium zu „Form“ stillschweigend auf der
Listenseite auf und meldete `disambiguation: false` — eine falsche Angabe über die eigene Quelle. Jetzt meldet
es die Mehrdeutigkeit samt Alternativen und nimmt eine echte Bedeutung. Mit Kontext wählt
`_pick_from_disambiguation` brauchbar („Feld“ + Physik → Elektromagnetisches Feld, „Faust“ + Goethe →
Goethes Faust, „Union“ + Politik → CDU/CSU); ohne Kontext gewinnt der erste Link, und der kann danebenliegen
(„Punkt“ → „Latein“, der Etymologie-Link).

**Nachgebessert am 2026-09-21: Die Bewertung las den Titel nicht.** Genau dort steht bei einer deutschen
Begriffsklärung die Unterscheidung — „Rolle (Physik)“, „Feld (Numismatik)“ —, und der Artikelkörper
wiederholt sie selten. Der Text hinter „Rolle (Physik)“ beginnt mit „Eine Rolle ist ein Maschinenelement“
und enthält das Wort „Physik“ überhaupt nicht; er bekam null Punkte, und „Mangel (Gerät)“ als erster Link
der Seite gewann das Thema „Rolle“ im Physik-Kontext. Mit dem Titel in der Bewertung wird daraus
„Rolle (Physik)“, und von 18 gegen die echten Archive geprüften Fällen ändert sich **genau dieser eine**.
Dasselbe Muster nutzt die Volltextsuche derselben Datei längst (`f"{hit.title} {hit.lead_text}"`).

**Nachgebessert am 2026-09-21: Die Etymologie ist keine Bedeutung.** Eine deutsche Begriffsklärung beginnt
mit einem eigenen Satz — „Punkt (lateinisch punctum: der Einstich) steht für:“ —, und dessen Links sind
Wortherkunft, keine Bedeutungen. Sie stehen vor allem anderen, also gewannen sie ohne Kontext: „Punkt“
löste zu „Latein“ auf, „Wende“ zu „Althochdeutsch“. Gemessen an 34 echten Seiten trifft das **drei** von
ihnen, und in allen drei stand die erste echte Bedeutung direkt dahinter. `listed_meanings` nimmt nur
Links, die auch in den Listenabsätzen stehen; von 38 geprüften Seiten behielt **jede** mindestens drei
Kandidaten, eine Seite ohne Listen behält sicherheitshalber alle.

**Das Fenster `links[:12]` bleibt — gemessen, nicht aus Bequemlichkeit.** Bei „Punkt“ steht die
Geometrie-Bedeutung auf Position 20 von 36; ein Fenster von 24 würde sie fangen und kostet nur 0,16 s je
mehrdeutigem Thema (0,52 s gegen 1,14 s für vier Themen, kalter Parse-Cache). Es ist aber **kein sauberer
Gewinn**: Von 18 geprüften Fällen werden zwei besser („Punkt“ + Geometrie → Punkt (Geometrie), „Lage“ +
Stadt → Lage (Lippe)) und einer schlechter („Faust“ + Goethe → „Faust. Der Tragödie zweiter Teil“ statt
„Goethes Faust“, weil ein später Kandidat höher punktet). Mit einer bekannten Verschlechterung für seltene
Themen bleibt es bei 12; wer das ändern will, braucht zuerst eine bessere Punktevergabe.

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

**Befund vom 2026-09-21: `kind` etikettierte Begriffsartikel als Akteure.** Aufgefallen beim Nachmessen des
Wörterbuchs: „Wirtschaft“ kam als `Organisation` zurück, „Hilfe“ als `Netzwerk`, „Firma“ als `Organisation`.
Die Ursache stand im Muster: `classify_entity` suchte das Typwort („Unternehmen“, „Kooperation“, „Museum“)
**irgendwo** in den ersten 260 Zeichen, sobald dort auch ein „ist“ stand. Der Lead „Wirtschaft … ist die
Gesamtheit aller Einrichtungen … Zu den wirtschaftlichen Einrichtungen gehören **Unternehmen**“ traf damit,
obwohl der zweite Satz etwas ganz anderes sagt. Das ist keine Kosmetik: Die Matching-Policy hält den
Fließtext von Akteuren aus dem Standard-Baustein heraus, ein falsches Etikett schließt also Inhalt aus.

**Zwei Versuche gemessen und verworfen, der dritte trägt.** Das Muster nur hinter der Kopula zu verankern —
die Form, die `_WORK_RE` längst nutzt — macht es **schlechter** (18 von 29 statt 19): Deutsche
Organisationen heißen nach ihrem Typ („…-Gesellschaft“, „Deutsches Museum“), und genau dieses Signal im
Namen zerstört die Verankerung. Die Verbindung aus beidem bringt nur +1. Was fehlte, war die dritte
Beobachtung: Ein Artikel, dessen **Titel** das Typwort ist, ist der Begriff und nie eine Instanz.

Mit allen dreien, gegen die echten Archive und 29 handgeurteilte Artikel gemessen: **20 richtig vorher, 26
nachher**, sechs falsche Akteure weg (Wirtschaft, Firma, Kooperation, Museum, Bibliothek, Unternehmen) und
**kein einziger echter Akteur verloren**. Was bleibt: ein Begriff, dessen Lead ihn *über* ein Akteurswort
definiert („Hilfe … ist ein Teil der Kooperation“) — dafür braucht es den Kopf des Prädikats, kein Muster.

**Zweiter Befund vom 2026-09-21: `kind` verfehlte historische Personen — und etikettierte eine als
Organisation.** Aufgefallen beim Nachmessen des Akteursverzeichnisses auf dem Produktionsweg (die ersten 40
Links von sechs echten Themen, 240 Nachschläge, 10 Akteure): **Hans Carl von Carlowitz**, geboren 1645,
gestorben 1714, stand als `Organisation` darin. Die Ursache war eine Kette: Die Personenregel verlangte die
Klammer **unmittelbar** vor dem Geburtszeichen (`\(\*`). Deutsche Leads setzen aber oft erst den Zweitnamen
(„Tycho Brahe (Tyge Ottesen Brahe, auch bekannt als …; * 14. Dezember 1546"), und das julianisch-gregorianische
Datum klebt an den Monat („* 14. Dezemberjul. / 24. Dezember 1645greg."). Wenn die erste Stufe der Kaskade
so danebengreift, fällt der Artikel nicht durch — die nächste Stufe gewinnt. Bei Carlowitz war das
„**Kammer**- und Bergrat".

Gemessen an 18 historischen Personen: **8 verfehlt**, danach **18 von 18 richtig**.

**Drei Zuschnitte gemessen, der dritte trägt.** Das Zeichen irgendwo im Vorspann zu lesen holt sich ein
Museum („Peter Hennig († 2013)" im dritten Satz). Es nur im **ersten Satz** zu lesen verliert 12 echte
Biografien, weil der Satztrenner mitten im Namen schneidet („1. Baronet", „Jr.", „ndl."). Was trägt, ist
derselbe Gedanke, den die Typwörter schon nutzen: Das Zeichen zählt im **Namensteil vor der Kopula**. Eine
Namensliste stellt die Kopula an den Anfang („Zapatka **ist** der Familienname folgender Personen: …"), ein
Museum auch — eine Biografie nie.

Alt gegen neu auf denselben 1500 Zufallsartikeln (beide Male die echte Funktion, der alte Stand aus dem
Commit geladen): **61 Personen gewonnen**, 45 verloren — davon **42 Namenslisten**, die die alte Regel für
*eine* Person hielt, weil ihre Einträge Geburtsdaten tragen, dazu eine Band und eine Obstsorte. Der echte
Preis sind **zwei Artikel**: ein Künstlername, dessen Kopula vor dem Zeichen steht („Mata Hari … war der
Künstlername der Tänzerin … (* 1876)"), und eine Begriffsklärung über Firmen, die vorher falsch als Person
und jetzt falsch als Organisation zurückkommt. Eine Nebenwirkung geprüft und entkräftet: Wer keine Person mehr ist, gilt als Sachartikel — dessen Fließtext lässt die Matching-Policy in den Standard-Baustein. Von den 45 verlorenen Seiten erkennt der Parser aber **43 als Begriffsklärung**; sie erreichen den Korpus gar nicht. Übrig bleiben die Band und der Künstlername. Nebenbei belegt: `libzim`s `get_random_entry` lässt sich
nicht säen — Stichproben sind nur **innerhalb** eines Laufs vergleichbar, nicht zwischen Läufen.

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


### Die Textbasis der Paare: das Kompendium, nicht der Rohkorpus

**Befund vom 2026-09-21.** Mit `topic` las der Endpunkt den ganzen Korpus der Artikel. Am laufenden Dienst
gemessen: **50 068 Zeichen** Korpus gegen **31 050 Zeichen** Kompendium zum selben Thema. Die Paare zeigten
es auch — „Was geschah im Jahr 1240?" stammt aus der Optik-Geschichte tief im Artikeltext, die im Kompendium
gar nicht vorkommt.

Das war nie die Absicht der Kette. Sie lautet: **erst das Kompendium erzeugen, dann daraus fragen.**

| Aufruf | Textbasis |
|---|---|
| `text` gesetzt | genau dieser Text — etwa das Markdown eines Kompendiums, das der Aufrufer schon hat |
| nur `topic` | Teil 1 wird erzeugt und **seine Bausteintexte** sind die Basis |

Genommen wird die **Prosa der Bausteine**, nicht das fertige Markdown: das trägt Überschriften,
Belegnummern, Facetten-Marken und den Quellen-Baustein, und eine Frage nach einer Belegnummer lehrt
niemanden etwas. Angefragt wird nur `parts: ["world"]` — Teil 2 zählt Lehrplanelemente auf und Teil 3
Materialien einer Sammlung, beides keine Prosa, aus der sich fragen lässt.

Der Preis ist ehrlich zu nennen: Ein `topic`-Aufruf kostet jetzt eine Kompendium-Erzeugung (bei *Optik*
regelbasiert rund 8 bis 14 Sekunden). Wer das nicht will, erzeugt einmal und übergibt den Text.

**Nebenwirkung, geprüft:** `_text_of` im Endpunkt hatte damit keinen Aufrufer mehr und ist entfallen, samt
dem Test, der am selben Tag dafür geschrieben worden war. Die Zusicherung dahinter — aus Literatur,
Weblinks, Einzelnachweisen und „Siehe auch" entstehen keine Fragen — hält jetzt eine Ebene höher und
stärker: `segment_source` macht aus diesen Abschnitten gar keine Chunks, und das Kompendium besteht nur aus
Chunks (`tests/test_segmentation.py`).

### Bildungsstufen — eine Option der Stufe `llm`

`levels` in der Anfrage verteilt die Paare über Bildungsstufen und gibt je Paar eine zurück (`level`).
Das Feld ist **optional**; ohne Angabe läuft alles wie zuvor.

**Die Eingabe spricht das Vokabular des Aufrufers, der Dienst seine eigenen Werte.** Die Bildungsstufe
kommt als OpenEduHub-Begriff — als prefLabel („Sekundarstufe I"), als altLabel („Sekundarstufe 1") oder
als Begriffs-URI (`.../educationalContext/sekundarstufe_1`). Alle drei bildet `bildungsstufe_facet` auf
den Wert aus `config/facets.yaml` ab, und die Projektwerte bilden auf sich selbst ab. Ab der Prüfung
reist nur noch **ein** Vokabular: der Prompt bekommt „Sek I", und `_level()` kann die Antwort des Modells
darauf zurückführen.

Vier Stufen des Vokabulars haben kein Gegenstück — **Schule, Förderschule, Fernunterricht, Informelles
Lernen**. Sie werden **namentlich abgelehnt** (422), nicht auf einen Nachbarn gebogen: Ein erfundenes
Etikett würde an den Paaren in einen Dienst weiterreisen, der es nicht kennt. Wer sie braucht, erweitert
`config/facets.yaml` — das ist eine Entscheidung über das Kompendium-Vokabular, nicht über diesen
Endpunkt.

**Nur `llm` kann eine Stufe zuordnen**, und das ist keine Bequemlichkeit: `rule-based` könnte die
Eigenschaft aufstempeln, aber nie einen Wert — Fragevorlagen haben kein Schwierigkeitssignal. `models`
hat überhaupt keinen Begriff von Schwierigkeit; die erfundene Stufe dieser Stufe wurde am 2026-09-21
ausgebaut (Commit 2746291). Wer `levels` an eine andere Stufe schickt, bekommt die Paare ohne Stufe —
**und einen Hinweis im Feld `note`**. Der Hinweis hängt an der *tatsächlichen* Stufe, nicht an der
angefragten: Wer `llm` anfragt und in den Regelmodus zurückfällt, verliert die Stufen mit, und das steht
dann auch da.

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

**Zweiter Nachtrag: Die Sätze kamen vom falschen Trenner.** Nach der Behebung oben blieben die Antworten
kurz („(von“, „optikós“). Ursache: spaCy zerschneidet deutsche Leads an
Abkürzungen und Datumsangaben. Gemessen an der echten Wikipedia wurde aus dem Optik-Lead drei Fragmente
(36, 66 und 242 Zeichen), aus dem Abbe-Lead ebenfalls drei (79, 51, 105). Aus einem Fragment kann nur eine
Fragment-Antwort kommen.

Zwei naheliegende Fixes wurden gemessen und verworfen: Eine Mindestlänge greift nicht (nur 3 von 268
Kandidaten liegen unter 30 Zeichen, und das schlechte „Die Optik (von altgriechisch ὀπτικός“
hat 36); die gemeinsame Wahl des besten Spans statt zweier Einzelmaxima ändert auf sauberen Sätzen nichts.
Gewirkt hat vorhandener Projektcode: `split_sentences` aus `app/knowledge/segmentation.py` ist auf dieses
Korpus abgestimmt (Abkürzungen, Initialen, Ordnungszahlen) und hielt alle geprüften Leads zusammen; 568
Sätze aus fünf Artikeln sind wörtliche Teilstücke, die Zuordnung der Nominalphrasen trägt also. Live danach:
aus „(von“ wurde „Lehre vom Licht genannt, ist ein Gebiet der Physik“, und die Fragen selbst
wurden besser, weil der Generator ganze Sätze sieht. Preis: 20,6 s statt 12 s für vier Paare.

**Aus dem Betrieb gemeldet und am 2026-09-21 behoben: Die Fragen deckten den Artikel nicht ab.** Jan
berichtete, zu „Optik“ drehten sich fast alle Fragen um Jahreszahlen. Nachgestellt gegen die echten
Archive: Die Ursache ist nicht das Modell, sondern die **Reihenfolge der Kandidaten**. Der Generator
arbeitet satzweise, und die Nominalphrasen wurden streng in Lesereihenfolge abgearbeitet — der erste Satz
einer Biografie enthält ein halbes Dutzend davon (Name, Datum, Ort, Bundesstaat, Beruf), also war `count`
erschöpft, bevor der zweite Satz an die Reihe kam. Gemessen: zu „Ernst Abbe“ stammten **alle acht** Fragen
aus der Geburts- und Sterbezeile („Wo geboren?“, „Wann gestorben?“, „In welchem Bundesstaat?“), zu „Optik“
**alle zwanzig** aus den ersten zwei Sätzen, vier davon Varianten derselben Frage.

`spread` verteilt reihum: Jeder Satz liefert eine Nominalphrase, bevor einer eine zweite liefert. Danach,
im Image gegen dieselben Archive gemessen: „Ernst Abbe“ 8 Paare mit **8 verschiedenen Antworten** (Beruf,
Zeiß und Schott, Glaswerk, Vater, Schulzeit, Studienmotiv), „Optik“ bei `count: 20` **20 verschiedene
Fragen** über Mikrooptik, Quantenoptik, nichtlineare und atmosphärische Optik, Brechungsgesetz, Spiegel und
Linsen. Der Preis ist null: Es werden nicht mehr Aufrufe gemacht, nur andere.

**Was das nicht behebt:** Die Fragen der kleinen Modelle bleiben stellenweise schief — „Wer hat in Eisenach
einfache Beziehungen geschlossen?“ oder eine Frage, die das Subjekt des Satzes verfehlt. Das ist die
Qualität der 220-Millionen-Parameter-Modelle und kein Reihenfolgeproblem.

**Image zunächst 3,4 GB, gemessen** (Schätzung war 2,5–3 GB, sie rechnete mit Radgrößen statt entpackten):
torch 769 MB, QG-Modell 853 MB, QA-Modell 418 MB, Embedding-Modell 322 MB, transformers 114 MB.

**Erledigt am 2026-09-20: Beide Modelle liegen jetzt in halber Genauigkeit, das Image bei 2,74 GB.** Offen war,
ob fp16 das Modell ändert. Gemessen im Image, mit denselben Eingaben und fp32 beim Rechnen: **12 von 12 Fragen
und 8 von 8 Antwortstellen wortgleich**. Der Generator fällt von 892 auf 446 MB, das Antwortmodell von 437 auf
219 MB, das Image von 3,40 auf 2,74 GB — ein Fünftel weniger. Die gepickelte `pytorch_model.bin` geht mit,
safetensors braucht kein `torch.load`.

Zwei Zahlen hat erst die Gegenprobe zurechtgerückt. Der erste Ladevorgang sah mit 10,5 s gegen 2,0 s teuer aus
— das war kalter Cache auf einer eben geschriebenen Datei. Warm kostet die Umwandlung **0,8 s** (1,1 s gegen
0,3 s), und zu lesen sind halb so viele Bytes. Und: **transformers 5 lädt im dtype der Datei.** Ohne
ausdrückliches `dtype=torch.float32` in `load_qa_models` hätte der Dienst ab sofort in fp16 gerechnet — auf
dieser CPU gemessen ohne Unterschied (4 von 4 Fragen gleich, 4,2 s gegen 3,9 s), aber fp16 auf der CPU ist
nichts, was dieses Image für jeden Wirt versprechen kann. Halbiert wird die Datei, nicht die Arithmetik.

### Wie U5a am 2026-09-20 gebaut wurde

**`app/synthesis/qa.py` hatte seit U1 keinen Aufrufweg mehr** — der v1-Endpunkt war weg, die Tests mit ihm.
U5a belebt das Modul wieder, statt Neues zu schreiben, und gibt ihm seine Tests zurück (12 Einheitentests).

**`models` steht nicht im Schema.** Ein Aufzählungswert, der nie funktionieren kann, ist schlimmer als ein
fehlender; U5b fügt ihn hinzu. Einen Wert zu ergänzen bricht keinen Aufrufer.

**Die Stufenverteilung (`level_property`, `level_values`) bleibt ungenutzt.** Gemessen am 2026-09-20:
`_level()` bildet über Teilstrings ab und setzte sonst stillschweigend die **erste** angebotene Stufe — aus
„Sekundarstufe II“ wurde „Primar“. Das war ein falsches Etikett, kein fehlendes.

**Behoben am 2026-09-21: Was die Regel nicht abbildet, bleibt leer.** Die Abbildung darf jetzt scheitern —
genau das, was hier gefehlt hat. Ein Aufrufer sieht eine leere Stufe und kann entscheiden; durch eine
erfundene sieht er nicht hindurch. Der Test, der die alte Fassung festhielt, sagte in seinem eigenen
Docstring „pins what the code does today, not what it should“ und ist mitgewandert.

**Weiterhin offen, aber aus einem anderen Grund:** Der Endpunkt bietet Stufen nicht an. Das ist jetzt keine
Sicherheitsfrage mehr, sondern eine Produktfrage — niemand hat sie bisher gebraucht. Wer sie will, hängt
`level_property` und `level_values` an `POST /api/v2/qa`; die Schicht darunter trägt sie bereits.

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

### Fragequalitaet der kleinen Modelle, am 2026-09-21 gemessen

In meinen Berichten stand mehrfach, die Qualitaet der Fragen haenge an der Modellgroesse. In dieser
Datei stand sie nie, und gemessen war sie auch nicht. Jetzt gemessen, im Image, an den ersten 14 Paaren
zu *Optik* (Kandidat, erzeugte Frage, gefundene Antwort, je Paar sichtbar):

Zuerst das Erfreuliche: **keine einzige Frage nach einer Jahreszahl mehr**. Der Befund, mit dem diese
Arbeit anfing, ist weg — die 14 Paare stammen aus 14 verschiedenen Saetzen, und alle 14 kommen durch den
Filter (keines wird als unbeantwortbar verworfen).

Die verbleibenden Maengel sitzen aber **nicht nur im Modell**. Von Hand zugeordnet:

| Fehlerort | Was passiert | Beispiel aus dem Lauf |
|---|---|---|
| Kandidat | markiert ist das Satzsubjekt, ueber das sich nichts fragen laesst | Kandidat „Grundlage" in „Grundlage der Wellenoptik ist die Wellennatur des Lichts" ergibt „Was ist die Wellennatur des Lichtes?" — die Frage stellt das Praedikat als Subjekt |
| Satz | der Satz verweist zurueck und ist allein nicht beantwortbar | „Viele Gesetzmaessigkeiten … gelten auch **ausserhalb dieser Bereiche**" ergibt „Was gibt es ausserhalb dieser Bereiche?" |
| Fragemodell | kaputte Grammatik oder erfundener Inhalt | „Was ist der **Vorteil** der Mikrooptik gegenueber der Wellenlaenge?" — von einem Vorteil steht dort nichts |
| Antwortmodell | liefert den ganzen Quellsatz statt einer Spanne | 5 der 14 Antworten sind der vollstaendige Satz |

Nach Handurteil sind **6 der 14 brauchbar**. Etwa die Haelfte der Maengel entsteht also vor dem Modell, in
der Auswahl von Kandidat und Satz. Ein groesseres Modell wuerde die Zeilen 2, 6 und 9 heilen und die
uebrigen nicht.

### Der erste Ansatzpunkt, umgesetzt und gemessen

**Eine Antwort, die praktisch den ganzen Satz umfasst, ist keine Antwort** — sie liest den Satz vor. Aus
dieser Beobachtung wurde `MAX_ANSWER_SHARE` in `model_pairs`.

Die Schwelle ist gemessen, nicht geraten. Über 32 Paare aus vier echten Themen fällt der Anteil der
Antwort am Satz in Gruppen mit einer Lücke dazwischen:

```
0.03 ... 0.48 | 0.71  0.78 | 0.86  0.92  0.98  0.98  0.98  0.99  1.00
```

Das Paar bei 0.71 („Was wird als photosynthetische Effizienz bezeichnet?") ist eine echte Antwort, die
zufällig eine lange Definition ist. Das bei 0.86 beginnt mit einem Nebensatz („Soweit die energiereichen
organischen Stoffe …"). Die Linie gehört dazwischen: **0,8**.

Derselbe Harnisch gegen beide Fassungen, vier Themen, je 8 Paare angefragt:

| | alte Fassung | neue Fassung |
|---|---|---|
| angefragt / geliefert | 32 / 32 | 32 / **32** |
| mangelfrei | 24 (75 %) | **30 (94 %)** |
| WIEDERHOLUNG | 7 | **0** |
| RUECKVERWEIS | 1 | 1 |
| ECHO | 4 | **1** |

**Kein Ertragsverlust.** Wer eine Wiederholung verwirft, verliert kein Paar: die Schleife nimmt den
nächsten Kandidaten, und der war die ganze Zeit da — er wurde nur von der Wiederholung verdrängt. Bei
*Optik* fielen damit 5 von 8 Mängeln auf 1, bei *Photosynthese* 3 auf 0.

### Was bewusst nicht umgesetzt ist

1. Rückverweise (`dabei`, `dieser`, `daneben`) aus der Frage verwerfen: **1 von 32**. Eine Regel für 3 %
   wäre mehr Code als Nutzen, und das eine Beispiel („Welcher Charakter des Lichts spielt dabei eine große
   Rolle?") hat eine richtige Antwort.
2. Das Satzsubjekt eines definierenden Satzes meiden. Genau diese Form liefert auch die besten Paare
   („Was ist die Quantenoptik?"), eine pauschale Regel wäre schlechter.

**Was die Maßzahl nicht misst.** Die drei Kriterien sind ein Boden, kein Qualitätsurteil. „Was ist der
Vorteil der Mikrooptik gegenüber der Wellenlänge?" zählt als mangelfrei, obwohl von einem Vorteil im Text
nichts steht — das erfindet das Fragemodell, und dagegen hilft nur ein größeres Modell oder eine Prüfung,
die den Text versteht.

### Erfundene Frageinhalte: als Maß widerlegt, dafür ein Textbefund

**Die Frage war:** Wie oft erfindet das Fragemodell Inhalte, die im Text nicht stehen („Was ist der
*Vorteil* der Mikrooptik?" — von einem Vorteil steht dort nichts)? **Der Versuch:** Ein Inhaltswort der
Frage gilt als gedeckt, wenn sein Anfang (6 Zeichen) im Quellsatz vorkommt; ungedeckte Wörter wären der
Verdacht.

**Gemessen an 32 Paaren aus vier echten Themen: 10 voll gedeckt, 13 mit einem offenen Wort, 9 mit zwei
und mehr.** Die offenen Wörter sind überwiegend harmlose Umschreibungen — „bezeichnet", „Bereich",
„Beruf", „Grund", „große" (statt „bedeutende"), „Teile" (statt „Teilchen"). Als Filter würde die
Wortdeckung **zwei Drittel der guten Fragen** mitnehmen. Der Ansatz ist damit **widerlegt**, nicht
aufgeschoben: Gegen erfundene Inhalte hilft nur ein größeres Modell oder eine Prüfung, die den Text
versteht — keine Wortstatistik.

### Der Quelltext: Anhänge gehörten nicht hinein

Beim Nachmessen fiel etwas anderes auf. `segment_source` schließt Literatur, Weblinks, Einzelnachweise
und Siehe auch über das Überschriften-Lexikon aus — sie sind Belege, kein Inhalt. `_text_of` im
QA-Endpunkt ging aber **direkt** über `source.sections` und kannte das Lexikon nicht.

| Thema | ganzer Text | ohne Anhänge |
|---|---|---|
| Optik | 10 812 Zeichen, **70 Sätze** | 9 003 Zeichen, **49 Sätze** |
| Zahnmedizin | 18 814 Zeichen, 113 Sätze | 16 250 Zeichen, 97 Sätze |
| Klimawandel | 49 820 Zeichen, 217 Sätze | 49 425 Zeichen, 215 Sätze |
| Photosynthese | 50 046 Zeichen, 332 Sätze | 49 987 Zeichen, 332 Sätze |

In Zeichen sind das nur 3,7 % — **in Sätzen bei einem kurzen Artikel 30 %**, weil Literaturzeilen kurz
sind. Und `spread` gibt jedem Satz ein Paar, bevor einer ein zweites bekommt, stellt „2. Auflage." also
gleichberechtigt neben den Fachinhalt.

**Wie groß der Schaden wirklich war, wurde gemessen, bevor etwas gebaut wurde:** Die Kandidaten kommen in
Dokumentreihenfolge, der Anhang steht am Ende. Bei `count` bis 20 stammen **0 von 80** der zuerst
probierten Kandidaten aus dem Anhang; erst beim größtmöglichen `count` von 50 ist es **1 von 100** — und
zwar „2. Auflage" aus „2. Auflage.".

Behoben wurde es trotzdem, und der Grund ist nicht die Häufigkeit: Das Projekt hat längst entschieden,
dass diese Abschnitte kein Inhalt sind — nur der QA-Endpunkt fragte nicht danach. Eine Inkonsistenz von
drei Zeilen, keine Geschmacksfrage.

**Nebenbei korrigiert sich eine frühere Messung:** Die Proben bis dahin lasen `sections[:3]` und
schnitten bei 3000 Zeichen. Die Produktion nimmt ganze Abschnitte bis 50 000 — bei *Optik* 10 773 statt
3000 Zeichen, bei *Photosynthese* schöpft sie die Grenze aus. Die Zahlen zur Fragequalität oben stammen
aus dem verkürzten Text und gelten für diesen; die Größenordnung hat sich in der Nachmessung bestätigt.

### Das Tempo der Modellstufe: die Schleife, nicht das Modell (2026-09-21 gemessen)

**Anlass:** 18 Sekunden für fünf Paare. Erster Verdacht war das Modell — `german-qg-t5-quad` ist t5-base
mit rund 220 Millionen Parametern. Der Verdacht war falsch. Gemessen wurden stattdessen die zwei Hebel im
eigenen Code: die Zahl der Strahlen und die Bündelung. Zehn Kandidaten eines echten Kompendiumtextes:

| Einstellung | je Frage |
|---|---|
| 4 Strahlen, einzeln (die bisherige Fassung) | 1,97 s |
| 2 Strahlen, einzeln | 1,29 s |
| 1 Strahl, einzeln | 0,90 s |
| 1 Strahl, gebündelt | 0,40 s |
| **4 Strahlen, gebündelt** | **1,03 s** |

**Weniger Strahlen kostet Qualität — gemessen, nicht vermutet.** Aus „Welche Physikrichtung beschäftigt
sich mit der Ausbreitung von Licht?" wurde mit einem Strahl „Was ist die Physik?" (die Antwort wäre
*Optik*, nicht *Physik*), aus „Welche Optik befasst sich mit den angrenzenden Strahlungsbereichen…"
wurde „Welches Instrument befasst sich…", und „im elektrischen Feld oder im Magnetfeld" verlor das
elektrische Feld. Die Strahlen bleiben bei vier.

**Die Bündelung dagegen ist wortgleich.** 24 Kandidaten, vier Strahlen durchgehend, gegen die
Einzelaufrufe verglichen:

| Bündel | je Frage | wortgleich |
|---|---|---|
| einzeln | 1,64 s | — |
| 5 | 0,83 s | 24/24 |
| **8** | **0,79 s** | **24/24** |
| 24 | 1,21 s | 24/24 |

**Ein großes Bündel ist wieder langsamer.** Die Auffüllung richtet jede Zeile am längsten Satz aus, also
zahlt ein Bündel zu 24 diesen Satz 24-mal. Der Punkt liegt bei etwa acht — daher `BATCH_SIZE = 8`.

**Der Verschnitt ist klein.** Eine Runde wird ganz erzeugt, auch wenn die geforderte Zahl mitten darin
erreicht ist. Gemessen: 20 Paare kosteten 25 der 314 Kandidaten, also folgt einer Runde selten eine zweite.

**A/B im selben Prozess** (alte Schleife nachgebildet, gleiche Modelle, gleicher Text):

| angefragt | alt | neu | schneller | Paare identisch |
|---|---|---|---|---|
| 5 | 15,4 s | 10,7 s | 1,44× | 5/5 |
| 20 | 38,0 s | 22,2 s | 1,71× | 20/20 |

**Der Preis ist Speicher.** Acht Sätze zu je vier Strahlen sind gleichzeitig unterwegs; das Hochwasser des
Prozesses stieg um rund 190 MiB. Wer zu knapp bemessen ist, senkt `BATCH_SIZE` — vier Sätze schlagen immer
noch einen.

**Warum kein anderes Modell.** `dehio/german-qg-t5-e2e-quad` erzeugt mehrere Fragen in einem Durchgang,
ist aber ebenfalls t5-base und spart genau das, was die Bündelung schon einsammelt: den Kodierer und den
Aufrufaufwand, nicht die Ausgabe-Token. Vor allem ist es **nicht antwortbewusst** — die `<hl>`-Markierung
und damit `spread()` fielen weg, also gerade das, was die Jahreszahlen-Flut behoben hat.
`FLAN-T5-small` ist dreimal kleiner, aber englisch und ebenfalls nicht antwortbewusst; ein deutsches
t5-small gibt es in dieser Linie nicht (`valhalla/t5-small-qa-qg-hl` ist auf englischem SQuAD trainiert).

### Eine dritte Regelstufe: das Satzsubjekt statt der Entitaet (2026-09-22 gemessen)

**Die Frage war, ob Entitaetenerkennung schnellere Fragen erzeugt.** Tempo war nicht das Problem: der
Regelmodus braucht 0,078 s für 20 angefragte Paare, die Modellstufe 23,4 s — 300-mal so lang. Der
Regelmodus ist nicht langsam, er ist **dünn**: 8 von 20 Paaren, und die Hälfte davon fragt nach einer
Jahreszahl.

**Reine Entitaetenregeln tragen nicht.** Gemessen über 172 Sätze aus vier echten Kompendien (Optik,
Ernst Abbe, Französische Revolution, Photosynthese): 95 % der Sätze gehen heute leer aus oder treffen nur
die Jahres-Vorlage, 67 % davon enthalten eine Entität. Aber die Etiketten stimmen zu oft nicht — spaCy
gab `PER` für „Prüfungsvorbereitungskurse an Meisterschulen" und `ORG` für „Grundlage der Wellenoptik ist
die Wellennatur des Lichts", und `MISC` war im Geschichtstext mit 50 von 79 der größte Topf und ist
semantisch leer. Eine Regel „enthält PER → *Wer war X?*" hätte messbar Unsinn erzeugt.

**Was trägt, ist der Parse, den das Modell ohnehin mitliefert.** `de_core_news_md` hat einen Parser in
der Pipeline. Ein deutscher Aussagesatz stellt das Subjekt voran und das finite Verb an zweite Stelle —
also bleibt es Deutsch, wenn man das Subjekt durch ein Fragewort ersetzt und den Rest wörtlich stehen
lässt. Die Antwort ist dann das Subjekt, nicht der ganze Satz:

| | Vorlagen | Subjekttausch | models |
|---|---|---|---|
| Sätze mit brauchbarer Frage | 8 von 172 (5 %) | **33 von 172 (19 %)** | — |
| Zeit | 0,078 s | ~4 ms je Satz (gebündelt, warm) | 23,4 s je 20 Paare |
| Antwort | ganzer Satz | Nominalphrase | Textstelle |
| mangelfrei | Jahresfragen weitgehend wertlos | 26 von 33 (79 %) | 30 von 32 (94 %) |

Viermal so viele brauchbare Fragen ohne Modell, aber messbar schlechter als die Modelle — deshalb eine
**dritte Option** (`method: parse-based`) und kein Ersatz. `rule-based` bleibt unverändert der Standard.
Der Ort, an dem die neue Stufe wirklich gewinnt, ist der kleine vServer: dort wird die Modellstufe
OOM-getötet (Exit 137, gemessen), und acht dünne Paare waren bisher alles, was blieb.

### Die vier Wachen, jede gegen eine gemessene Fehlfrage

Ohne Wachen liefert der Subjekttausch 70 der 172 Sätze (41 %), aber mit Fehlern. Jede Wache steht für
eine falsche Frage, die die Messung erzeugt hat — nicht für einen ausgedachten Fall:

1. **Kein Pronomen als Subjekt.** „Was ist eine Wissenschaft und gehört zur Physik?" — Antwort „Sie".
   12 von 172 Sätzen. spaCy hat keine Koreferenz, das ist nicht reparierbar; Biografien verlieren dadurch
   den größten Teil ihrer Sätze („Er wurde 1840 geboren").
2. **Kein Pluralverb.** „Was gelten auch außerhalb dieser Bereiche?" ist kein Deutsch. 15 von 172.
3. **Keine unpaarige Klammer im Subjekt.** Der Parse schnitt „Ernst Karl Abbe [" ab und fragte den Rest.
4. **Kein Rest, der mit Komma beginnt.** Eine Apposition außerhalb des Subtrees ließ „Was , wird durch
   Verfolgen des Strahlenverlaufs konstruiert?" übrig.

Mit den Wachen bleiben 33 der 172 Sätze.

**Am ausgelieferten Code nachgeprüft, nicht nur an der Sonde.** `parse_based_pairs` selbst, im Image,
über dieselben vier Texte: 172 Sätze zu 33 Paaren (19 %), davon 4 mit *Wer* und 29 mit *Was* — dieselben
Zahlen wie die Sonde. Die Zeit liegt warm bei 3,8 bis 4,2 ms je Satz; der erste Text eines Prozesses
zahlt mit 18,1 ms je Satz einmalig das Aufwärmen von spaCy.

**Verworfen: „Wer" über eine Person irgendwo im Subjekt.** Naheliegend, weil „Sein Vater Georg Adam Abbe"
und „Der Politikwissenschaftler Iring Fetscher" am Kopf ein Substantiv tragen und deshalb „Was" bekommen.
Gemessen: die Lockerung repariert diese zwei Fälle und zerbricht zwei andere („Wer dauern in Vollzeit
ungefähr ein Jahr?", „Wer ˈabə] (* 23. Januar 1840 …?"). Netto null, also bleibt es beim Kopf.

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

### Wie weit `target_length` die Länge wirklich steuert (2026-09-21 gemessen)

Am laufenden Dienst, Thema *Optik*, nur Teil 1:

| `target_length` | Markdown gesamt | Bausteintext |
|---|---|---|
| 2 000 | 25 784 | 23 127 |
| 4 000 | 27 583 | — |
| 8 000 | 31 050 | 28 323 |
| 12 000 (Vorgabe) | 32 523 | — |
| 20 000 | **35 056** | **32 329** |
| 40 000 | 35 056 | — |
| 60 000 | 35 056 | 32 329 |

**Nach oben steuert der Wert, bis die Quellen ausgehen.** Ab 20 000 ändert sich nichts mehr: mehr
Zielzeichen, aber kein Material. Genau hier hilft, was ohnehin geplant ist — **mehr Quellen heben diese
Decke**, und der Parameter steuert dann weiter.

**Nach unten steuert er kaum.** Bei Ziel 2 000 kommen 25 784 Zeichen heraus. Der Grund steht nicht im
Ziel, sondern in der Absatzgrenze: `_scale_budgets` verteilt den Wert nach Gewicht auf die Bausteine
(mindestens 300 Zeichen je Baustein), und `build_excerpts` hört erst **an einer Absatzgrenze** auf,
sobald das Anderthalbfache des Anteils erreicht ist. Die Bausteinlängen bei Ziel 2 000:

```
318  348  357  502  524  534  563  1092  3348  5893  9648
```

Ein einzelner Baustein ist **9 648 Zeichen** — fast das Fünffache der gesamten angefragten Länge, weil
sein Quellabsatz so lang ist. Ein Baustein kann nie kürzer sein als sein erster Absatz.

**Das ist eine Entwurfsentscheidung, kein Fehler:** Die Regelextraktion nimmt ganze Absätze, damit der
Wortlaut der Quelle erhalten bleibt und jeder Satz belegt ist. Wer wirklich kurze Texte braucht, schneidet
entweder mitten im Absatz (dann ist der Beleg hin) oder lässt den LLM-Modus formulieren (`generation:
llm`), der die Ziellänge im Prompt nennt. Geändert wurde deshalb nur die **Feldbeschreibung**, die bis
hierhin „Approximate total characters for part 1" versprach — eine Zahl, die am unteren Ende um den
Faktor zehn danebenlag.

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
