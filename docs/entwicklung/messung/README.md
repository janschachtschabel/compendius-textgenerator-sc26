# Messskripte zur Entwicklungsdokumentation

Die Skripte zu den Messungen vom 23. bis 26.09.2026 im [Messprotokoll](../05-messprotokoll.md). Sie sind für den
Entwicklungsrechner geschrieben: Archive unter `kompendium-test\data`, die venv dieses Projekts, die venv der Testapp
und die venv des alten Dienstes. Pfade stehen am Anfang jedes Skripts. Wer auf dem Server misst, übergibt dessen
Adresse als Argument; sie steht nicht im Repository. Der b-api-Schlüssel kommt aus `B_API_KEY` und wird nirgends
geschrieben.

| Messung | Skripte | Umgebung | Sprachmodell |
|---|---|---|---|
| M1 Laufzeit des neuen Dienstes | `perf_new.py <server> <out.json>` | beliebiges Python | keins, jede Anfrage schaltet es ab |
| M2 alter Dienst | `old_run.py <out-dir> <thema>…` | venv des alten Dienstes, Arbeitsverzeichnis `alterCode/compendious` | `gpt-4.1-mini`, rund 8.000 Tokens je Thema |
| M2 Auswertung | `old_analyze.py <out.json> <run-dir>…` | venv dieses Projekts | keins |
| M3 Teil 1 im neuen Dienst | `new_part1_check.py <server> <out.json>`, `final_checks.py <server>` | venv dieses Projekts | keins |
| M4 alle Verfahren im Ablauf des Dienstes | Schritte 1, 2, 4, 5, 7 und 8 unten | `mc_model_scores.py` in der venv der Testapp, der Rest in der venv dieses Projekts | keins |
| M5 LLM als Zuordner | Schritte 3 und 6 unten | venv dieses Projekts | `gpt-5.6-luna`, harte Tokengrenze als Argument |
| M6 blinder Richter | `mc_heldout_export.py`, `mc_variants_v200.py`, `mc_judge_v200.py <export> <cache> <token-grenze>` | venv dieses Projekts | `gpt-5.6-luna`, harte Tokengrenze als Argument |
| M7 Größe des XML-Dumps | `xml_dump_ratio.py` | beliebiges Python | keins; lädt rund 64 MB Stichproben |
| M8 Artikelwahl | `mc_artikelwahl.py <alte-läufe> <ergebnis.json> <pool.json>`, dann `mc_artikel_richter.py <pool.json> <richter.json> <token-grenze>`, dann `mc_artikelwahl_auswertung.py <ergebnis.json> <richter.json> <out.txt>` | venv dieses Projekts | Richter `gpt-5.6-luna`, harte Tokengrenze als Argument |
| Suchzeiten des Archivs | `mc_zim_suche.py <out.json>` | venv dieses Projekts | keins |
| M9 Artikelwahl mit Regeln und LLM | `mc_aufloesung.py <out.json> [--llm] <gold.yaml>…`; den alten Stand mit `PYTHONPATH` auf eine `git archive`-Kopie von `c03dafe` | venv dieses Projekts | mit `--llm` `gpt-5.6-luna` über `article_choice=llm`, rund 950 Tokens je unsicherer Anfrage |
| M10 Volltexttreffer | `mc_trefferfilter.py <out.json>`, `mc_treffer_llm.py <out.json> [--korpus]`, `mc_treffer_wirkung.py <bewertungen.json> <out.json>` | venv dieses Projekts | `mc_treffer_llm.py`: `gpt-5.6-luna`, rund 900 Tokens je Thema |
| M11 Wikibooks und Wikiversity | `mc_zusatzquellen.py <out.json> <pool.json>`, `mc_zusatzsuche.py <out.json> <treffer-je-archiv>` | venv dieses Projekts, beide Archive unter `kompendium-test\data` | `mc_zusatzsuche.py`: `gpt-5.6-luna` für die Trefferprüfung |
| M12 Bausteinbeschreibungen und LLM-Zuordnung | `mc_varianten.py <out.json> [--llm] [--llm-pool gold] <label=template:strategie>…` mit `sc26_beschreibungen.json`; `mc_llm_sparvarianten.py <out.json> [--rotieren] <weg>…` (Wege rules, llm, llm_25x700, llm_50x400, llm_billig, llm_zweifel) | venv dieses Projekts | `gpt-5.6-luna`, 70.000 bis 150.000 Tokens je LLM-Variante |
| M13 Laufzeit | `mc_zeit_artikelwahl.py <out.json> <weg>…` mit `PYTHONPATH` auf die Kopie des Standes; `mc_zeit_zuordnung.py <out.json>` | venv dieses Projekts | `gpt-5.6-luna` für `llm`: rund 1.000 Tokens je Thema bei der Artikelwahl, rund 29.000 bei der Zuordnung |
| M14 Budget ohne Rückfall | `mc_zeit_zuordnung.py <out.json> Relativitätstheorie Völkerwanderung Kreuzzüge Expressionismus Verdauung` mit `PYTHONPATH` auf die Kopie des Standes mit D39; `mc_budget_nachrechnung.py <out.json> 60000 <Thema>…` | venv dieses Projekts | `gpt-5.6-luna`: 172.440 Tokens für die fünf Themen; die Nachrechnung ruft die b-api nicht |
| M15 lokale Strategien je Baustein | `mc_varianten.py <out.json> lexicon_only=-:lexicon_only bm25=-:bm25 char_tfidf=-:char_tfidf hybrid_light=-:hybrid_light` | venv dieses Projekts | keins |
| M16 laya-multilingual | `mc_laya_export.py <ergebnisse-ordner> <export.json> <gold.yaml>…` in der venv dieses Projekts, dann `mc_laya.py <export.json> <out.json>` in der venv der Testapp mit dem Paket `laya` 0.3.20 auf `PYTHONPATH` | beide; das Modell `convaiinnovations/laya-multilingual` (678 MB) von Hugging Face | keins |
| M17 alter Weg über Begriffe vom LLM | `mc_alte_artikelwahl.py <out.json> <token-grenze> [<modell>]` aus dem Projektordner (der Dienst liest `config/` relativ dazu; ohne die Fachwörter kommen die Regeln auf 79 statt 86) | venv dieses Projekts | der Prompt des alten Dienstes wortgleich; ohne Modellangabe das Modell des Dienstes (M17 lief mit `gpt-5.6-luna`); `gpt-4.1-mini` nur, um den alten Dienst nachzustellen, bei Temperatur 0,7; rund 1.300 bis 1.500 Tokens je Anfrage |
| M18 Kennungen der Entitäten | `mc_entitaeten_gnd.py <out.json> [--wikidata <wikidata.db>] [--gegen <stichprobe.json>] [--lobid <n> <stichprobe.json>]` aus dem Projektordner; den Index vorher mit `compendium wikidata build` | venv dieses Projekts | keins; `--lobid` fragt lobid-gnd mit nichts als den GND-Nummern, eine Anfrage je Sekunde |
| M19 gpt-6-luna | `mc_aufloesung.py <out.json> --llm <gold.yaml>…`, `mc_treffer_llm.py <out.json> --korpus` und `mc_llm_sparvarianten.py <out.json> llm`, jeweils mit `B_API_MODEL=gpt-6-luna`; `mc_latenz_modelle.py <out.json> gpt-5.6-luna gpt-6-luna` (je Lauf eine neue Datei), alle aus dem Projektordner | venv dieses Projekts | `gpt-6-luna`, zusammen rund 145.000 Tokens; der Latenzvergleich beide Modelle mit je acht kurzen Aufrufen |
| M21 Artikelwahl echter Materialien | `mc_material_stichprobe.py <entwurf.yaml>` zieht die Stichprobe für `eval/materialwahl`, `mc_material_artikelwahl.py <out.json> [--ohne-llm]` misst, beide aus dem Projektordner | venv dieses Projekts | S4 mit dem Modell von `B_API_MODEL` (`gpt-6-luna`), rund 470 Tokens je Material; liest die Materialien anonym aus der WLO-Produktion |
| M22 Lehrplanbezüge von Teil 2 | `mc_lehrplan_treffer.py <out.json> <bogen.json>` zieht die Stichprobe (den Bogen mit den Texten der Elemente außerhalb des Repositorys ablegen), `mc_lehrplan_auswertung.py <m22.json> <noten.yaml> [<zweite noten.yaml>]` rechnet, beide aus dem Projektordner | venv dieses Projekts, `lehrplan.db` in `STATE_DIR` | keins; das LLM bleibt aus |
| M23 Kompendium aus Material-Metadaten | `mc_material_kompendium.py <out.json> <bogen.json>` baut je Material sechs Kompendien (den Bogen mit Beschreibungen und Artikelanfängen außerhalb des Repositorys ablegen), `mc_material_kompendium_auswertung.py <m23.json> <noten.yaml> [<zweite noten.yaml>]` rechnet Anteile, Precision, Recall und F1, beide aus dem Projektordner | venv dieses Projekts | `gpt-6-luna` für K0b, KL und KEa, zusammen 113.476 Tokens für 40 Materialien; liest die Materialien anonym aus der WLO-Produktion |
| M24 Artikel eines Materials ohne LLM | `mc_material_embedding.py <modell> <out.json> [<einträge>]` läuft blockweise über alle Einträge der Wikipedia-ZIM, ohne Index auf der Platte (`<modell>`: das Model2Vec-Modell des Dienstes, im Image `/models/m2v`), `mc_material_embedding_auswertung.py <m24.json> <noten.yaml>` rechnet, beide aus dem Projektordner | venv dieses Projekts, rund 1 GB Arbeitsspeicher, ein Lauf rund 15 Minuten | keins; liest die Materialien anonym aus der WLO-Produktion |
| M25 Einbau nach M21 bis M24 | `mc_korpus_verlinkung.py <out.json> [--llm] [--m2v <modell>]` misst Verlinkung und LLM-Prüfung der Nebenartikel an den 20 Themen des Begriffs-Golds, mit `--m2v` auch die gedruckten Absätze; `mc_material_stichprobe.py <entwurf.yaml> 4 --saat 25 --ohne eval/materialwahl/materialien.yaml` zog die zweite Stichprobe; `mc_material_knoten.py <gold.yaml> <out.json> [--noten <noten.yaml>]` misst die Artikelwahl des Dienstes für Materialien, `--auswertung <out.json>` druckt die Tabellen eines Laufs; `mc_zeit_artikelwahl.py <out.json> rule-based llm --m25 [--m2v <modell>]` misst die Zeit an 30 neuen Themen; alle aus dem Projektordner (`<modell>`: das Model2Vec-Modell des Dienstes, wenn der Cache des Hubs keins hat) | venv dieses Projekts | `gpt-6-luna` für `--llm`, die Wege L und BL und den Weg `llm`: Nebenartikel 23.490 Tokens, Artikelwahl der Materialien rund 80.000 je Lauf über beide Golds, Zeitmessung 27.931; liest die Materialien anonym aus der WLO-Produktion |
| M27 Die vier Profile | `mc_profile_zuordnung.py <out.json> --m2v <modell>` misst die Zuordnung von `llm-free` und `balanced` auf den zehn Goldthemen; `mc_profile.py <out.json> <texte-ordner> --m2v <modell>` erzeugt sechs neue Themen in allen vier Profilen (Tokens; die Texte für M28 bleiben außerhalb des Repositorys); `mc_profile_zeit.py <out.json> --m2v <modell>` misst die Zeit, jedes LLM-Profil auf sechs eigenen Themen; alle aus dem Projektordner | venv dieses Projekts | `gpt-6-luna`: Gold 8.683 Tokens je Lauf, gleiche Themen 429.905, Zeitmessung 401.637 |
| M28 Lesefassung | `mc_richter_auswertung.py text <schlüssel.json> <urteil1.json> <urteil2.json> <out.json>` wertet die blinden Urteile aus; Bögen und Schlüssel entstehen aus den Texten von `mc_profile.py` und bleiben außerhalb des Repositorys | beliebiges Python | keins; zwei Claude-Gutachter lesen die Bögen |
| M29 QA-Paare je Profil | `mc_qa_profile.py parse <out.json>` im Image (spaCy), `mc_qa_profile.py llm <parse.json> <out.json>` auf dem Entwicklungsrechner, `mc_qa_profile.py sheet …` schreibt Bogen und Schlüssel, `mc_richter_auswertung.py qa …` wertet aus; `parse-based` gibt es seit D57 nicht mehr, das Skript braucht einen Stand bis `1ae63db` | Image und venv dieses Projekts | `gpt-6-luna`, 9.496 Tokens |
| M30 QA-Stufen nach D55 | `mc_qa_stufen.py free <out.json>` im Image (spaCy und die zwei Modelle: Teil 1 von `llm-free` zu sechs Themen, dann die Paare der Regeln, der alten Vorlagen, des Parse und der Modelle), `mc_qa_stufen.py llm <free.json> <out.json>` auf dem Entwicklungsrechner, `mc_qa_stufen.py sheet <free.json> <llm.json> <ordner>` schreibt zwei Bögen und den Schlüssel, `mc_qa_stufen.py summary <free.json> <llm.json> <out.json>` zählt je Stufe, `mc_richter_auswertung.py qa …` wertet die Urteile aus; `models` und `parse-based` gibt es seit D57 nicht mehr, das Skript braucht einen Stand bis `1ae63db` | Image und venv dieses Projekts | `gpt-6-luna` für `llm`, 15.353 Tokens gemeldet; die vier Themen von M29 kamen aus dem Zwischenspeicher der b-api |
| M31 Modellwissen mit Prompt v2 | `mc_modellwissen_v2.py run <out.json> <texte-ordner> --m2v <modell>` erzeugt die sechs Themen von M27 in `best-quality-generated` (die Texte bleiben außerhalb des Repositorys), `mc_modellwissen_v2.py sheet <texte M27> <texte> <ordner>` schreibt die blinden Bögen und zwei Schlüssel, `mc_modellwissen_v2.py evaluate <schlüssel.json> <urteil1.json> <urteil2.json> <out.json>` ordnet die Urteile den Fassungen zu; alle aus dem Projektordner | venv dieses Projekts | `gpt-6-luna`, 243.338 Tokens gemeldet; Artikelwahl und Zuordnung kamen aus dem Zwischenspeicher der b-api |
| Zusammenfassungen von M9 bis M15 | `mc_zusammenfassung.py <ergebnisse-ordner>` | beliebiges Python | keins; rechnet nur aus den Rohdaten |
| Grafiken der Entscheidungsvorlage | `mc_grafiken.py <ergebnisse-ordner> <bilder-ordner>`, Ziel `docs/entwicklung/bilder` | venv dieses Projekts (liest das Gold aus `eval/artikelwahl`) | keins; reines SVG ohne Bibliothek |

