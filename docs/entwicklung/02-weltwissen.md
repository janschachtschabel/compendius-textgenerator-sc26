# Bereich 1: Weltwissen

[Übersicht](README.md) · Messaufbau: [Messprotokoll](05-messprotokoll.md), Abschnitte M1 bis M3, M7 bis M11 und M13

Teil 1 soll gesichertes Wissen zum Thema liefern, gegliedert nach den Bausteinen des SC26-Templates. Dafür braucht es
verlässliche Quellen, die richtigen Artikel und ein Verfahren, das aus den Artikeln einen Text macht.

## Quellen: ZIM-Archive statt Live-API oder XML-Dump

Für Wikipedia gibt es vier Zugänge. Zahlen für die deutsche Wikipedia, Stand 23.09.2026:

| | Live-API (MediaWiki) | XML-Dump (Wikimedia) | HTML-Dump (Wikimedia Enterprise) | Kiwix-ZIM |
|---|---|---|---|---|
| Inhalt | JSON je Anfrage | Wikitext in XML, bz2-gepackt | gerendertes HTML als NDJSON, tar.gz | gerendertes HTML, komprimiert, mit Titel- und Volltextindex |
| Größe | – | 7,96 GB gepackt (Multistream-Variante 8,25 GB), entpackt hochgerechnet rund 32 GB | 33 GB gepackt | 14,6 GB (13,6 GiB) ohne Bilder, 5,04 Mio. Einträge |
| Sofort nutzbar? | ja, je Artikel ein Netzaufruf | nein: entpacken oder streamen, Wikitext parsen, Vorlagen bleiben unaufgelöst | nein: importieren | ja: libzim liest direkt, wahlfreier Zugriff |
| Suche | über die API | selbst bauen | selbst bauen | eingebaut: Titelvorschlag im Median 3 ms, Volltextsuche unter 1 ms (23.09., Datei im Speicher des Betriebssystems) |
| Aktualität | live | zweimal im Monat | öffentliche Reihe endet am 20.03.2025 | wie Kiwix baut; das deutsche Archiv ohne Bilder ist vom 15.01.2026 |
| Weitere Quellen | je Projekt eine eigene API | nur Wikimedia-Projekte; kein Klexikon | nur Wikimedia-Projekte | Wikipedia, Klexikon, Wikibooks, Wikiversity und viele mehr aus einem Katalog, im selben Format |
| Risiko zur Laufzeit | Sperren (403), Drosselung (429), Netz | keins | keins | keins |

Die entpackte Größe des XML-Dumps ist hochgerechnet: 541 bz2-Blöcke an 16 Stellen der Multistream-Datei wurden
entpackt, das Verhältnis liegt bei 3,9. Mit dem Multistream-Format und seiner Indexdatei lassen sich einzelne
Artikel auch ohne vollständiges Entpacken lesen, aber nur per Titel und als Wikitext; eine Volltextsuche fehlt
weiterhin.

**Warum ZIM:**

- **Direkt nutzbar.** Kein Entpacken von rund 32 GB, kein Parser für Wikitext und Vorlagen (Infoboxen, Formeln,
  Einzelnachweise), kein eigener Suchindex, keine zusätzliche Datenbank.
- **Der Index trägt die Artikelwahl.** Titel, Weiterleitungen, Vorschläge und Volltextsuche liefert das Archiv mit;
  darauf bauen Begriffsklärung, Unterartikel und die Suche je Baustein auf.
- **Eine Stelle, viele Quellen.** Kiwix pflegt Wikipedia, Klexikon, Wikibooks, Wikiversity und weitere Archive in
  einem Format und einem Katalog. Welche der Dienst nutzt, legt ein Abo-Manifest fest.
- **Betriebssicher.** Zur Anfragezeit kein Netz, keine Sperren, keine Drosselung. Neue Archive lädt ein Sidecar mit
  Prüfsumme herunter und schaltet ohne Neustart um.
