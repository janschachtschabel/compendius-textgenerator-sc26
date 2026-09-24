# Ergebnisse der Messungen M1 bis M20

Rohdaten (`.json`) und lesbare Zusammenfassungen (`.txt`) der Messungen vom 23. und 24.09.2026. Aufbau und Deutung
stehen im [Messprotokoll](../../05-messprotokoll.md), die Skripte eine Ebene höher ([messung](../README.md)). Die
Zusammenfassungen von M9 bis M15 rechnet `mc_zusammenfassung.py` aus den Rohdaten nach, die Grafiken der
[Entscheidungsvorlage](../../07-entscheidungsvorlage.md) in `docs/entwicklung/bilder/` zeichnet `mc_grafiken.py`:

```
python docs/entwicklung/messung/mc_zusammenfassung.py docs/entwicklung/messung/ergebnisse
python docs/entwicklung/messung/mc_grafiken.py docs/entwicklung/messung/ergebnisse docs/entwicklung/bilder
```

## Auf einen Blick

| Messung | Frage | Ergebnis | Zusammenfassung | Rohdaten |
|---|---|---|---|---|
| M1 | Wie schnell ist der neue Dienst auf dem Server? | Teil 1 und 2 im Median 2,81 s, im zweiten Durchgang 1,98 s; ohne Sprachmodell | – | `m1_laufzeit_server.json`, `m1_laufzeit_entwicklungsrechner.json` |
| M2 | Was leistet der alte Dienst v0.2.0? | wie ausgeliefert 374 s und keine Quelle; im besten Fall Median 34,8 s, 7.913 Tokens, 21 % der Sätze durch ihre Quelle gestützt | – | `m2_alter_dienst.json`, `m2_alter_dienst_details.json` |
| M3 | Hält Teil 1 seine Belege? | 432 von 432 Sätzen stehen wörtlich im zitierten Absatz; Teil 1 im Median 2,0 s | `m3_pruefungen.txt` | `m3_teil1_neu_laufzeit.json`, `m3_teil1_neu_belege.json` |
| M4 | Welches lokale Verfahren ordnet am besten zu? | `hybrid_light` mit Model2Vec: macro-F1 0,45 in 0,30 s je Thema; die Modelle der Testapp schlechter, bei 4 bis 73 s je Thema | `m4_goldstandard.txt` | `m4_tabellen.json` |
| M5 | Wie gut ordnet ein LLM zu? | macro-F1 0,63 (Skript) und 0,66 (`matcher=llm` im Dienst) statt 0,43; rund 240 Tokens je Absatz, 7,5 s je Thema | `m4_goldstandard.txt` | `m5_llm_zuordnung.json`, `m5_llm_dienst.json` |
| M6 | Bestätigt ein blinder Richter die Reihenfolge? | Standard 62 % klar, 28 % falsch; die lexikalischen Varianten dicht beieinander, Model2Vec allein 49 % klar | `m6_richter_je_thema.txt` | `m6_richter.json`, `m6_richter_varianten.json` |
| M7 | Wie groß ist der XML-Dump entpackt? | hochgerechnet 32,0 GB (Faktor 3,88) | `m7_xml_dump.txt` | – |
| M8 | Trifft die Artikelwahl, passt der Korpus? | Hauptartikel 45 von 59, mehrdeutig mit Fach 6 von 16; 6 % unpassende Korpusartikel, beim alten Dienst 14 % | `m8_artikelwahl.txt` | `m8_artikelwahl.json`, `m8_artikel_richter.json` |
| M9 | Was bringen schärfere Regeln und `article_choice=llm`? | über drei Goldsätze 66, 86 und 91 von 94 Anfragen richtig; sichere Regeln 73 von 76, unsichere 13 von 18, mit dem LLM 18 von 18; rund 950 Tokens je Aufruf | `m9_artikelwahl.txt` | `m9_aufloesung_alt.json`, `m9_aufloesung_regeln.json`, `m9_aufloesung_llm.json` |
| M10 | Wie fallen unpassende Volltexttreffer heraus? | nur das LLM mit dem ganzen Korpus trennt: 11 von 16 unpassenden Treffern fallen, kein passender; gedruckt aus unpassenden Artikeln 10 statt 26 Absätze | `m10_volltexttreffer.txt` | `m10_trefferfilter.json`, `m10_treffer_llm_allein.json`, `m10_treffer_llm_korpus.json`, `m10_treffer_wirkung.json` |
| M11 | Helfen Wikibooks und Wikiversity? | Volltextsuche: +1 gefüllter Baustein in 20 Themen, mit Trefferprüfung +3; verworfen | `m11_zusatzquellen.txt` | `m11_zusatzquellen.json`, `m11_zusatzsuche.json` |
| M12 | Schärfere Beschreibungen, günstigere LLM-Zuordnung? | Beschreibungen ohne Gewinn; 50 Absätze zu 400 Zeichen so gut wie 25 zu 700 (0,69 bis 0,73), 27 bis 29 % weniger Tokens | `m12_zuordnung.txt` | `m12_beschreibungen_lokal.json`, `m12_beschreibungen_llm.json`, `m12_sparvarianten.json`, `m12_sparvarianten_rotiert.json` |
| M13 | Was kosten die LLM-Schalter an Zeit? | `article_choice=llm` im Median 1,7 s und 927 Tokens mehr; `matcher=llm` Teil 1 im Median 12,0 statt 1,2 s, im Mittel 29.400 Tokens | `m13_laufzeit.txt` | `m13_zeit_alt.json`, `m13_zeit_alt_zweiter_lauf.json`, `m13_zeit_neu.json`, `m13_zeit_neu_regeln_zweiter_lauf.json`, `m13_zeit_zuordnung.json` |
| M14 | Fällt mit D39 noch ein Absatz am Budget zurück? | 0 statt 151 von 1.005 (altes Verfahren nachgerechnet, trifft M13 genau); im Mittel 34.500 Tokens je Kompendium; Teil 1 im Median 22,7 s bei langsamerer b-api, Themen ab fünf Stapeln mit zweiter Runde | `m14_zuordnung_budget.txt` | `m14_zeit_zuordnung.json`, `m14_budget_nachrechnung.json` |
| M15 | Wo unterscheiden sich die lokalen Strategien? | nur in Bildung, Regularien und Beruf & Wirtschaft (21 Gold-Absätze); in den großen Bausteinen höchstens 0,04 auseinander; das LLM hebt fast jeden Baustein | `m15_bausteine_lokal.txt` | `m15_bausteine_lokal.json` |
| M16 | Taugt das kleine Entscheidungsmodell laya-multilingual für Artikelwahl oder Trefferprüfung? | nein: Artikelwahl 8 von 18 unsicheren Anfragen (Regeln 13, LLM 18), Trefferprüfung auf Zufallsniveau (AUC 0,51); mit den Regeln 81 von 94 (Regeln allein 86); läuft auf der CPU mit 1,7 GB und rund 0,5 s je Entscheidung; nicht eingebaut, erst nach einem Nachtraining wieder zu prüfen | – | `m16_laya.json`, `m16_laya_englisch.json` |
| M17 | Taugt der alte Weg über Begriffe vom LLM für die Artikelwahl? | nein: der richtige Hauptartikel an erster Stelle 55 von 94, unter bis zu zehn Artikeln 58 (`gpt-5.6-luna`) bis 78 (`gpt-4.1-mini`), Regeln 86, mit LLM 91; je Anfrage 6 bis 8 s und rund 1.300 bis 1.500 Tokens; findet aber 6 der 8 Fehler der Regeln | – | `m17_alte_artikelwahl_gpt41mini.json`, `m17_alte_artikelwahl.json` |
| M18 | Wie viele verknüpfte Entitäten tragen im Archiv eine GND-Nummer? | 503 von 679 Wikipedia-Artikeln (74 %), fast alle Sachbegriffe; 30 von 30 geprüften Nummern passen zum Artikel, 4 der 30 Artikel sind falsch verknüpft; mit dem lokalen Index (D43) Wikidata bei 674 von 679, 29 von 30 wie bei lobid-gnd | – | `m18_entitaeten_gnd.json`, `m18_gnd_stichprobe.json` |
| M19 | Taugt gpt-6-luna als Nachfolger von gpt-5.6-luna? | ja: Artikelwahl 90 statt 91 von 94, Trefferprüfung 10 statt 11 von 16 unpassenden verworfen (kein passender), Zuordner macro-F1 0,703 (gpt-5.6-luna 0,694 und 0,720), Tokens gleich bis +12 % zum halben Preis je Token; je Aufruf ein Viertel bis drei Viertel langsamer | – | `m19_aufloesung_gpt6.json`, `m19_treffer_gpt6.json`, `m19_zuordnung_gpt6.json`, `m19_latenz.json`, `m19_latenz_2.json` |
| M20 | Hilft eine Genitiv-Regel beim Verknüpfen der Entitäten? | ja: 30 neue Verknüpfungen in 20 Texten, keine falsch; beide Genitivfehler von M18 behoben, Wikidata bei 677 von 682 (D46) | – | `m20_entitaeten_genitiv.json` |
| – | Nebenwerte, Suchzeiten des Archivs | Testsuite, Entitätenerkennung, Länge von Teil 2; Titelvorschlag 2,9 ms, Volltextsuche 0,4 ms | `nebenwerte.txt` | `zim_suche.json` |

