"""Identifiers of a linked Wikipedia article (D43), all from local data: nothing is looked up online.

* GND and VIAF come from the article's Normdaten block, which the Kiwix dump keeps (docs/entwicklung, M18). An
  article without a GND there gets one from the local GND index, built from the DNB's dumps (D65): the record that
  names its Wikidata item, else the one record that carries its title, and only when the block names no other kind
  of record (a person, a work: the index holds subject headings and places). ``gnd_source`` says which;
* the Wikidata number comes from the local index built from dewiki dumps (``compendium wikidata sync``, D64);
* the DBpedia URI names the resource of the article's English counterpart, which the same index knows from the
  dewiki table ``langlinks``: ``de.dbpedia.org`` no longer answers, and DBpedia names its live resources after the
  English article (M42, D65). Without an English article it stays the German chapter's IRI. Either way it is built
  the way DBpedia forms its IRIs, not checked.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from app.sources.gnd.index import GndIndex
from app.sources.wikidata.index import WikidataIndex
from app.sources.zim.normdaten import read_normdaten

DBPEDIA = "http://dbpedia.org/resource/"
DBPEDIA_DE = "http://de.dbpedia.org/resource/"  # the German chapter, for articles without an English one
GND = "https://d-nb.info/gnd/"
VIAF = "https://viaf.org/viaf/"
WIKIDATA = "http://www.wikidata.org/entity/"
# Characters that mean something in a URI or are not allowed in an IRI; the rest of a title stays as it is
_ESCAPED_IN_URI = frozenset('"#%<>?[]^`{|}' + chr(92))


def dbpedia_uri(title: str, english: str | None = None) -> str:
    """The DBpedia URI of a German Wikipedia article: the resource of its English article (``english``), else the
    German chapter's IRI of ``title``. Spaces become underscores, umlauts and brackets stay."""
    base, name = (DBPEDIA, english) if english else (DBPEDIA_DE, title)
    name = name.strip().replace(" ", "_")
    return base + "".join(quote(char, safe="") if char in _ESCAPED_IN_URI else char for char in name)


@dataclass(frozen=True)
class Identifiers:
    gnd: str | None
    gnd_kind: str | None
    gnd_source: str | None  # "normdaten", "wikidata" or "name"; None without a GND
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


def identifiers(title: str, html: str, wikidata: WikidataIndex | None, gnd: GndIndex | None = None) -> Identifiers:
    """The identifiers of the Wikipedia article ``title`` whose page is ``html``."""
    normdaten = read_normdaten(html)
    qid = wikidata.qid(title) if wikidata else None
    number = normdaten.gnd if normdaten else None
    kind = normdaten.kind if normdaten else None
    source = "normdaten" if number else None
    hit = gnd.find(title, qid) if number is None and gnd is not None else None
    # A record of another kind than the block names - the article is a person, a work - is not the article's
    if hit is not None and kind in (None, hit.kind):
        number, kind, source = hit.number, hit.kind, hit.source
    return Identifiers(
        gnd=number,
        gnd_kind=kind,
        gnd_source=source,
        viaf=normdaten.viaf if normdaten else None,
        wikidata=qid,
        dbpedia=dbpedia_uri(title, wikidata.english(title) if wikidata else None),
    )