- **Reproduzierbar.** Archivdatum und UUID stehen im Vorspann jedes Kompendiums (`sources_snapshot`); jede
  Belegnummer zeigt auf einen festen Stand.
- **Schnell.** Der Korpus eines Themas mit bis zu 12 Artikeln steht auf dem Server im Median nach 0,9 s.

**Der Preis:**

- 14,6 GB für Wikipedia, dazu Klexikon (135 MB). Ein Volume von 40 GB lässt Platz, ein neues Archiv neben dem
  alten zu laden.
- Die Aktualität hängt am Kiwix-Bau. Für Schulwissen reicht ein Stand von einigen Monaten; tagesaktuelle Ereignisse
  fehlen.
- Keine Bilder (Variante `nopic`).
- libzim steht unter GPL; ob das zur Lizenz des Dienstes passt, ist eine offene Frage an edu-sharing.

Gemessen ([Messprotokoll](05-messprotokoll.md), M1 und M2): Der neue Dienst baut den Korpus aus den Archiven auf dem
Server im Median in 0,9 s, mit bis zu zwölf ganzen Artikeln. Beim alten Dienst dauerten im besten Fall allein die
Wikipedia-Anfragen je Thema zusammen im Median 3,3 s (2,3 bis 22,6 s), obwohl er nur Einleitungen abruft.

## Vom Thema zum Korpus: die Artikelwahl

**Alter Dienst:** Ein LLM nennt zehn Begriffe samt vermutetem Titel, jeder Titel wird exakt nachgeschlagen, bei
Misserfolg mit Schreibvarianten und LLM-Synonymen. Ob der Titel eine Begriffsklärung oder ein ganz anderer Artikel
ist, prüft niemand.

**Neuer Dienst:**

1. **Thema bereinigen.** Zusätze wie „in Klasse 7“ oder „Physik:“ werden abgetrennt und als Kontext behalten. Mit
   `collection_id` kommen das Thema und die Bildungsstufen als Kontext aus der Sammlung. Das Fach (aus dem Thema, der
   Anfrage oder der Sammlung) bringt seine Kontextwörter aus `config/subjects.yaml` mit, für Physik etwa *physik*
   und *physikalisch*, für Informatik auch *computer* und *software*.
2. **Exakter Titel** in den Archiven, Wikipedia zuerst; Weiterleitungen werden verfolgt („Atommodell“ führt zu
   *Liste der Atommodelle*). Nennt sein Textanfang kein Kontextwort des Fachs, sieht der Dienst auf der Seite
   „Titel (Begriffsklärung)“ nach: „Informatik: Baum“ führt so zu *Baum (Datenstruktur)*. Findet er dort nichts
   Eindeutiges, bleibt der Titel, gilt aber als unsicher.
3. **Begriffsklärung erkennen.** Unter bis zu 40 gelisteten Bedeutungen gewinnt die, deren Titel (dreifach
   gewertet) und Textanfang die meisten Kontextwörter tragen, verglichen als Wortanfang: „chemi“ findet *Chemische
   Bindung*. Wortformen eines Fachworts zählen einmal. Personen und Werke, die die Seite erst nach einer gewöhnlichen
   Bedeutung nennt, kommen zuletzt; sonst endete „Geschichte: Wende“ beim Historiker Peter Wende. Bis zu acht
   Alternativen stehen in der Antwort.
4. **Sonst** gebeugte Formen („Lineare Funktionen“, „Vulkane“), Genitivwendungen („Kreislauf des Wassers“ über das
   Kompositum *Wasserkreislauf*, „Ursachen der Französischen Revolution“ über das, was dem Aspektwort folgt), dann
   Titelvorschläge und Volltexttreffer, gereiht nach den Wörtern der Anfrage.
5. **Sicherheit melden.** Die Auflösung nennt ihren Weg (`method`: title, variant, disambiguation, suggestion, search
   oder llm) und ob sie sicher ist (`confident`). Unsicher sind eine Begriffsklärung, die das Fach nicht entscheidet,
   ein exakter Titel ohne Fachbezug, Varianten und alle Vorschlags- und Suchtreffer.
