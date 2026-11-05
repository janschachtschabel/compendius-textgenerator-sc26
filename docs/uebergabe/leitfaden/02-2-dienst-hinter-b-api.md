# 2.2 Dienst hinter der b-api

[Leitfaden](../leitfaden-dienste.md) · zurück: [2.1 LLM und Routing](02-1-llm-routing.md) · weiter: [2.3 Logging und Tracing](02-3-logging-tracing.md)

```
Browser → edu-sharing → b-api /api/v1/proxy/<dienst> → Dienst → b-api (LLM, Router)
          wählt Schlüssel  reicht Authorization weiter    reicht ihn   bucht auf den Schlüssel
                                                          unverändert weiter
```

Die b-api prüft den Schlüssel, begrenzt und bucht Nutzung und Kosten je Schlüssel (`dailyCostLimit`,
`weeklyCostLimit`) und reicht ihn als `Authorization: Bearer <key>` an den Dienst weiter. edu-sharing wählt den
Schlüssel: einen für eingeloggte Nutzer, einen für Gäste. Der Dienst braucht keinen eigenen Schlüssel und muss nicht
wissen, wer anfragt.

## Regeln im Dienst

- [ ] **Nur `Authorization` lesen.** `X-API-KEY` kommt über den Proxy nicht an.
- [ ] **Unverändert weitergeben:** nichts davorsetzen, nichts umformatieren, der Wert enthält schon `Bearer …`.
      Kleines `bearer` → 401.
- [ ] **Genau einen Header** an die b-api: ein zusätzlicher ungültiger `X-API-KEY` → 401.
- [ ] **Nur pro Anfrage:** nicht speichern, nicht loggen, nicht in einem Singleton ablegen, nur an die b-api.
- [ ] **Rückfall-Schlüssel** `B_API_KEY` nur für Aufrufe ohne Header (lokal, Tests, Hintergrundjobs) – ein eigener
      Schlüssel, nie der eines Nutzers.
- [ ] **Keine eigene Prüfung** des Schlüssels; dafür nur über die b-api erreichbar (NetworkPolicy, Kapitel 3).

```python
import os
from fastapi import HTTPException, Request


def llm_auth(request: Request) -> dict[str, str]:
    auth = request.headers.get("authorization")  # unverändert übernehmen
    if auth:
        return {"Authorization": auth}
    fallback = os.environ.get("B_API_KEY")  # nur ohne Proxy: Tests, Jobs
    if fallback:
        return {"Authorization": f"Bearer {fallback}"}
    raise HTTPException(401, "Kein API-Key empfangen und kein Rückfall-Key gesetzt")
```

## Einmalig: den Dienst anbinden (Administrator der b-api)

1. Als Proxy-Dienst eintragen: Name (`/api/v1/proxy/<name>`, gleich der Dienst-ID), `baseUrl` auf den öffentlichen Port,
   Timeout = längste Antwort + Reserve.
2. „API-Key des Aufrufers weiterreichen“ (`forwardApiKey`) anhaken.
3. Sicherstellen, dass der Dienst nur über die b-api erreichbar ist.

## Testen

| Phase | Was | braucht den Eintrag |
|---|---|---|
| Schlüssel prüfen | `GET $B/api/v1/llm/openai/models` mit `Authorization: Bearer …` → 200 | nein |
| Dienst lokal | den Header selbst setzen, wie es später die b-api tut | nein |
| Echter Weg | ein Aufruf über `/api/v1/proxy/<dienst>/…`; kommt der Header an, klappt der Rückweg? | ja |
| Produktion | mit Nutzer- und Gast-Schlüssel prüfen | ja |

Für den echten Weg hilft ein vorübergehender Endpunkt, der nur zeigt, **ob** der Header ankommt (Schema und Länge,
nie den Wert) – danach entfernen.

## Sicherheit

- Nicht direkt aus dem Internet erreichbar; nur die b-api (und das Monitoring am internen Port).
- Nie loggen – auch nicht in Access-Logs, Fehlerseiten oder Debug-Ausgaben.
- Keine Session-Cookies weiterreichen.
- Der Gast-Schlüssel gilt als öffentlich: Limits eng setzen.

## Fehlersuche

| Symptom | Ursache |
|---|---|
| 401 ohne Text | Header fehlt, falsch oder `bearer` klein |
| 401 trotz gültigem Bearer | zusätzlich ein ungültiger `X-API-KEY` |
| Dienst bekommt keinen Header | `forwardApiKey` nicht gesetzt oder Aufruf nicht über `/api/v1/proxy/<name>` |
| 400 `Proxy <name> not found` | Dienst nicht eingetragen oder falscher Name |
| 403 auf `/administration/*` | Schlüssel ohne Admin-Recht – erwartet |

## Praxis aus „Kompendiale Texte“

- `B_API_KEY_SOURCE=request` nimmt den Schlüssel der Anfrage, sonst `B_API_KEY`: Derselbe Dienst läuft hinter der
  b-api und direkt, ohne Code-Änderung.
- Lehnt die b-api den Schlüssel einer Anfrage ab, läuft diese Anfrage ohne LLM weiter; andere Anfragen behalten es.
- Das Access-Log von uvicorn ist aus; die eigene Zeile je Anfrage nennt keine Header.

Muster: `app/api/b_api_key.py`, [anforderungen.md, Abschnitt 2](../anforderungen.md#2-b-api-integration-und-authentifizierung).
