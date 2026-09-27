"""Text of sources other people type into, made safe to stand in the markdown of a compendium.

Part 3 treated repository text this way from the start; part 2 put the labels and IRIs of MEM in unfiltered (audit
2026-09-27, SE-05): the harvest turns "&lt;!--" into "<!--", which opened a comment that hid the rest of the
document, and the IRI of a node or area was never checked before it became a link target - "javascript:alert(…)"
was rendered. Both parts now share these helpers.
"""

from __future__ import annotations

# Brackets in a link text would end the link early or open another one; escaped, CommonMark shows them as typed
LINK_TEXT_ESCAPE = str.maketrans({"[": r"\[", "]": r"\]"})
WEB_SCHEMES = ("https://", "http://")


def one_line(text: str) -> str:
    """Free text as it was typed, on one line: a line break would break the line it goes into - the TULLU line
    of the sources, a line of a material block in part 3, an element of part 2."""
    return " ".join(text.split())


def no_comment(text: str) -> str:
    """``text`` without ``<!--``: a value from a source must not open a facet marker, close a block or hide what
    follows in an HTML comment. The ``!`` after the ``<`` is escaped, which CommonMark shows as typed."""
    return text.replace("<!--", r"<\!--")


def plain_label(text: str) -> str:
    """A label from a source as text of one line: no comment, no link, no line break."""
    return no_comment(one_line(text)).translate(LINK_TEXT_ESCAPE)


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