6. **Das LLM, wo eines konfiguriert ist** (`article_choice=llm`, D35, seit D37 Vorgabe): Nur bei einer unsicheren
   Auflösung wählt `gpt-5.6-luna` unter den Kandidaten der Regeln oder nennt einen Wikipedia-Titel, der nur zählt, wenn
   das Archiv ihn als Artikel hat. `article_choice=rule-based` schaltet es je Anfrage ab.
7. **Korpus bauen:** Hauptartikel, derselbe Artikel aus Klexikon, verlinkte Unterartikel (gereiht nach Themenwort
   im Titel, Treffer in den Überschriften und Häufigkeit der Erwähnung; Jahre, Länder oder Maßeinheiten stehen auf
   einer Sperrliste) und Volltexttreffer je Baustein, die das Thema nennen. Höchstens 12 Artikel und 400 Absätze.
   Artikel ohne das Themenwort im Titel geben nur Absätze ab, die das Thema nennen. Mit `article_choice=llm` benotet
   das LLM alle Korpusartikel in einem Aufruf, und Volltexttreffer mit der Note 0 fallen heraus.

| Gemessen an zehn Themen | Alter Dienst, bester Fall | Neuer Dienst |
|---|---|---|
| Hauptartikel des Themas im Korpus | 9 von 10 | 10 von 10 |
| Begriffsklärungsseiten als Quelle | 10 (in 3 Themen) | 0 von 87 |
| Umfang der Quellen | Median 10 Einleitungen, rund 12.200 Zeichen | Median 10,5 ganze Artikel |
| Laufzeitabhängigkeiten | Wikipedia und LLM | keine |
| Gleiche Anfrage, gleiches Ergebnis | nicht zugesichert | ja (Stichprobe Photosynthese) |
| Artikel, die nicht zum Thema passen (blind bewertet, M8) | 14 % | 6 % |

### Wie gut die Artikelwahl ist

Die Artikelwahl ist der kritischste Schritt: Ein falscher Hauptartikel macht das ganze Kompendium falsch, ein
unpassender Unterartikel bringt fremde Absätze in den Text. Gemessen wurde sie am 23.09.2026 im Ablauf des Dienstes
([Messprotokoll](05-messprotokoll.md), M8) gegen ein eigenes Gold in `eval/artikelwahl/`. Die folgenden Tabellen
zeigen den Stand vor den Verbesserungen vom 23. und 24.09.2026; was sie brachten, steht im nächsten Abschnitt.

- **Hauptartikel:** 59 Anfragen mit dem erwarteten Artikel, festgelegt, bevor der Dienst sie aufgelöst hat.
- **Korpus:** alle 221 Artikel, die der Dienst für die 20 Themen aus M1 holt, und die 91 Artikel, die der alte Dienst
  für die zehn Goldthemen abrief. Beide Mengen wurden gemischt und blind bewertet, ohne Angabe des Dienstes.
- **Skala:** 2 = gehört zum Thema, 1 = verwandt, 0 = passt nicht.
- **Gegenprobe:** Dieselben Artikel bewertete `gpt-5.6-luna` als Richter.

| Art der Anfrage | Beispiele | Hauptartikel richtig |
|---|---|---|
| normale Themen | Photosynthese, Römisches Reich | 20 von 20 |
| mit Klassen-, Stufen- oder Fachzusatz | Optik in Klasse 7, Physik: Optik (Sek I) | 8 von 8 |
| mehrdeutig, Fach als Kontext | Physik: Strom, Informatik: Maus | 6 von 16 |
| mehrdeutig, ohne Kontext | Strom, Zelle | 3 von 3 |
| Schreibvariante, Abkürzung, Mehrzahl | Fotosynthese, DNA, Lineare Funktionen | 6 von 8 |
| ohne gleichnamigen Artikel zum Thema | Gewaltenteilung in Deutschland | 2 von 4 |
| **alle** | | **45 von 59** |

**Wo die Auflösung scheitert:**

