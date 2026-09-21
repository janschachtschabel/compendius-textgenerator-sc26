"""Citation checks on LLM output (PLAN.md 4.7, D26): pure text functions, no LLM, no network.

A sentence survives when it carries a valid evidence number and its content words occur in the chunks it cites.
Markers are normalised first (``[1, 2]`` to ``[1][2]``, paragraph-style ``Satz. Satz. [2]``), so that the
renumbering into the global citation sequence sees every marker.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from app.knowledge.segmentation import ends_with_abbreviation, split_sentences
from app.matching.base import tokenize
from app.synthesis.facets import END_MARKER

# Support check: share of a sentence's content stems that occur in the chunks it cites. Measured with
# gpt-5.6-luna on 2026-09-18 (175 sentences): median 0.73; inference sentences that only carry a marker
# score 0.00 to 0.17, the weakest faithful paraphrases 0.20 and above.
MIN_SUPPORT = 0.2
MIN_CONTENT_STEMS = 3  # shorter sentences carry too little signal to judge
STEM_CHARS = 6

_MARKER_RE = re.compile(r"\[(\d{1,3})\]")
# "[1, 2]", "[1; 2]", "[1 und 2]", "[1-3]": forms the model uses although the prompt asks for single markers
_MULTI_MARKER_RE = re.compile(r"\[(\d{1,3}(?:\s*(?:[,;]|und|-|–)\s*\d{1,3})+)\]")
MAX_MARKER_RANGE = 20
# A marker group after the end of a sentence ("Satz. [1]"), followed by a new sentence or the end of the paragraph.
# Inside a sentence ("usw. [1] und …") the marker stays where it is.
_TRAILING_MARKERS_RE = re.compile(r"([.!?…])((?:\s*\[\d{1,3}\])+)(?=\s*$|\s+[A-ZÄÖÜ„\"(\[0-9])")
_QUOTE_END_RE = re.compile(r"(?<=[.!?…][“”\"»«)])\s+(?=[A-ZÄÖÜ„\"(\[0-9])")  # split_sentences misses these
# A sentence that starts in lower case: split_sentences only splits before capitals, so an uncited sentence next
# to it would ride along. The full stop counts as a sentence end after a marker ("… aus [1]. dann …") or after a
# real word; abbreviations and short tokens ("usw.", "ca.") keep the sentence together.
_LOWER_START_RE = re.compile(r"(?<=[.!?])\s+(?=[a-zäöüß])")  # not after "…": that continues the sentence
_LAST_WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüß]+$")
MIN_SENTENCE_END_WORD = 5
_HEADING_RE = re.compile(r"^\s*#{1,6}\s")
# The compendium is parsed by its comment markers (sections, facet blocks): nothing the model writes may look like one.
_COMMENT_RE = re.compile(r"<!--.*?-->|<!--|-->", re.DOTALL)
# A sentence that fails a check can stay instead of being dropped: without numbers, inside such a block. The grade
# says why it is unsupported - a conclusion of the model (LLM_UNSUPPORTED_SENTENCES=mark), or knowledge it brought
# along because the request allowed that (enrichment=model-knowledge, docs/umbau.md U4).
CONCLUSION = "Schlussfolgerung"
MODEL_KNOWLEDGE = "Modellwissen"


def opening_marker(grade: str) -> str:
    """The facet comment that opens a marked sentence; ``END_MARKER`` closes it."""
    return f"<!-- f: Evidenzgrad={grade} -->"


CONCLUSION_OPEN = opening_marker(CONCLUSION)
MODEL_KNOWLEDGE_OPEN = opening_marker(MODEL_KNOWLEDGE)
_OPENERS = (CONCLUSION_OPEN, MODEL_KNOWLEDGE_OPEN)
_MARKED_RE = re.compile(
    "(?:" + "|".join(re.escape(opener) for opener in _OPENERS) + ")" + r".*?" + re.escape(END_MARKER), re.DOTALL
)
_BULLET_RE = re.compile(r"^\s*[-*•–]\s+")
_NUMBERED_RE = re.compile(r"^\s*\d{1,2}[.)]\s+")


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def without_markers(text: str) -> str:
    """The text without its evidence numbers, for something that is read rather than cited.

    The markers belong to the compendium: every sentence of part 1 ends with at least one, and they
    sit inside the block text, not in the markdown around it. Anything built *from* that text reads
    them as words - on 2026-09-21 the question generator built one around a marker, asking what an
    evidence number consists of. Single and grouped markers go, and the space they leave with them.
    """
    text = _MULTI_MARKER_RE.sub("", _MARKER_RE.sub("", text))
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"[ \t]+($|\n)", r"\1", text).strip()


def marker_numbers(text: str) -> list[int]:
    """Evidence numbers in order of first appearance."""
    return list(dict.fromkeys(int(m) for m in _MARKER_RE.findall(text)))


def verify_citations(text: str, valid: set[int], *, mark: str = "") -> tuple[str, int]:
    """Keep only sentences with at least one valid marker; return the cleaned text and the number that failed.

    ``mark`` names the Evidenzgrad a failing sentence is kept under instead of being dropped; empty drops it.
    """
    dropped = 0
    paragraphs: list[str] = []
    for paragraph in re.split(r"\n\s*\n", _expand_markers(_COMMENT_RE.sub(" ", text))):
        kept: list[str] = []
        for unit in _units(paragraph):
            for sentence in _cited_sentences(unit):
                if not _MARKER_RE.sub("", sentence).strip(" .;:,!?…()0123456789"):
                    continue  # a marker-only fragment or a list number is noise, not a claim
                markers = [int(m) for m in _MARKER_RE.findall(sentence)]
                if not any(m in valid for m in markers):
                    dropped += 1
                    if mark:
                        kept.append(_as_marked(sentence, mark))
                    continue
                clean = _MARKER_RE.sub(lambda m: m.group(0) if int(m.group(1)) in valid else "", sentence)
                clean = re.sub(r"\s+([.!?,;:…])", r"\1", collapse(_COMMENT_RE.sub(" ", clean)))
                kept.append(clean)
        if kept:
            paragraphs.append(" ".join(kept))
    return "\n\n".join(paragraphs), dropped


def _expand_markers(text: str) -> str:
    """``[1, 2]`` and ``[1-3]`` become single markers, the only form the checks and the renumbering know."""

    def expand(match: re.Match[str]) -> str:
        numbers: list[int] = []
        for part in re.split(r"\s*(?:[,;]|und)\s*", match.group(1)):
            bounds = [int(b) for b in re.split(r"\s*[-–]\s*", part)]
            if len(bounds) == 2:
                if not 0 <= bounds[1] - bounds[0] <= MAX_MARKER_RANGE:
                    return match.group(0)  # stays text without a marker, so the sentence counts as uncited
                numbers.extend(range(bounds[0], bounds[1] + 1))
            else:
                numbers.extend(bounds)
        return "".join(f"[{n}]" for n in numbers)

    return _MULTI_MARKER_RE.sub(expand, text)


def _units(paragraph: str) -> list[str]:
    """Prose lines joined into one unit; every list line is a unit of its own, so its claim stands alone."""
    units: list[str] = []
    prose: list[str] = []
    for line in paragraph.splitlines():
        if not line.strip() or _HEADING_RE.match(line):
            continue
        if _BULLET_RE.match(line) or _NUMBERED_RE.match(line):
            if prose:
                units.append(" ".join(prose))
                prose = []
            units.append(_BULLET_RE.sub("", line).strip())
        else:
            prose.append(line.strip())
    if prose:
        units.append(" ".join(prose))
    return units


def _as_marked(sentence: str, grade: str) -> str:
    """The sentence without its numbers inside a parseable block: a marker that proves nothing must not stay."""
    # Removing a number can join "-" and "->" into a comment delimiter, so comments are stripped once more.
    plain = re.sub(r"\s+([.!?,;:…])", r"\1", collapse(_COMMENT_RE.sub(" ", _MARKER_RE.sub("", sentence))))
    return f"{opening_marker(grade)}{plain}{END_MARKER}"


def _split_claims(text: str) -> list[str]:
    """Sentences of a text; already marked sentences stay whole."""
    claims: list[str] = []
    position = 0
    for block in _MARKED_RE.finditer(text):
        claims.extend(_split_plain(text[position : block.start()]))
        claims.append(block.group(0))
        position = block.end()
    claims.extend(_split_plain(text[position:]))
    return claims


def _split_plain(text: str) -> list[str]:
    """``split_sentences`` plus two boundaries it misses: after a closing quote or bracket, before a lower-case word."""
    return [
        claim
        for sentence in split_sentences(text)
        for piece in _QUOTE_END_RE.split(sentence)
        for claim in _split_lower_case_starts(piece)
        if claim.strip()
    ]


def _split_lower_case_starts(sentence: str) -> list[str]:
    pieces: list[str] = []
    start = 0
    for match in _LOWER_START_RE.finditer(sentence):
        head = sentence[start : match.start()]
        if not _ends_a_sentence(head):
            continue
        pieces.append(head)
        start = match.end()
    pieces.append(sentence[start:])
    return pieces


def _ends_a_sentence(head: str) -> bool:
    stripped = head.rstrip(" .!?…")
    if _MARKER_RE.search(stripped[-5:]):  # "… aus [1]." is the sentence form the prompt asks for
        return True
    if ends_with_abbreviation(head):
        return False
    last_word = _LAST_WORD_RE.search(stripped)
    return last_word is not None and len(last_word.group(0)) >= MIN_SENTENCE_END_WORD


def _cited_sentences(unit: str) -> list[str]:
    """Sentences of a unit, each carrying the markers that cite it.

    A marker before the full stop ("Satz [2].") cites its own sentence. A marker group after the full stop
    ("Satz. Satz. [2]") is the paragraph style of citing: it covers the unmarked sentences right before it.
    """
    sentences: list[str] = []
    position = 0
    for match in _TRAILING_MARKERS_RE.finditer(unit):
        run = _split_claims(unit[position : match.end(1)])
        group = collapse(match.group(2))
        index = len(run) - 1
        while index >= 0 and not _MARKER_RE.search(run[index]):
            run[index] = _with_markers(run[index], group)
            index -= 1
        sentences.extend(run)
        position = match.end()
    sentences.extend(_split_claims(unit[position:]))
    return sentences


def _with_markers(sentence: str, group: str) -> str:
    stripped = sentence.rstrip()
    if stripped.endswith((".", "!", "?", "…")):
        return f"{stripped[:-1].rstrip()} {group}{stripped[-1]}"
    return f"{stripped} {group}"


def _stems(text: str) -> set[str]:
    return {token[:STEM_CHARS] for token in tokenize(text) if len(token) >= 4}


def drop_unsupported(text: str, evidence: Mapping[int, str], *, mark: str = "") -> tuple[str, int]:
    """Drop sentences whose content words barely occur in the chunks they cite; a marker alone proves nothing.

    ``mark`` names the Evidenzgrad such a sentence is kept under instead; empty drops it. Returns the text
    and the number that failed.
    """
    stems_by_number = {number: _stems(chunk_text) for number, chunk_text in evidence.items()}
    unsupported = 0
    paragraphs: list[str] = []
    for paragraph in text.split("\n\n"):
        kept: list[str] = []
        for sentence in _split_claims(paragraph):
            if sentence.startswith(_OPENERS):
                kept.append(sentence)
                continue
            own = _stems(_MARKER_RE.sub("", sentence))
            cited: set[str] = set()
            for number in _MARKER_RE.findall(sentence):
                cited |= stems_by_number.get(int(number), set())
            if len(own) >= MIN_CONTENT_STEMS and len(own & cited) / len(own) < MIN_SUPPORT:
                unsupported += 1
                if mark:
                    kept.append(_as_marked(sentence, mark))
                continue
            kept.append(sentence)
        if kept:
            paragraphs.append(" ".join(kept))
    return "\n\n".join(paragraphs), unsupported


def renumber(text: str, mapping: Mapping[int, int]) -> str:
    return _MARKER_RE.sub(lambda m: f"[{mapping[int(m.group(1))]}]" if int(m.group(1)) in mapping else m.group(0), text)
