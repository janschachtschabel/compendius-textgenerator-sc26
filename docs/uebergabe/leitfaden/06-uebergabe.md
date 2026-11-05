# 6. Übergabe und Wartung

[Leitfaden](../leitfaden-dienste.md) · zurück: [5. Dienste kombinieren](05-kestra.md)

## Übergabepaket (vollständig, bevor T6 übernimmt)

- [ ] Repo-Link und CI, die getaggte, schlanke Images und das Chart je Tag baut
- [ ] Pfad zur OpenAPI, Anzeigename und Beschreibungstext für Endnutzende
- [ ] Port-Aufteilung (öffentlich / intern) bzw. Liste auszublendender Pfade
- [ ] Besondere Header, Content-Types, erwartete Antwortzeiten, ggf. Job-Endpunkte
- [ ] Mit b-api: Proxy-Eintrag, durchgereichter Schlüssel, Rechte, Route (Modelle). Ohne b-api: Env für LLM und Auth
- [ ] Prometheus-Endpunkt, Applikationsmetriken, Alarmregeln
- [ ] Log-Format, Dienst-ID, B3-Tracing
- [ ] Zustand, Skalierung und ihre Grenzen, kurze Architekturübersicht
- [ ] Ressourcen gemessen (RAM fest oder elastisch, CPU, Storage), Empfehlung mit Puffer
- [ ] Datenbankwahl, abschaltbare Komponenten, Bereitstellung großer Daten (Quelle, Volume-Größe)
- [ ] Updates der Daten (CronJobs, Zeitplan), Überwachung, ob sie laufen
- [ ] Env-Variablen mit Vorgaben, Helm-Values, Liste der Secrets, Dockerfile und Compose als Referenz
- [ ] Mit wem der Dienst spricht (für die NetworkPolicy)
- [ ] Kosten (LLM-Tokens je Aufruf, externe APIs), Laufzeit je Funktion
- [ ] Ansprechperson **und Vertretung**

## Steckbrief

Eine Seite nach der Vorlage von Team 6, je Zeile eine knappe Angabe mit Status. Zusätzlich bewährt: Funktionen mit
Laufzeit und Kosten, ein b-api-Block, Clusterfähigkeit (was geht, was nicht), Updates und CronJobs, Ressourcen mit
Empfehlung, Image-Größe. Muster: [Steckbrief Kompendiale Texte](../steckbrief.md).

## Wartung und Lebenszyklus

- [ ] Vor der Übergabe klären, wer Updates anstößt (Abhängigkeiten, Sicherheitspatches, Modellwechsel).
- [ ] Modellwechsel über die Route der b-api, nicht über ein neues Image – innerhalb einer Parameterfamilie.
- [ ] Changelog mit Hinweisen für den Betrieb je Release.
- [ ] Prototypen: festhalten, ob und wann über einen dauerhaften Betrieb entschieden wird, mit Aufwand und Kosten.
- [ ] Im Blick behalten, ob der Dienst verkaufbar ist (Paket, Kundenkreis) und ob er bei Kunden ohne WLO-Metadaten
      oder ohne OpenAI funktioniert.