- **Fach als Kontext.** „Informatik: Maus“ endet bei *Gemeine Figur* aus der Wappenkunde, „Informatik: Virus“ bei
  *Viren*, „Chemie: Bindung“ bei *Binden (Kochen)*, „Geschichte: Wende“ bei *Wende (Segeln)*. Zwei Fehler sind
  Grenzfälle: *Leiter (Physik)* und *Theorem* sind allgemeinere Artikel zum richtigen Begriff. Drei Ursachen liegen im
  Code:
  - Das Wort „Fach“ aus „Fach Physik“ zählt als Kontextwort und steckt auch in „mehrfach“; so sammeln falsche
    Bedeutungen Punkte, und bei Gleichstand gewinnt die zuerst gelistete.
  - Kontextwörter zählen nur wörtlich: „Chemie“ steht nicht in *Chemische Bindung*.
  - Ist der genaue Titel keine Begriffsklärung, spielt das Fach keine Rolle: „Informatik: Baum“ bleibt beim Baum.
- **Kein gleichnamiger Artikel zum Thema.** Titelvorschläge und Volltextsuche greifen dann auch daneben: „Lichtlehre“
  führt zu einer Person, „Kreislauf des Wassers“ zu *Meereswärmekraftwerk*, „Lineare Funktionen“ zu
  *Funktionenraum*. „Die Französische Revolution“ trifft genau den Titel eines Spielfilms.

Bei Begriffsklärungen und Suchtreffern stehen Alternativen in der Antwort, bei „Lineare Funktionen“ etwa der richtige
Artikel; die Redaktion kann dann den genauen Titel angeben. Bei einem eindeutigen Titel wie *Baum* gibt es keine
Alternativen. Unbemerkt blieb ein Fehlgriff damals leicht, weil der Dienst nicht meldete, wie sicher er ist; das tut
er seitdem (Schritt 5 oben).

**Korpus der 20 Themen** (Anteile gehört zum Thema, verwandt, passt nicht):

| Herkunft der Artikel | Artikel | Gold | Richter: passt nicht |
|---|---|---|---|
| Hauptartikel | 20 | 100 %, 0 %, 0 % | 0 % |
| dasselbe Thema aus Klexikon | 14 | 86 %, 14 %, 0 % | 14 % |
| verlinkte Unterartikel | 140 | 50 %, 41 %, 9 % | 6 % |
| Volltexttreffer je Baustein | 47 | 32 %, 34 %, 34 % | 23 % |
| **alle** | **221** | **53 %, 34 %, 13 %** | **10 %** |

Die Volltextsuche je Baustein ist die schwächste Quelle: Ein Drittel ihrer Treffer passt nicht, etwa *Kernwaffe*
bei Atommodell oder *Probit-Modell* bei Lineare Funktion. Der Themenfilter hält einen Teil davon zurück: 38 Artikel
geben keinen Absatz ab, unter ihnen sind unpassende doppelt so häufig (21 % gegen 11 %). Von den 3.035 Absätzen im
Korpus stammen 149 (5 %) aus unpassenden Artikeln, von den 358 Absätzen, die der Standard druckt, 26 (7 %).

**Alt gegen neu** auf den zehn Goldthemen:

| | Artikel | gehört zum Thema | verwandt | passt nicht | Richter: passt nicht |
|---|---|---|---|---|---|
| alter Dienst, bester Fall | 91 | 51 % | 35 % | 14 % | 5 % |
| neuer Dienst | 87 | 62 % | 32 % | 6 % | 2 % |

Nach beiden Bewertungen wählt der neue Dienst seltener unpassende Artikel. Beim Anteil zentraler Artikel sind sich
Gold und Richter uneins: nach Gold liegt der neue Dienst vorn (62 % gegen 51 %), nach dem Richter der alte (71 % gegen
66 %). Der Richter vergibt insgesamt öfter eine 2. Sechs Begriffsklärungsseiten des alten Dienstes, etwa *Beugung*
oder *Interferenz*, wertete er als passend, weil er den Begriff im Titel beurteilte, nicht die Seite; als Quelle
taugen sie nicht. Insgesamt stimmen Gold und Richter bei 223 von 288 Artikeln überein (77 %, Cohens Kappa 0,61).

