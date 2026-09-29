"""Text of sources other people type into, made safe to stand in the markdown of a compendium.

Part 3 treated repository text this way from the start; part 2 put the labels and IRIs of MEM in unfiltered (audit
2026-09-27, SE-05): the harvest turns "&lt;!--" into "<!--", which opened a comment that hid the rest of the
document, and the IRI of a node or area was never checked before it became a link target - "javascript:alert(…)"
was rendered. Both parts now share these helpers.

Parts 1 and 3 kept a gap each (audit 2026-09-28, SE-16): the rules copy source sentences word for word, and the ZIM
parser turns "&lt;" into "<", so the article on cross-site scripting brought a real ``<script>`` into part 1; the
titles, addresses, authors and descriptions of materials went in as typed. ``escape_text`` makes such text show as
typed, and ``defuse`` is the net behind every writer: whatever it overlooks, no tag, image, comment or link to
anything but a web address reaches the reader.
"""

from __future__ import annotations

import re

WEB_SCHEMES = ("https://", "http://")
# Signs that start markdown or HTML inside a line. The backslash comes first, so an escape the source typed cannot
# take over one of ours; backticks, since a code span would show our escapes as typed; brackets for links, images
# and references; "<" before what opens a tag or an autolink, and the "!" after it, which keeps a comment, a declaration
# or CDATA from opening and a parser that looks for "<!--" from finding one; "&" before an entity. Emphasis: every
# asterisk, since one inside a word opens it as well ("Lehrer*innen sowie Schüler*innen"), and a run of underscores
# that could open it - one after a letter or digit or before a blank cannot, and without an opener nothing is
# emphasised. An address the sources block prints as text keeps its "Brechung_(Physik)": an autolink of GFM would
# keep a backslash in it (audit 2026-09-29, T2). Measured on the eleven topics of the sample archives and part 3 of
# the WLO samples: three asterisks gained a backslash (the birth sign in "(* 23. Januar 1840"), no underscore;
# every underscore escaped would have put one into five addresses of the sources list. 200,000 random strings of
# underscores, asterisks, letters, blanks and punctuation rendered no emphasis with markdown-it and read back as typed.
_ACTIVE = re.compile(r"[\\`\[\]*]|<(?=[A-Za-z/?])|(?<=<)!|&(?=#?[A-Za-z0-9]+;)|(?<!\w)_+(?=[^\s_])")
# The first sign of a line that makes it a heading, quote, list, rule, fence or table row, and the dot or bracket
# after the number of an ordered list. A delimiter row of a table may start with the colon of its alignment
# (":--- | :---"), which made two lines of a description a table (audit 2026-09-29, T11).
_LINE_START = re.compile(r"^([ \t]*)(?:([#>+\-*=_~|:])|(\d{1,9})([.)]))", re.M)
# A backslash before ASCII punctuation, which CommonMark reads as that sign
_ESCAPED = re.compile(r"\\([!-/:-@\[-`{-~])")
# What defuse leaves: an escape, the service's own comments (section marker, facet marker, end of a facet block) and
# the start of a link to a web address. What it defuses: any other link or image target, an image, a reference
# definition with a target that is no web address, and every other start of HTML.
_OWN = r"\\.|<!-- (?:kompendium:section [^\n]*?|f: [^\n]*?|/f) -->|\]\(<?(?i:https?://)"
_DEFUSE = re.compile(
    rf"(?P<kept>{_OWN})|(?P<target>\]\()|(?P<image>!(?=\[))|(?P<html><(?=[A-Za-z/?])|(?<=<)!)"
    r"|(?P<definition>\](?=:[ \t]*\n?[ \t]*(?!<?(?i:https?://))\S))"
)


def one_line(text: str) -> str:
    """Free text as it was typed, on one line: a line break would break the line it goes into - the TULLU line
    of the sources, a line of a material block in part 3, an element of part 2."""
    return " ".join(text.split())


def plain_label(text: str) -> str:
    """A label from a source as text of one line, shown as typed: no line break, and nothing in it starts markup."""
    return escape_text(one_line(text))


def escape_text(text: str) -> str:
    """Text from a source as markdown that shows it as typed: nothing in it opens a tag, comment, link, image, code
    span, emphasis or entity, and no line of it reads as a heading, quote, list, rule, fence or table row. CommonMark
    also ends a line at a lone CR, so every line end becomes an LF first."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _ACTIVE.sub(lambda match: "".join("\\" + sign for sign in match.group(0)), text)
    return _LINE_START.sub(_escaped_start, text)


def _escaped_start(match: re.Match[str]) -> str:
    indent, sign, number, delimiter = match.groups()
    return f"{indent}\\{sign}" if sign is not None else f"{indent}{number}\\{delimiter}"


def unescape(text: str) -> str:
    """The text as typed again, for whoever reads a compendium back: every escape as the sign it stands for."""
    return _ESCAPED.sub(r"\1", text)


# Every reference definition, whatever its target, and the escapes it must not take apart
_DEFINITION = re.compile(r"\\.|\](?=:[ \t]*\n?[ \t]*\S)")


def no_definitions(markdown: str) -> str:
    """``markdown`` without a reference definition: one in a kept block of an earlier compendium turned the citation
    markers of every block into links, wherever it pointed (audit 2026-09-29, T6). ``defuse`` lets a definition to
    a web address through; a writer of the service writes none."""
    return _DEFINITION.sub(lambda match: match.group(0) if len(match.group(0)) == 2 else "\\]", markdown)


def defuse(markdown: str) -> str:
    """``markdown`` with nothing left that runs, loads or leads anywhere but to a web address: every start of HTML
    except the service's own comments, every image and every link or reference target that is no web address is
    escaped. The net behind every writer; what they write through ``escape_text`` passes unchanged."""
    return _DEFUSE.sub(_defused, markdown)


def _defused(match: re.Match[str]) -> str:
    kept = match.group("kept")
    return kept if kept is not None else "\\" + match.group(0)


def link_target(url: str) -> str:
    """``url`` as a markdown link target that cannot end early: with spaces or parentheses it goes in angle
    brackets - ``…/wiki/Linse_(Optik)`` is a real material URL, which a parser reading up to the first ``)``
    would cut - and angle brackets inside it are percent-encoded."""
    if any(char in url for char in " ()<>"):
        return f"<{url.replace('<', '%3C').replace('>', '%3E')}>"
    return url


def web_target(value: str | None) -> str | None:
    """``value`` as a link target when it is a web address, else ``None``: no other scheme becomes a link."""
    address = one_line(value or "")
    return link_target(address) if address.lower().startswith(WEB_SCHEMES) else None


def table_cell(text: str) -> str:
    """A value as one table cell: on one line, no pipe that would split the row, shown as typed."""
    return plain_label(text.replace("|", "–"))


def web_link(label: str, url: str | None) -> str:
    """``label``, markdown already, as a link to ``url`` when that is a web address, else the label alone."""
    target = web_target(url)
    return f"[{label}]({target})" if target else label


def code_span(text: str) -> str:
    """``text`` on one line as a code span that no backtick inside it can end early (CommonMark takes a run of
    backticks longer than any run inside as the fence)."""
    text = one_line(text)
    fence = "`" * (max((len(run) for run in re.findall("`+", text)), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"
