# Messskripte zur Entwicklungsdokumentation

Die Skripte zu den Messungen vom 23. und 24.09.2026 im [Messprotokoll](../05-messprotokoll.md). Sie sind für den
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
| M12 Bausteinbeschreibungen und LLM-Zuordnung | `mc_varianten.py <out.json> [--llm] [--llm-pool gold] <label=template:strategie>…` mit `sc26_beschreibungen.json`; `mc_llm_sparvarianten.py <out.json> <weg>…` | venv dieses Projekts | `gpt-5.6-luna`, 70.000 bis 150.000 Tokens je LLM-Variante |

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
| `ergebnisse/m10_trefferfilter.json` | M10, die 47 Volltexttreffer mit Note und Filtermerkmalen |
| `ergebnisse/m10_treffer_llm_allein.json`, `m10_treffer_llm_korpus.json` | M10, Note des LLM je Treffer, allein und mit dem ganzen Korpus benotet |
| `ergebnisse/m10_treffer_wirkung.json` | M10, gedruckte Absätze nach Note und gefüllte Bausteine je Thema, mit und ohne die mit 0 benoteten Treffer |
| `ergebnisse/m11_zusatzquellen.json`, `m11_zusatzsuche.json` | M11, Seiten aus Wikibooks und Wikiversity je Thema, ihre gedruckten Absätze und Bausteine, das Urteil der Trefferprüfung |
| `ergebnisse/m12_beschreibungen_lokal.json`, `m12_beschreibungen_llm.json` | M12, sc26 gegen schärfere Beschreibungen, lokal und mit `matcher=llm` |
| `ergebnisse/m12_sparvarianten.json` | M12, Regeln und drei Wege der LLM-Zuordnung mit F1 je Baustein und Tokens |
| `ergebnisse/nebenwerte.txt` | Testsuite, Entitätenerkennung, Kiefer-Alternativen, Länge von Teil 2, Knotenzeilen von Teil 3 |
| `ergebnisse/zim_suche.json` | Suchzeiten des Wikipedia-Archivs |

In `m4_goldstandard.txt` zeigt die Spalte `ms` nur die Zeit im Ablauf des Dienstes. Für die Modelle der Testapp kommt
die Zeit hinzu, in der sie ihre Paare bewerten; sie steht in `m4_tabellen.json` unter `model_seconds`. Beim LLM steht
dort die mittlere Wandzeit je Thema.

Die Rohausgaben des alten Dienstes mit den Wikipedia-Auszügen, die Zwischendateien mit Absatztexten und der Pool
der Artikelanfänge für M8 bleiben außerhalb des Repositorys. Das Gold für M8 liegt in `eval/artikelwahl/`.