### Was seit M8 besser wurde (M9 bis M11, M13)

Die Hebel aus M8 wurden umgesetzt und gemessen, gegen das Hauptgold und zwei neue Goldsätze: 23 Anfragen zur
Validierung und 12 zurückgehaltene, die erst liefen, als die Regeln feststanden (M9).

| Hauptartikel richtig | alter Stand | Regeln | Regeln und LLM (`article_choice=llm`) |
|---|---|---|---|
| Hauptgold, 59 Anfragen | 45 | 55 | 57 |
| Validierung, 23 | 14 | 22 | 23 |
| zurückgehaltener Test, 12, erster Lauf | 7 | 8 | 9 |
| zurückgehaltener Test nach zwei Korrekturen | 7 | 9 | 11 |

- **Die Regeln** (Schritte 1 bis 5 oben) brachten den größten Teil: Bei mehrdeutigen Wörtern mit Fach stieg die
  Trefferzahl über alle drei Sätze von 19 auf 31 von 38, bei Anfragen ohne gleichnamigen Artikel von 3 auf 9 von 9.
  Unabhängig gemessen ist nur der erste Lauf des Testsatzes, 7 zu 8. Zwei Fehler, die er zeigte, wurden danach
  behoben; seitdem ist auch er nicht mehr unabhängig.
- **Das LLM** entscheidet nur, wo die Regeln unsicher sind: 18 von 94 Anfragen, rund 950 Tokens je Aufruf. Es
  holte „Geschichte: Wende“, „Deutsch: Fall“ (*Kasus*), „Physik: Linse“, „Erdkunde: Delta“ (*Flussdelta*) und
  „Lichtlehre“ (*Optik*, einen Titel, den es selbst nannte). Einen richtigen Artikel der Regeln hat es nie verworfen.
- **Übrig** sind Fälle, in denen die Regeln sich sicher sind und deshalb nicht fragen: „Physik: Leiter“ und
  „Physik: Strom“ enden bei *Leiter (Physik)* und *Strom (Physik)*, allgemeineren Physikartikeln zum richtigen
  Begriff, „Informatik: Netzwerk“ bei *Netzwerk* statt *Rechnernetz*.

**Volltexttreffer je Baustein** (M10). Einfache Filter trennen sie nicht: Das Themenwort in Titel oder erstem Satz
zu verlangen, verwirft 14 der 16 unpassenden Treffer, aber auch 7 der 15 zentralen; die Model2Vec-Ähnlichkeit zur
Einleitung des Hauptartikels ist bei unpassenden Treffern wie *Kernwaffe* (Atommodell) so hoch wie bei guten. Das LLM
mit dem Prompt des M8-Richters trennt sie, wenn es alle Korpusartikel eines Themas zugleich benotet: 11 der 16
unpassenden Treffer bekommen eine 0, keiner der passenden. Die Treffer allein benotet es zu mild (6 von 16). Ohne die
mit 0 benoteten Treffer druckt der Standard 10 statt 26 Absätze aus unpassenden Artikeln und 346 statt 332 aus
passenden oder verwandten. Das ist Teil von `article_choice=llm`, rund 890 Tokens je Thema mit Treffern.