`alter_linker.py` (der Linker-Prompt des alten Dienstes, wortgleich), `materialwege.py` (Entitäten-Rangfolge,
LLM-Frage nach dem Artikel eines Materials), `noten.py` (Übereinstimmung zweier Beurteiler) und `artikelmengen.py`
(Precision, Recall und F1 gedruckter Artikel gegen die passenden) sind keine Skripte: Die Messungen importieren sie,
damit mehrere Skripte denselben Prompt, dieselbe Rangfolge und dieselbe Rechnung nutzen.

Für den alten Dienst gilt: Mit seinem eigenen User-Agent wird er von Wikipedia abgewiesen (Szenario „wie
ausgeliefert“). Für den besten Fall setzt man `PROJECT_NAME` auf einen Namen mit Kontaktadresse; der Code bleibt
unverändert. Die Umgebung des alten Dienstes entsteht mit `uv sync --frozen --no-dev` in `alterCode/compendious`.

`new_part1_check.py` prüft jeden Satz gegen den Absatz, auf den seine Belegnummer zeigt. Die Laufzeiten in M3 stammen
aus einem ersten Lauf mit einer früheren Fassung, die denselben Server abfragte und Sätze nur im ganzen Korpus
suchte; beide Läufe ergaben dieselben Sätze.

