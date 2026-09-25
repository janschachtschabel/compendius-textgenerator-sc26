# Fachvokabulare von edu-sharing

Schnappschüsse der beiden Vokabulare, die edu-sharing im Feld `ccm:taxonid` nutzt, Stand 25.09.2026. Das Feld hält
Schul- und Hochschulfächer; `ccm:oeh_taxonid_university` wiederholt die Hochschulfächer.

| Datei | Vokabular | Begriffe |
|---|---|---|
| `discipline.json` | Schulfächer, <https://vocabs.openeduhub.de/w3id.org/openeduhub/vocabs/discipline/index.json> | 70 |
| `hochschulfaechersystematik.json` | Hochschulfächer der Destatis-Systematik, <https://vocabs.openeduhub.de/w3id.org/openeduhub/vocabs/hochschulfaechersystematik/index.json> | 344 in drei Ebenen |

Als `subject` einer Anfrage nimmt der Dienst jeden Begriff beider Vokabulare an: URI, Kennung (letzter Teil der
URI), deutsches Label oder Alternativlabel. Alles andere ist eine 422 (D51). Lehrplanwörter und Kontextwörter der
Artikelwahl haben nur die 37 Fächer von `config/subjects.yaml`; für ein anderes Fach sucht Teil 2 in allen Fächern.

Auffrischen:

```bash
curl -o config/vocabs/discipline.json https://vocabs.openeduhub.de/w3id.org/openeduhub/vocabs/discipline/index.json
curl -o config/vocabs/hochschulfaechersystematik.json https://vocabs.openeduhub.de/w3id.org/openeduhub/vocabs/hochschulfaechersystematik/index.json
```