**Zeit und Vorgabe** (M13, D37). Gemessen an 30 Themen, die keine frühere Messung gestellt hatte, damit kein Prompt
aus dem Zwischenspeicher der b-api kommt: `article_choice=llm` verlängert Teil 1 im Median um 1,7 s (90. Perzentil
3,4 s, höchstens 3,8 s) bei rund 930 Tokens. Die Trefferprüfung braucht im Median 1,4 s und lief bei allen 30 Themen;
eine unsichere Artikelwahl kam bei 5 Themen hinzu, mit 1,0 bis 2,6 s. Die schärferen Regeln kosten gegenüber v2.0.0
keine Zeit: Teil 1 im Median 1,35 statt 1,37 s bei warmem Dateicache. Seit D37 ist `article_choice=llm` die Vorgabe,
wo ein LLM konfiguriert ist; ohne LLM wählen die Regeln, ohne Hinweis im Audit. Auf denselben 30 Themen wählten die
neuen Regeln bei 5 der 9 mehrdeutigen Wörter einen anderen Hauptartikel als v2.0.0, dem Titel nach jedes Mal den
besseren (*Blatt (Pflanze)* statt *Keimblatt*, *Körper (Geometrie)* statt *Gegenstand*, *Stimme (Musik)* statt
*Menschliche Stimme*, *Becken (Geomorphologie)* statt *Einzugsgebiet*, *Salze* statt *Speisesalz*); das ist eine
Einschätzung ohne Goldsatz, aber an Anfragen, die nicht in die Regeln eingeflossen sind.

**Sperrliste** (M10, Nebenbefund). Passte der Hauptartikel selbst auf ein Muster der Sperrliste für Links, galt die
ganze Liste nicht: „Programmiersprache“ passt auf das Sprachmuster und ließ *Liste von Programmiersprachen* ein,
*Liste der Atommodelle* auf das Listenmuster und ließ *Physik* ein. Jetzt fällt nur das Muster weg, auf das der Titel
selbst passt.

**Weitere Quellen: Wikibooks und Wikiversity** (M11). Aus weiteren Archiven nimmt der Dienst nur einen Artikel mit
genau dem Titel des Hauptartikels; für die 20 Themen aus M1 waren das zwei Seiten, und die Zahl gefüllter Bausteine
blieb bei 122. Mit der Volltextsuche beider Archive, drei Treffer je Archiv, kamen 88 Seiten hinzu und 1 gefüllter
Baustein (mit der LLM-Prüfung 3). Die Suche findet gute Seiten, etwa *Physikunterricht/ Optik* oder den
Wikiversity-Kurs *Kurs:Optik* mit Versuchen, doch aus keiner dieser Seiten druckte der Standard einen Absatz. Gedruckt
wurde aus Seiten wie *Arbeiten mit .NET* oder *Kommutative Ringe/Bruchrechnung/Aufgabe*, und das *Ungarisch-Lesebuch*
belegte bei sieben Themen die Treffer aus Wikibooks. Das deckt sich mit dem gemischten Bild aus der Testapp. Die
Zusatzsuche wurde deshalb nicht übernommen; die Profile `standard` und `extended` bleiben, wie sie sind.

**Offen:** ein LLM-Vorschlag, wenn die Regeln gar keinen Artikel finden (bisher ein 404 mit Alternativen); die
didaktischen Seiten aus Wikibooks und Wikiversity gezielt für Praxis und Bildung nutzen, etwa mit `matcher=llm` (nicht
gemessen, ein Kompendium kostet dann rund 30.000 Tokens); eine redaktionelle Prüfung der drei Goldsätze.

## Extraktiv oder generativ

Der alte Dienst arbeitet **generativ**: Das Modell bekommt Quelltext und schreibt daraus einen neuen Text. Der neue
arbeitet im Standard **extraktiv**: Er wählt Absätze aus den Quellen, ordnet sie Bausteinen zu und übernimmt je
Absatz die ersten brauchbaren Sätze wörtlich, mit Belegnummer.