## Ablauf von M4 und M5

Alle Verfahren laufen durch den Weg von `CompendiumService.match` und werden am Goldstandard gemessen. Die
Zwischendateien entstehen in einem Arbeitsordner außerhalb des Repositorys, weil sie die Absatztexte enthalten.

1. `mc_export.py export.json`: baut den Korpus der zehn Goldthemen mit dem Code 2.0.0 und hält Goldlabels und die
   Zuordnung der Strategien des Dienstes fest, in beiden Kandidatenpools.
2. `mc_variants_v200.py export.json export_var.json`: weitere Kombinationen der Ranker des Dienstes, darunter
   Model2Vec allein und BM25 + Model2Vec. Das Skript baut `hybrid_light` aus seinen Bestandteilen nach und bricht ab,
   wenn der Nachbau eine andere Auswahl ergibt als der Dienst.
3. `mc_llm_matcher.py export_var.json export_llm.json llm_roh.json <token-grenze>`: das LLM ordnet die gelabelten
   Absätze zu (M5, erste Messung).
4. In der venv der Testapp, Arbeitsverzeichnis `kompendium-test`: `mc_model_scores.py export.json minilm
   scores_minilm.json`, ebenso mit `cross_encoder`, dann `mc_model_scores.py export.json qa scores_qa.json
   scores_minilm.json`. Die Modelle bewerten dieselben Texte wie die Ranker des Dienstes.
