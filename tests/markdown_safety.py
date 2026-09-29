"""What a reader's renderer makes of the markdown the service writes (audit 2026-09-28, SE-16, SE-17 and SE-21).

markdown-it renders CommonMark with tables, lets raw HTML through and takes every link target, as the most permissive
renderer a consumer may use would. ``unsafe`` lists everything in the resulting HTML that markdown syntax alone does not produce: a tag of its
own, an attribute that runs code or loads something, a link that is not a web address, a comment that is none of the
service's markers.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from markdown_it import MarkdownIt

_RENDERER = MarkdownIt("commonmark", {"html": True}).enable("table")
# markdown-it refuses javascript: and similar targets itself; a consumer's renderer may not, so none is refused here
_RENDERER.validateLink = lambda url: True  # type: ignore[method-assign]
MARKDOWN_TAGS = frozenset(
    "p h1 h2 h3 h4 h5 h6 ul ol li strong em a code pre table thead tbody tr th td hr br blockquote".split()
)
OWN_COMMENT = re.compile(r"^ (?:f: [^\n]*|/f|kompendium:section [^\n]*) $")
WEB = re.compile(r"^https?://", re.IGNORECASE)
ALIGNMENT = re.compile(r"^text-align:(?:left|right|center)$")


def render(markdown: str) -> str:
    html: str = _RENDERER.render(markdown)
    return html


class _Inspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[str] = []
        self.tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        if tag not in MARKDOWN_TAGS:
            self.found.append(f"tag <{tag}>")
        for name, value in attrs:
            if tag == "a" and name == "href" and WEB.match(value or ""):
                continue
            if tag == "a" and name == "title":
                continue
            if tag in ("th", "td") and name == "style" and ALIGNMENT.match(value or ""):
                continue
            self.found.append(f"{tag}[{name}={value!r}]")

    def handle_comment(self, data: str) -> None:
        if not OWN_COMMENT.match(data):
            self.found.append(f"comment <!--{data[:40]}-->")

    def handle_decl(self, decl: str) -> None:
        self.found.append(f"declaration <!{decl[:40]}>")

    def handle_pi(self, data: str) -> None:
        self.found.append(f"processing instruction <?{data[:40]}>")


def unsafe(markdown: str) -> list[str]:
    """What the rendered markdown holds beyond harmless markup; empty when it is safe to show."""
    inspector = _Inspector()
    inspector.feed(render(markdown))
    inspector.close()
    return inspector.found


def tags(markdown: str) -> list[str]:
    """The tags of the rendered markdown in document order."""
    inspector = _Inspector()
    inspector.feed(render(markdown))
    inspector.close()
    return inspector.tags
