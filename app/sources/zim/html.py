"""Parse mwoffliner article HTML into sections, paragraphs, links and aliases.

Observed structure (openZIM/mwoffliner 1.17, Wikipedia and Klexikon): content inside
``div.mw-parser-output`` with ``<p>``, ``<h2>``..``<h4>``, ``<ul>/<ol>/<dl>``; footnotes as
``<sup class="reference">``; inline ``<style>`` blocks inside paragraphs; internal links as
relative, URL-encoded ``href`` with a decoded ``title`` attribute; the defined term in bold.
Class checks are token exact: the ``<html>`` element itself carries classes such as
``vector-toc-not-available`` that a substring match would wrongly treat as a table of contents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import unquote

from app.domain.models import ArticleSection, ChunkKind, Paragraph

_VOID = frozenset({"br", "img", "hr", "meta", "link", "input", "wbr", "source", "col", "area", "base"})
_SKIP_TAGS = frozenset(
    {"head", "title", "script", "style", "nav", "noscript", "figure", "iframe", "svg", "audio", "video", "h1"}
)
_NEVER_SKIP = frozenset({"html", "body", "main"})
_SKIP_CLASSES = frozenset(
    {
        "reference",
        "references",
        "mw-editsection",
        "thumb",
        "thumbinner",
        "thumbcaption",
        "hatnote",
        "noprint",
        "navbox",
        "toc",
        "metadata",
        "infobox",
        "sidebar",
        "mw-empty-elt",
        "gallery",
        "mw-references-wrap",
        "mw-indicators",
        "mw-jump-link",
        "printfooter",
        "catlinks",
        "rellink",
        "noexcerpt",
        "mwe-math-element",
        "mwe-math-fallback-image-inline",
        "mw-kartographer-container",
        "mw-halign-right",
        "mw-halign-left",
        "BKL",
        "Begriffsklaerung",
    }
)
_SKIP_CLASS_PREFIXES = ("vector-toc", "mw-indicator", "mw-jump", "navbox-", "infobox_", "Vorlage_Begriffskl")
_SKIP_IDS = frozenset({"toc", "mw-navigation", "footer", "siteNotice", "mw-panel", "mw-head", "p-lang"})
_NAMESPACES = (
    "Datei:",
    "File:",
    "Kategorie:",
    "Category:",
    "Spezial:",
    "Special:",
    "Hilfe:",
    "Help:",
    "Wikipedia:",
    "Portal:",
    "Vorlage:",
    "Template:",
    "Diskussion:",
    "Benutzer:",
    "Klexikon:",
    "Wikibooks:",
    "Wikiversity:",
    "Media:",
    "Bild:",
)
_HEADINGS = {"h2": 2, "h3": 3, "h4": 4, "h5": 4, "h6": 4}
_BLOCK_TAGS = frozenset({"p", "blockquote", "dd", "dt", "div", "pre", "section", "article"})
_ALIAS_PATTERNS = [
    re.compile(r"\bauch\s+([A-ZÄÖÜ][^,.;()]{2,60}?)\s+genannt\b"),
    re.compile(r"\(auch\s+([^)]{2,60}?)\)"),
    re.compile(r"\bauch\s+(?:kurz\s+)?([A-ZÄÖÜ][\wäöüß-]{2,40})\b(?=[,.;])"),
]


@dataclass
class ParsedArticle:
    title: str
    sections: list[ArticleSection]
    links: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    is_disambiguation: bool = False

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for s in self.sections for p in s.paragraphs)


class _ArticleParser(HTMLParser):
    def __init__(self, title: str) -> None:
        super().__init__(convert_charrefs=True)
        self.title = title
        self.sections: list[ArticleSection] = [ArticleSection(heading="", path=[], level=0)]
        self.links: list[str] = []
        self.bold_terms: list[str] = []
        self._skip: list[str] = []
        self._heading_level: int | None = None
        self._heading_text: list[str] = []
        self._text: list[str] = []
        self._list_depth = 0
        self._list_items: list[str] = []
        self._item_text: list[str] = []
        self._in_item = False
        self._table_depth = 0
        self._table_rows: list[str] = []
        self._row_cells: list[str] = []
        self._cell_text: list[str] = []
        self._in_cell = False
        self._bold_depth = 0
        self._bold_text: list[str] = []
        self._path_stack: list[str] = []
        self._seen_links: set[str] = set()

    # -- helpers ------------------------------------------------------------------------------
    @property
    def _current(self) -> ArticleSection:
        return self.sections[-1]

    def _flush_paragraph(self) -> None:
        text = self._normalize("".join(self._text))
        self._text = []
        if text:
            self._current.paragraphs.append(Paragraph(kind=ChunkKind.TEXT, text=text))

    def _flush_list(self) -> None:
        items = [self._normalize(i) for i in self._list_items]
        items = [i for i in items if i]
        self._list_items = []
        if items:
            self._current.paragraphs.append(Paragraph(kind=ChunkKind.LIST, text="\n".join(f"- {i}" for i in items)))

    def _flush_table(self) -> None:
        rows = [r for r in self._table_rows if r.strip(" |")]
        self._table_rows = []
        if len(rows) >= 2:
            self._current.paragraphs.append(Paragraph(kind=ChunkKind.TABLE, text="\n".join(rows)))

    @staticmethod
    def _normalize(text: str) -> str:
        text = re.sub(r"\[\d+\]", "", text)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\s*\n\s*", " ", text)
        return text.strip()

    def _emit(self, data: str) -> None:
        if self._heading_level is not None:
            self._heading_text.append(data)
        elif self._in_cell:
            self._cell_text.append(data)
        elif self._in_item:
            self._item_text.append(data)
        else:
            self._text.append(data)
        if self._bold_depth:
            self._bold_text.append(data)

    @staticmethod
    def _should_skip(tag: str, attrs: dict[str, str | None]) -> bool:
        if tag in _NEVER_SKIP:
            return False
        if tag in _SKIP_TAGS:
            return True
        tokens = (attrs.get("class") or "").split()
        if any(t in _SKIP_CLASSES or t.startswith(_SKIP_CLASS_PREFIXES) for t in tokens):
            return True
        if (attrs.get("id") or "") in _SKIP_IDS:
            return True
        if tag == "table":
            return "wikitable" not in tokens
        return False

    # -- HTMLParser callbacks --------------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        if self._skip:
            if tag not in _VOID:
                self._skip.append(tag)
            return
        if tag == "math":  # MathML and its LaTeX alttext are not prose; drop them
            self._skip.append(tag)
            return
        if self._should_skip(tag, attrs):
            if tag not in _VOID:
                self._skip.append(tag)
            return
        if tag in _HEADINGS:
            self._close_blocks()
            self._heading_level = _HEADINGS[tag]
            self._heading_text = []
            return
        if tag == "a":
            self._record_link(attrs)
            return
        if tag in ("b", "strong"):
            self._bold_depth += 1
            self._bold_text = []
            return
        if tag in ("ul", "ol"):
            if self._list_depth == 0:
                self._flush_paragraph()
            self._list_depth += 1
            return
        if tag == "li" and self._list_depth:
            if self._in_item:
                self._list_items.append("".join(self._item_text))
            self._item_text = []
            self._in_item = True
            return
        if tag == "table":
            self._flush_paragraph()
            self._table_depth += 1
            self._table_rows = []
            return
        if tag == "tr" and self._table_depth:
            self._row_cells = []
            return
        if tag in ("td", "th") and self._table_depth:
            self._cell_text = []
            self._in_cell = True
            return
        if tag in _BLOCK_TAGS:
            if not self._in_item and not self._in_cell:
                self._flush_paragraph()
            return
        if tag == "br":
            self._emit(" ")

    def handle_endtag(self, tag: str) -> None:
        if self._skip:
            if tag == self._skip[-1]:
                self._skip.pop()
            return
        if tag in _HEADINGS and self._heading_level is not None:
            heading = self._normalize("".join(self._heading_text))
            level = self._heading_level
            self._heading_level = None
            self._start_section(heading, level)
            return
        if tag in ("b", "strong") and self._bold_depth:
            self._bold_depth -= 1
            term = self._normalize("".join(self._bold_text))
            if self._current.level == 0 and 2 <= len(term) <= 60:
                self.bold_terms.append(term)
            return
        if tag == "li" and self._in_item:
            self._list_items.append("".join(self._item_text))
            self._item_text = []
            self._in_item = False
            return
        if tag in ("ul", "ol") and self._list_depth:
            self._list_depth -= 1
            if self._list_depth == 0:
                self._flush_list()
            return
        if tag in ("td", "th") and self._in_cell:
            self._row_cells.append(self._normalize("".join(self._cell_text)))
            self._in_cell = False
            return
        if tag == "tr" and self._table_depth:
            self._table_rows.append(" | ".join(self._row_cells))
            self._row_cells = []
            return
        if tag == "table" and self._table_depth:
            self._table_depth -= 1
            self._flush_table()
            return
        if tag in _BLOCK_TAGS and not self._in_item and not self._in_cell:
            self._flush_paragraph()

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self._emit(data)

    # -- structure ------------------------------------------------------------------------------
    def finish(self) -> None:
        """Flush trailing paragraph and list after the document has been fed."""
        self._close_blocks()

    def _close_blocks(self) -> None:
        self._flush_paragraph()
        if self._list_depth:
            if self._in_item:
                self._list_items.append("".join(self._item_text))
                self._in_item = False
            self._list_depth = 0
            self._flush_list()

    def _start_section(self, heading: str, level: int) -> None:
        if not heading:
            return
        depth = level - 2  # h2 -> 0
        self._path_stack = self._path_stack[:depth]
        self._path_stack.append(heading)
        self.sections.append(ArticleSection(heading=heading, path=list(self._path_stack), level=level))

    def _record_link(self, attrs: dict[str, str | None]) -> None:
        href = attrs.get("href") or ""
        if not href or href.startswith(("#", "http://", "https://", "//", "./_", "../", "mailto:", "javascript:")):
            return
        title = attrs.get("title") or unquote(href.split("#")[0].split("?")[0]).replace("_", " ")
        title = title.strip()
        if not title or title.startswith(_NAMESPACES):
            return
        if title.lower() not in {t.lower() for t in self._current.links}:
            self._current.links.append(title)
        if title.lower() in self._seen_links:
            return
        self._seen_links.add(title.lower())
        self.links.append(title)


def parse_article(html: str, title: str) -> ParsedArticle:
    """Parse article HTML; the first section (level 0) is the lead."""
    parser = _ArticleParser(title)
    parser.feed(html)
    parser.close()
    parser.finish()
    sections = [s for s in parser.sections if s.paragraphs]
    lead_text = sections[0].paragraphs[0].text if sections and sections[0].level == 0 else ""
    aliases = _aliases(parser.bold_terms, lead_text, title)
    text_head = " ".join(p.text for s in sections[:2] for p in s.paragraphs)[:2000].lower()
    is_disambiguation = "(begriffsklärung)" in title.lower() or "begriffsklärungsseite" in text_head
    return ParsedArticle(
        title=title, sections=sections, links=parser.links, aliases=aliases, is_disambiguation=is_disambiguation
    )


def _aliases(bold_terms: list[str], lead_text: str, title: str) -> list[str]:
    aliases: list[str] = []
    for term in bold_terms:
        clean = term.strip(" „“\"'")
        if clean and clean.lower() != title.lower() and clean not in aliases:
            aliases.append(clean)
    for pattern in _ALIAS_PATTERNS:
        for match in pattern.finditer(lead_text):
            clean = match.group(1).strip(" „“\"'")
            if clean and clean.lower() != title.lower() and clean not in aliases:
                aliases.append(clean)
    return aliases[:8]