| | Generativ (alter Dienst) | Extraktiv (neuer Standard) |
|---|---|---|
| Treue zur Quelle | 21 % der Sätze sind durch die zitierte Quelle nachweislich gestützt, der Rest ist nicht belegt | jeder Satz steht wörtlich im zitierten Absatz (458 von 458) |
| Prüfbarkeit | Verweise auf ganze Artikel, Satzbezug unklar | Belegnummer je Absatz mit Artikel, Abschnitt und Textstelle |
| Tempo und Kosten | 35 s, rund 7.900 Tokens | 2 s, 0 Tokens |
| Wiederholbarkeit | hängt vom Modell ab (Temperatur 0,7) | gleiche Anfrage, gleicher Text (Stichprobe geprüft) |
| Lesbarkeit | flüssiger Fließtext aus einem Guss | Auszüge nebeneinander, ohne Überleitungen, mit Stilwechseln zwischen Quellen |
| Vollständigkeit | füllt jeden Aspekt, notfalls ohne Quelle | Bausteine ohne passenden Absatz bleiben leer |
| Weiterverarbeitung durch KI | Fehler des Modells wandern in jede Folgeanwendung | belastbare, zitierfähige Bausteine; Marker für Abschnitte und Facetten |

### Beispiel: Optik

**Alter Dienst**, Abschnitt „Einführung“ (Lauf vom 23.09.2026 mit `gpt-4.1-mini`):

> Die **Optik** ist ein essenzielles Teilgebiet der Physik, das sich mit der Natur des Lichts und dessen
> Wechselwirkungen mit Materie beschäftigt. Der Begriff „Optik“ entstammt dem altgriechischen ὀπτικός (optikós), was
> „zum Sehen gehörend“ bedeutet, und verweist auf die historische Bedeutung dieses Fachgebiets als „Lehre vom Sehen“
> (1). […] Diese Disziplin hat weitreichende Anwendungen in Wissenschaft, Technik, Medizin und Alltag und bildet
> eine Brücke zwischen theoretischer Physik und praktischer Technologie.

Flüssig geschrieben, aber nur ein Satz verweist auf eine Quelle; für den Rest sagt der Text nicht, woher er stammt.

**Neuer Dienst**, Baustein „1 · Themendefinition“ (Auszug aus dem Wikipedia-Artikel *Optik*, CC BY-SA 4.0):

> Die Optik (von altgriechisch ὀπτικός optikós „zum Sehen gehörend, das Sehen betreffend“ – ὀπτική [τέχνη] optikḗ
> [téchnē]: „Lehre vom Sehen“), auch Lehre vom Licht genannt, ist ein Gebiet der Physik und beschäftigt sich mit der
> Ausbreitung von Licht sowie dessen Wechselwirkung mit Materie, insbesondere im Zusammenhang mit optischen
> Abbildungen. […] [1]

Wörtlich aus der Quelle; die Belegnummer am Ende des Absatzes gilt für alle seine Sätze und führt zu Artikel und
Abschnitt.

**Wo der extraktive Text holpert**, Baustein „3 · Fachinhalte“ (Auszug aus dem Wikipedia-Artikel *Wellenoptik*,
CC BY-SA 4.0):

> Dabei ist der Laplace-Operator, c die Lichtgeschwindigkeit und u die von Ort und Zeit t abhängende Wellenfunktion.
> […] Führt man die Wellenzahl ein, so ergibt sich die Helmholtzgleichung [8]

Im Artikel stehen davor die Wellengleichung und das Symbol Δ als Formelsatz, den die Übernahme weglässt; übrig
bleiben Sätze, die sich auf Unsichtbares beziehen. Im selben Baustein folgt ein Absatz zur Wortherkunft aus dem
Artikel *Augenoptiker*, ohne Überleitung.

Kurz: **extraktiv ist besser für KI und Datenverarbeitung, generativ liest sich besser.** Das Kompendium ist vor
allem Grundlage für Suche, KI-Assistenten und Redaktion, deshalb ist extraktiv der Standard. Für eine bessere
Lesbarkeit gibt es Schalter, die ein Sprachmodell über die b-api zuschalten:

