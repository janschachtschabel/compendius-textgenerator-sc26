"""The Normdaten block of a German Wikipedia article: the authority record the article stands for.

German Wikipedia ends most articles with it, and the Kiwix dump keeps it: the kind of the record ("Person",
"Sachbegriff", "Geografikum", "Körperschaft", "Werk", ...), the GND number and often the VIAF number. Measured on
the entities the endpoint links (docs/entwicklung, M18): 503 of 679 Wikipedia articles carry a GND number, and 30
of 30 numbers checked against lobid-gnd name what their article is about. Only the block is read; a GND link in
the references names an author or a book, not the article.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BLOCK_MARKER = 'id="normdaten"'
BLOCK_CHARS = 4000  # the block is a few hundred characters; the window only has to reach its end
_KIND_RE = re.compile(r"Normdaten(?:&nbsp;|\s)\(([^)<]+)\)")
_GND_RE = re.compile(r"d-nb\.info/gnd/([0-9X-]+)")
_VIAF_RE = re.compile(r"viaf\.org/viaf/(\d+)")


@dataclass(frozen=True)
class Normdaten:
    kind: str | None
    gnd: str | None
    viaf: str | None


def read_normdaten(html: str) -> Normdaten | None:
    """Kind, GND and VIAF of the article's Normdaten block; ``None`` when the article has no such block."""
    start = html.find(BLOCK_MARKER)
    if start < 0:
        return None
    window = html[start : start + BLOCK_CHARS]
    kind = _KIND_RE.search(window)
    # The label and all numbers stand in one <div>; what follows its end belongs to the page, not to the block
    end = window.find("</div>", kind.end() if kind else 0)
    block = window[: end if end >= 0 else len(window)]
    gnd, viaf = _GND_RE.search(block), _VIAF_RE.search(block)
    return Normdaten(
        kind=kind.group(1).strip() if kind else None,
        gnd=gnd.group(1) if gnd else None,
        viaf=viaf.group(1) if viaf else None,
    )
