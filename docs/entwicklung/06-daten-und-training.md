# Daten für später: Protokoll, Training, Paket

[Übersicht](README.md) · Stand 24.09.2026 · Bewertung, nichts davon ist umgesetzt

## Ausgangslage

Die lokalen Verfahren der Zuordnung kommen am Goldstandard auf macro-F1 0,43 bis 0,45, das LLM auf rund 0,7 (0,66
bis 0,73 in vier Läufen, [Messprotokoll](05-messprotokoll.md), M5 und M12). Bei der Artikelwahl holt das LLM die
Fälle, in denen die Regeln unsicher sind (M9, M10). Beides kostet je Anfrage Tokens und Zeit (M13). Ein lokal
trainiertes Modell könnte einen Teil dieses Abstands schließen, ohne Tokens zur Laufzeit. Dafür braucht es Trainingsdaten, und die fehlen: Der Goldstandard hat 603
Absätze aus zehn Themen. Eine logistische Regression darauf kam am 18.09.2026 bei Kreuzvalidierung über die Themen auf
höchstens 0,35 (`03-matching.md`). Das spricht gegen die Datenmenge, nicht gegen die Idee.

## Woher Trainingsdaten kommen können

| Weg | Was entsteht | Aufwand | Wert |
|---|---|---|---|
| **LLM-Entscheidungen offline erzeugen** (Destillation) | Ein Stapellauf ruft den Dienst für eine Themenliste mit `matcher=llm` und `article_choice=llm` auf; die Entscheidungen des Modells sind die Labels. | keine Änderung am Dienst; rund 35.000 Tokens je Thema (M14, seit D39 ohne Rückfall am Budget), 200 Themen also rund 7 Millionen, dreieinhalb Tage des Tagesbudgets von 2 Millionen | Labels in der Güte des LLM (rund 0,7 am Gold), ohne Nutzerdaten |
| **Protokoll im Betrieb** | je Kompendium die Entscheidungen, die der Dienst ohnehin trifft: Auflösung mit Kandidaten und `method`, Korpus mit Herkunft und Trefferprüfung, je Absatz Regelbaustein mit Score, LLM-Baustein mit Sicherheit, gedruckter Baustein | Schalter, Schreibpfad im `STATE_DIR`, Rotation, Export | nur dort neu, wo LLM-Schalter laufen; im Regelmodus protokolliert es, was die Regeln schon wissen |
| **Redaktionelle Rückmeldung** | Unterschiede zwischen erzeugtem und redaktionell geprüftem Kompendium: Absatz behalten, gestrichen, verschoben | Absprache mit der Redaktion, wie geprüfte Texte zurückkommen; der Dienst liest `existing_markdown` mit `redaktionell-geprüft` schon heute | die einzigen Labels, die kein Modell liefern kann |

Texte muss ein Protokoll nicht speichern. Der Vorspann jedes Kompendiums nennt die Archive samt Version
(`zim_snapshot`), und mit Artikelpfad und Absatznummer lässt sich jeder Absatz aus demselben Archiv wieder lesen. Das
hält die Daten klein und umgeht die Frage, wie Wikipedia-Text weitergegeben wird (CC BY-SA verlangt Namensnennung
und Weitergabe unter gleichen Bedingungen).

## Was ein Paket sein könnte

- **Datenpaket:** versionierte JSONL-Exporte für zwei Aufgaben, Absatz zu Baustein und Artikel zu Relevanz, mit einem
  Datenblatt: Herkunft der Labels (Gold, LLM, Redaktion), Archivversionen, Lizenz. Ein Export-Befehl der CLI könnte
  sie aus Protokoll oder Stapellauf erzeugen.
- **Trainingspaket:** ein eigenes Repository, das die Exporte liest, ein kleines Modell trainiert und eine Modelldatei
  schreibt, die der Dienst als weitere Zuordnungsstrategie lädt. Naheliegend sind die vorhandenen Model2Vec-Vektoren
  mit einem Klassifikator je Baustein, oder ein kleiner deutscher Encoder, feinjustiert. Die Strategie würde wie alle
  anderen am Goldstandard gemessen, bevor sie Standard werden darf.

## Datenschutz und Lizenz

Anfragen enthalten Thema, Fach, Sammlungs-IDs und Schalter, keine Personendaten. Ein Protokoll schreibt keine
IP-Adressen, Schlüssel oder Tokens. Wikipedia- und Klexikon-Text steht unter CC BY-SA; wer Absätze statt Verweisen
speichert und weitergibt, muss die Lizenz mitführen.

## Empfehlung

1. **Jetzt kein Protokoll der Zuordnung im Betrieb.** Solange `matcher=llm` selten läuft, sammelt es vor allem
   Regelentscheidungen. Anders die Artikelwahl: Mit der Stufe `balanced` benotet das LLM bei fast jeder Anfrage die
   Korpusartikel und entscheidet unsichere Themen; Standard ist sie seit D40 nicht mehr. Ein kleines Protokoll nur
   dafür (Thema, Fach, Kandidaten, Noten, Wahl) wäre der billigste Anfang eines Datensatzes, mit dem sich die
   Trefferprüfung später lokal lernen ließe.
2. **Erst ein Destillationsversuch offline:** 50 bis 100 Themen mit `matcher=llm` (1,5 bis 3 Millionen Tokens), ein
   Schülermodell darauf trainieren und am Goldstandard über die Themen hinweg messen. Erreicht es lokal 0,6 macro-F1
   oder mehr, lohnen Datenpaket, Trainingspaket und ein Protokoll für LLM-Anfragen.
3. **Parallel mit der Redaktion klären,** wie geprüfte Kompendien zurückkommen. Das sind die Daten, die sich mit
   keinem Stapellauf ersetzen lassen.