| Schalter | Was das LLM tut | Gemessen mit `gpt-5.6-luna` |
|---|---|---|
| `extraction=llm` | wählt je Baustein Sätze aus bis zu acht Kandidatenabsätzen; der Wortlaut bleibt der Quelle | Optik am 19.09.: 10 Aufrufe, 16.467 Tokens, 11 s; zehn Goldthemen: 14.000–22.400 Tokens je Thema |
| `generation=llm-fast` | schreibt die Bausteine Themendefinition und Querschnitt neu | vier Themen am 18.09.: 2–3 Aufrufe, 2.300–4.000 Tokens, 9–15 s |
| `generation=llm` | schreibt alle Inhaltsbausteine neu | vier Themen am 18.09.: 8–10 Aufrufe, 10.500–14.500 Tokens, 16–20 s |
| beide auf `llm` | Satzauswahl und Neuformulierung | Optik am 19.09.: 20 Aufrufe, 27.205 Tokens, 18 s; über die Goldthemen bis rund 37.000 Tokens |
| `enrichment=model-knowledge` | erlaubt eigenes Modellwissen, sichtbar markiert als `Evidenzgrad=Modellwissen` | – |

**Belegprüfung:** Ein vom LLM geschriebener Satz bleibt nur, wenn er eine gültige Belegnummer trägt und mindestens
20 % seiner Inhaltswörter im zitierten Absatz vorkommen. Bei 175 geprüften Modellsätzen (18.09.2026) lag dieser
Anteil im Median bei 73 %; eigene Schlussfolgerungen des Modells kamen auf 0 bis 17 %, die schwächsten treuen
Umformulierungen auf 20 % und mehr. Fällt ein Satz durch, wird er gestrichen oder als Schlussfolgerung markiert;
bleibt nichts übrig, steht der extraktive Text. Ist die b-api nicht erreichbar oder das Tagesbudget aufgebraucht,
arbeitet der Dienst regelbasiert weiter, und der Vorspann nennt den tatsächlich genutzten Weg.

## Lesbarkeit: weitere Wege

| Weg | Wirkung | Aufwand, Kosten | Stand |
|---|---|---|---|
| `generation=llm-fast` oder `llm` | flüssiger Text, Belege bleiben prüfbar | 2.300–14.500 Tokens, 9–20 s | vorhanden |
| `extraction=llm` | passendere Sätze statt Absatzanfängen; im Goldstandard 14 richtige Absätze mehr als dieselbe Konfiguration ohne LLM, bei gleicher Präzision; kleine Bausteine füllt es dagegen oft falsch | 14.000–22.400 Tokens, rund 11 s | vorhanden |
| Redaktion mit Teil-Neuerzeugung | Menschen glätten; als geprüft markierte Bausteine bleiben bei jeder Neuerzeugung wortgleich | redaktionelle Zeit | vorhanden |
| Formelreste vermeiden: Sätze weglassen, die sich auf eine entfernte Formel beziehen, oder die Formel als Text übernehmen | keine Sätze mit Bezug ins Leere wie im Beispiel oben | klein, ohne LLM | Vorschlag; eine Regel gibt es schon, sie erkennt aber nur Funktionswörter direkt vor einem Satzzeichen |
| Überleitungssatz je Baustein aus einem Kurztext im Template | Orientierung für Lesende, ohne LLM | klein | Vorschlag |
| Anzeige im Frontend: Belegnummern als Fußnote oder Tooltip, Quelle je Absatz einblendbar | ruhigeres Schriftbild; die Marker sind schon heute unsichtbare HTML-Kommentare | Frontend | Vorschlag |
| Kurzüberblick am Anfang, vom LLM aus den Bausteinen, als solcher gekennzeichnet | drei bis fünf Sätze Einstieg | ein Aufruf | Vorschlag |
| Zwei Fassungen: der extraktive Text bleibt die Referenz, eine LLM-Lesefassung wird daraus erzeugt und verweist auf dieselben Belege | prüfbar für Maschinen, lesbar für Menschen | Tokens je Erzeugung, Speicher für zwei Fassungen | Vorschlag |
| Klexikon-Absätze für einen einfachen Einstieg bevorzugen | einfache Sprache für jüngere Lernende | klein | Vorschlag; Klexikon ist schon heute Quelle und in Themendefinition, Gesellschaftlichem Kontext und Bildung ausdrücklich vorgesehen |