5. `mc_model_variants.py export_llm.json export_alle.json scores_minilm.json scores_cross_encoder.json
   scores_qa.json`: die Modellwerte als Ranker im Ablauf des Dienstes, dazu das Umsortieren durch den Cross-Encoder.
6. `mc_llm_dienst.py m5_llm_zuordnung.json llm_dienst.json <token-grenze>`: `matcher=llm` durch den Dienst selbst
   auf dem Goldpool, verglichen mit der ersten Messung; dann `mc_llm_dienst_merge.py export_alle.json llm_dienst.json
   export_final.json`.
7. `mc_final_tables.py export_final.json scores_minilm.json scores_cross_encoder.json scores_qa.json llm_roh.json
   tabellen.json llm_dienst.json`: die Tabellen der Seiten 3 und 5, Rechenzeiten und die Hochrechnung der LLM-Kosten.
8. `mc_eval.py export_final.json`: die vollständige Ausgabe mit beiden Kandidatenpools.

## Ergebnisdateien

| Datei | Inhalt |
|---|---|
| `ergebnisse/README.md` | alle Messungen auf einen Blick: Frage, Ergebnis, Dateien; Lesehinweise |
| `ergebnisse/m1_laufzeit_server.json` | M1, alle 47 Anfragen an den Server mit Schrittzeiten |
| `ergebnisse/m1_laufzeit_entwicklungsrechner.json` | dieselbe Messung im lokalen Container |
| `ergebnisse/m2_alter_dienst.json` | M2, Auswertung je Lauf: Quellen, Begriffsklärungen, Sätze, Belege |
| `ergebnisse/m2_alter_dienst_details.json` | M2, Begriffe, Tokenaufteilung, Aufrufe, Wikipedia-Status je Thema |
| `ergebnisse/m3_teil1_neu_laufzeit.json` | M3, erster Lauf: Dauer, Umfang, Quellen |
| `ergebnisse/m3_teil1_neu_belege.json` | M3, zweiter Lauf: Belegprüfung Satz für Satz |
| `ergebnisse/m3_pruefungen.txt` | Hauptartikel, Begriffsklärungen, Wiederholbarkeit, F1 je Baustein |
| `ergebnisse/m4_goldstandard.txt` | M4 und M5, Ausgabe von `mc_eval.py`: Klassifikation und Auswahl aller Verfahren, beide Kandidatenpools |
| `ergebnisse/m4_tabellen.json` | M4 und M5, Ausgabe von `mc_final_tables.py`: Kennzahlen je Verfahren und Pool, Rechenzeiten, LLM-Hochrechnung |
| `ergebnisse/m5_llm_zuordnung.json` | M5, erste Messung: jeder LLM-Aufruf mit Dauer und Tokens, die Antwort je Absatz als Absatzkennung, Baustein und Sicherheit |
| `ergebnisse/m5_llm_dienst.json` | M5, `matcher=llm` im Dienst: je Thema Aufrufe, Tokens, Rückfälle, Zuordnung und Auswahl; Vergleich mit der ersten Messung |
| `ergebnisse/m6_richter.json` | M6, erster Lauf: Kennzahlen der Verfahren des Dienstes, Aufrufe und Tokens des Laufs |
| `ergebnisse/m6_richter_varianten.json` | M6, zweiter Lauf für Model2Vec allein und BM25 + Model2Vec: Kennzahlen aller Verfahren des Dienstes, Aufrufe und Tokens dieses Laufs |
| `ergebnisse/m6_richter_je_thema.txt` | M6, die Verfahren des Dienstes je Thema |
| `ergebnisse/m7_xml_dump.txt` | M7, Stichproben und Größen der Dump-Varianten |
| `ergebnisse/m8_artikelwahl.json` | M8, Auflösung jeder Anfrage; Korpus der 20 Themen mit Herkunft, Absätzen und gedruckten Absätzen je Artikel; Artikel des alten Dienstes |
| `ergebnisse/m8_artikel_richter.json` | M8, Note des Richters je Artikel, Aufrufe und Tokens |
| `ergebnisse/m8_artikelwahl.txt` | M8, alle Tabellen, falsch aufgelöste Anfragen, unpassende Artikel mit Absätzen, Kreuztabelle Gold und Richter |
| `ergebnisse/m9_aufloesung_alt.json`, `m9_aufloesung_regeln.json`, `m9_aufloesung_llm.json` | M9, Auflösung jeder Anfrage der drei Goldsätze: alter Stand, Regeln, Regeln und LLM, mit Weg, Sicherheit und Alternativen |
| `ergebnisse/m9_artikelwahl.txt` | M9 lesbar: richtig je Goldsatz und Art der Anfrage, wie sicher die Regeln sind, was das LLM änderte, alle geänderten und falschen Anfragen |
| `ergebnisse/m10_trefferfilter.json` | M10, die 47 Volltexttreffer mit Note und Filtermerkmalen |
| `ergebnisse/m10_treffer_llm_allein.json`, `m10_treffer_llm_korpus.json` | M10, Note des LLM je Treffer, allein und mit dem ganzen Korpus benotet |
| `ergebnisse/m10_treffer_wirkung.json` | M10, gedruckte Absätze nach Note und gefüllte Bausteine je Thema, mit und ohne die mit 0 benoteten Treffer |
| `ergebnisse/m10_volltexttreffer.txt` | M10 lesbar: jeder Filter mit behaltenen und verworfenen Treffern, Note des LLM gegen Gold, Wirkung auf das gedruckte Kompendium |
| `ergebnisse/m11_zusatzquellen.json`, `m11_zusatzsuche.json` | M11, Seiten aus Wikibooks und Wikiversity je Thema, ihre gedruckten Absätze und Bausteine, das Urteil der Trefferprüfung |
| `ergebnisse/m11_zusatzquellen.txt` | M11 lesbar: Überblick der Wege, gefüllte Bausteine je Thema, alle Seiten, aus denen gedruckt wurde |
| `ergebnisse/m12_beschreibungen_lokal.json`, `m12_beschreibungen_llm.json` | M12, sc26 gegen schärfere Beschreibungen, lokal und mit `matcher=llm` |
| `ergebnisse/m12_sparvarianten.json`, `m12_sparvarianten_rotiert.json` | M12, Regeln und die Wege der LLM-Zuordnung mit F1 je Baustein, Tokens und Sekunden je Thema; der zweite Lauf mit gedrehten Pools |
| `ergebnisse/m12_zuordnung.txt` | M12 lesbar: Beschreibungsvarianten, alle Wege der LLM-Zuordnung mit Tokens und Sekunden, F1 je Baustein in beiden Läufen |
| `ergebnisse/m13_zeit_alt.json`, `m13_zeit_alt_zweiter_lauf.json`, `m13_zeit_neu.json`, `m13_zeit_neu_regeln_zweiter_lauf.json` | M13, je Thema und Weg die Sekunden, Phasen, Tokens, Titel und verworfenen Treffer |
| `ergebnisse/m13_zeit_zuordnung.json` | M13, `matcher=llm` gegen `hybrid_light` an fünf ganzen Kompendien: Sekunden, Phasen, Tokens, Rückfälle |
| `ergebnisse/m13_laufzeit.txt` | M13 lesbar: Teil 1 je Stand und Weg, Phasen des Audits, alle 30 Themen mit Titel und verworfenen Treffern, `matcher=llm` gegen `hybrid_light` |
| `ergebnisse/m14_zeit_zuordnung.json` | M14, `matcher=llm` mit D39 gegen `hybrid_light` an fünf neuen Kompendien: Sekunden, Phasen, Tokens, Aufrufe, Rückfälle mit Grund |
| `ergebnisse/m14_budget_nachrechnung.json` | M14, je Thema aus M13 und M14 die Reservierung jedes Stapels und der Rückfall ohne Warten |
| `ergebnisse/m14_zuordnung_budget.txt` | M14 lesbar: Nachrechnung gegen die Messungen, `matcher=llm` mit D39 je Thema und im Median |
| `ergebnisse/m15_bausteine_lokal.json` | M15, die vier lokalen Strategien in beiden Pools: Kennzahlen und F1 je Baustein |
| `ergebnisse/m16_laya.json`, `m16_laya_englisch.json` | M16, je unsichere Anfrage die Wahl von laya und der Regeln, je Volltexttreffer Goldnote, Ja-Wahrscheinlichkeit und Dreiwahl, dazu die Zeiten; ohne Artikeltext |
| `ergebnisse/m17_alte_artikelwahl_gpt41mini.json`, `m17_alte_artikelwahl.json` | M17, je Anfrage die Begriffe des alten Wegs mit Artikel, Weg des Nachschlagens, Begriffsklärung und GND, dazu Tokens, Sekunden und der Hauptartikel der Regeln; ohne Artikeltext |
| `ergebnisse/m18_entitaeten_gnd.json`, `m18_gnd_stichprobe.json` | M18, je Thema die verknüpften Entitäten mit Art und den Kennungen des Endpunkts (GND, Normdaten-Art, VIAF, Wikidata); die Stichprobe mit Name und Wikidata-Verknüpfung des GND-Datensatzes bei lobid-gnd |
| `ergebnisse/m19_aufloesung_gpt6.json`, `m19_treffer_gpt6.json`, `m19_zuordnung_gpt6.json` | M19, dieselben Dateien wie in M9, M10 und M12, gerechnet mit `gpt-6-luna` |
| `ergebnisse/m19_latenz.json`, `m19_latenz_2.json` | M19, zwei Läufe: je Aufruf Modell, Thema, Sekunden und Tokens des gleichzeitigen Latenzvergleichs |
| `ergebnisse/m21_materialwahl.json` | M21, je Material die Artikel der fünf Wege und ob sie im Gold stehen; Titel und Entscheidungen, keine Beschreibungen |
| `ergebnisse/m23_material_kompendium.json` | M23, je Material und Weg Status, Hauptartikel, gedruckte Absätze je Quellartikel, Bausteine, Länge, Teil 2, Sekunden und Tokens, dazu die Entitäten der Entitäten-Wege; Titel und Zahlen, keine Beschreibungen und Artikeltexte |
| `ergebnisse/m24_material_embedding.json` | M24, je Material und Weg die ersten 20 Artikel mit ihrer Ähnlichkeit, die Ähnlichkeit der in M23 benoteten Artikel, der Hauptartikel von KL als Anker, ob ein Artikel mit ihm verlinkt ist und welche Wege von M23 ihn druckten, dazu die Laufzeiten; Titel und Zahlen, keine Beschreibungen und Artikeltexte |
| `ergebnisse/m25_korpus_verlinkung.json` | M25, je Thema der Hauptartikel und jeder Nebenartikel mit Herkunft, Note aus M8, Verlinkung mit dem Hauptartikel und der Zeit dafür, die Noten des LLM für den ganzen Korpus und für den ohne unverlinkte Volltexttreffer mit ihren Tokens, dazu je Korpus die gedruckten Absätze nach Note und die gefüllten Bausteine; Titel und Zahlen, keine Artikeltexte |
| `ergebnisse/m25_knoten_materialien.json`, `m25_knoten_materialien_m25.json` | M25, je Material der beiden Golds und Weg (K0, R, L, B, BR, BL) der Artikel, ob das Gold ihn akzeptiert, Sekunden und Tokens, wie der Dienst ihn fand, ein Rückfall und der Titel, den das LLM nannte, bei BR und BL der Artikel des Materials, ob er in den Korpus kam, und seine Note aus M23; zweiter Lauf, die Zeiten von L und BL großenteils aus dem Zwischenspeicher der b-api; Titel und Entscheidungen, keine Beschreibungen |
| `ergebnisse/m25_knoten_materialien_m25_vor_korrektur.json` | M25, dasselbe für Gold 2 im ersten Lauf, vor der Korrektur der zwei Fehler, die diese Stichprobe aufdeckte; seine Zeiten von L und BL sind Modellzeit |
| `ergebnisse/m25_zeit_artikelwahl.json` | M25, wie `m13_zeit_neu.json` je Thema und Weg die Sekunden, Phasen, Tokens, Titel und verworfenen Nebenartikel, dazu die Zusammenfassung beider Wege |
| `ergebnisse/m27_zuordnung_gold.json` | M27, je Goldthema und Profil Hauptartikel, Absätze, bewertete und veraltete Labels, macro-F1 (alle Absätze, Goldpool, gedruckt), die verworfenen Nebenartikel und Tokens, dazu gepoolt je Profil; Titel und Zahlen, keine Absatztexte |
| `ergebnisse/m27_profile_tokens.json` | M27, je Thema und Profil Sekunden (durch den Zwischenspeicher der b-api verzerrt), Phasen, Aufrufe, Tokens, Hauptartikel, Bausteine, Absätze, Lehrplanelemente, was die LLM-Schritte taten, Sätze mit Modellwissen; Titel und Zahlen, keine Texte |
| `ergebnisse/m27_profile_zeit.json` | M27, je Profil und Thema dieselben Felder, jedes LLM-Profil auf eigenen Themen, `llm-free` auf allen; die Themensätze und die Mediane von `llm-free` je Satz |
| `ergebnisse/m28_lesefassung.json` | M28, je Thema und Gutachter die Noten beider Profile, Füllsätze, Zahl der Fachfehler, Vorzug, und je Satz mit Modellwissen Richtigkeit und Nutzen; die Auswertung; keine Texte |
| `ergebnisse/m29_qa.json` | M29, je Text Zeichen, Paare, Sekunden und Tokens beider Verfahren, das Verfahren je Paar-Kennung und die Urteile beider Gutachter mit Auswertung; keine Texte und Paare |
| `ergebnisse/m30_qa.json` | M30, je Thema und Stufe Paare, Frageanfänge, Zeitfragen und Sekunden, die Tokens des LLM und die Zeichen des Textes, das Verfahren je Paar-Kennung, die Urteile beider Gutachter und die Auswertung mit und ohne die drei Paare vor dem Fix `2542932`; keine Texte und Paare |
| `ergebnisse/m31_modellwissen.json` | M31, je Thema Tokens und Sätze mit Modellwissen beider Fassungen, der Schlüssel der blinden Bögen, die Urteile beider Gutachter (Noten, Füllsätze, Fachfehler, Vorzug, je Satz mit Modellwissen Richtigkeit und Nutzen) und die Auswertung; keine Texte und Sätze |
| `ergebnisse/m22_lehrplan_treffer.json` | M22, je Thema Stichwörter, Fachwörter und Elementzahlen beider Läufe, je Stichwort und Fundort, dazu die Stichprobe mit IRI, Schicht und Stichwort; keine Texte der Elemente |
| `ergebnisse/m20_entitaeten_genitiv.json` | M20, dieselbe Form wie `m18_entitaeten_gnd.json`, gerechnet mit der Genitiv-Regel (D46) |
| `ergebnisse/m15_bausteine_lokal.txt` | M15 lesbar: Kennzahlen je Strategie, F1 je Baustein neben den LLM-Läufen aus M12 |
| `ergebnisse/nebenwerte.txt` | Testsuite, Entitätenerkennung, Kiefer-Alternativen, Länge von Teil 2, Knotenzeilen von Teil 3 |
| `ergebnisse/zim_suche.json` | Suchzeiten des Wikipedia-Archivs |

In `m4_goldstandard.txt` zeigt die Spalte `ms` nur die Zeit im Ablauf des Dienstes. Für die Modelle der Testapp kommt
die Zeit hinzu, in der sie ihre Paare bewerten; sie steht in `m4_tabellen.json` unter `model_seconds`. Beim LLM steht
dort die mittlere Wandzeit je Thema.

Die Rohausgaben des alten Dienstes mit den Wikipedia-Auszügen, die Zwischendateien mit Absatztexten und der Pool
der Artikelanfänge für M8 bleiben außerhalb des Repositorys. Das Gold für M8 liegt in `eval/artikelwahl/`.
