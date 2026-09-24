"""Identifiers of a linked Wikipedia article (D43), all from local data: nothing is looked up online.

* GND and VIAF come from the article's Normdaten block, which the Kiwix dump keeps (docs/entwicklung, M18);
* the Wikidata number comes from the local index built from two dewiki dumps (``compendium wikidata build``);
* the DBpedia URI is built from the title the way DBpedia forms its IRIs. It is constructed, not checked: the
  German DBpedia may lag behind the archive, so a URI can name a resource it does not describe yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from app.sources.wikidata.index import WikidataIndex
from app.sources.zim.normdaten import read_normdaten

DBPEDIA = "http://de.dbpedia.org/resource/"
GND = "https://d-nb.info/gnd/"
VIAF = "https://viaf.org/viaf/"
WIKIDATA = "http://www.wikidata.org/entity/"
# Characters that mean something in a URI or are not allowed in an IRI; the rest of a title stays as it is
_ESCAPED_IN_URI = frozenset('"#%<>?[]^`{|}' + chr(92))


def dbpedia_uri(title: str) -> str:
    """The DBpedia URI of a German Wikipedia title: spaces become underscores, umlauts and brackets stay."""
    name = title.strip().replace(" ", "_")
    return DBPEDIA + "".join(quote(char, safe="") if char in _ESCAPED_IN_URI else char for char in name)


@dataclass(frozen=True)
class Identifiers:
    gnd: str | None
    gnd_kind: str | None
    viaf: str | None
    wikidata: str | None
    dbpedia: str

    @property
    def same_as(self) -> list[str]:
        """Every identifier as a URI, in the order GND, VIAF, Wikidata, DBpedia."""
        uris = [
            GND + self.gnd if self.gnd else None,
            VIAF + self.viaf if self.viaf else None,
            WIKIDATA + self.wikidata if self.wikidata else None,
            self.dbpedia,
        ]
        return [uri for uri in uris if uri]


def identifiers(title: str, html: str, wikidata: WikidataIndex | None) -> Identifiers:
    """The identifiers of the Wikipedia article ``title`` whose page is ``html``."""
    normdaten = read_normdaten(html)
    return Identifiers(
        gnd=normdaten.gnd if normdaten else None,
        gnd_kind=normdaten.kind if normdaten else None,
        viaf=normdaten.viaf if normdaten else None,
        wikidata=wikidata.qid(title) if wikidata else None,
        dbpedia=dbpedia_uri(title),
    )