## Lesehinweise

- **Zwischenspeicher der b-api.** Einen wortgleichen Prompt beantwortet die b-api aus ihrem Zwischenspeicher, mit
  derselben Antwort und denselben gemeldeten Tokens. Zeiten solcher Läufe sind keine Modellzeit; die
  Zusammenfassungen markieren sie. Unabhängige Wiederholungen brauchen geänderte Prompts, etwa andere Stapel
  (`--rotieren` in M12) oder neue Themen (M13, M14).
- **Zeiten zwischen Prozessen.** Der Dateicache des Betriebssystems verzerrt Vergleiche zwischen Läufen in
  verschiedenen Prozessen. Belastbar sind die Phasen, die das Audit je Anfrage misst, und Wiederholungen in warmem
  Zustand (M13).
- **Pools.** „Goldpool“ sind die rund 600 gelabelten Absätze der zehn Goldthemen, „voller Pool“ alle 1.632 Absätze
  ihrer Korpora. Die Zeiten im Goldpool gelten für rund 60 Absätze je Thema, nicht für ein ganzes Kompendium.
- **Was nicht im Repository liegt:** die Rohausgaben des alten Dienstes mit den Wikipedia-Auszügen, Zwischendateien
  mit Absatztexten und die Textanfänge der Seiten aus M8 und M11.
