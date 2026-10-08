"""Citation checks on LLM output (PLAN.md 4.7, D26): pure text functions, no LLM, no network.

A sentence survives when it carries a valid evidence number and its content words occur in the chunks it cites.
Markers are normalised first (``[1, 2]`` to ``[1][2]``, paragraph-style ``Satz. Satz. [2]``), so that the
renumbering into the global citation sequence sees every marker.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from decimal import Decimal

from app.markup.citations import CITATION_MARKER_RE as _MARKER_RE
from app.markup.facets import END_MARKER
from app.markup.safe_markdown import escape_text
from app.prose import ends_with_abbreviation, split_sentences, tokenize

# Support check: share of a sentence's content stems that occur in the chunks it cites. Measured with
# gpt-5.6-luna on 2026-09-18 (175 sentences): median 0.73; inference sentences that only carry a marker
# score 0.00 to 0.17, the weakest faithful paraphrases 0.20 and above.
MIN_SUPPORT = 0.2
MIN_CONTENT_STEMS = 3  # shorter sentences carry too little signal to judge
STEM_CHARS = 6
# A number of a cited sentence its evidence does not name is no evidence: shared words and a valid marker let
# 1,000,000 Euro pass for evidence of 10,000 (audit 2026-10-02, A03). A value counts in any of its spellings,
# 10.000 as 10000, 4,6 Milliarden as 4.600.000.000. Of 72 cited sentences with numbers best-quality-generated wrote
# on three topics (2026-10-03) none named a number its evidence lacked; the small ones were values and dates (7°,
# 3. Januar), so they count as well; digits grouped by a point or any space are one number (15 372)
_SCALES = {
    "tausend": 10**3,
    "mio": 10**6,
    "million": 10**6,
    "millionen": 10**6,
    "mrd": 10**9,
    "milliarde": 10**9,
    "milliarden": 10**9,
}
# the word of scale right after a number: matched from its end, since a pattern of number and word tried from every
# digit of a run and went back over the rest of it, 38 s for 20,000 digits
_SCALE_RE = re.compile(r"\s*(tausend|millionen|million|mio|milliarden|milliarde|mrd)\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d{1,3}(?:[. \u00a0\u2009\u202f]\d{3})+(?:,\d+)?(?!\d)|\d+(?:,\d+)?")
_GROUP_RE = re.compile(r"[. \u00a0\u2009\u202f](?=\d{3})")
# a number in brackets refers, it claims no quantity: a forged marker such as [1234] beside a checked one
_REFERENCE_RE = re.compile(r"\\?\[\d+\\?\]")

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
# What the model writes goes into a document to publish, and its prompts carry foreign text: an instruction placed
# there could make it write a link, an image or markup no source contains (audit 2026-09-27, SE-04). The words of a
# link stay; its target, images, tags and bare addresses go. The patterns run on a unit whose lines are joined: on
# the raw text a tag, a link or an image over two lines was whole again after the join (audit 2026-09-28, SE-17).
# A tag runs to its first ">", whatever "<" stands in it (_without_tags); a target left behind nested brackets goes on
# its own. A target may hold one level of parentheses, as CommonMark allows balanced ones. Each pattern ends at a line
# end or its closing sign, so a run of them costs no more than its length.
_IMAGE_RE = re.compile(r"!\[[^\[\]\n]*\]\((?:[^()\s]|\([^()\s]*\))*\)?")
_LINK_RE = re.compile(r"\[([^\[\]\n]*)\]\((?:[^()\s]|\([^()\s]*\))*\)?")
_TARGET_RE = re.compile(r"\]\((?:[^()\s]|\([^()\s]*\))*\)?")
_TAG_START_RE = re.compile(r"<[A-Za-z/!?]")
_ADDRESS_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
# A sentence that fails a check can stay instead of being dropped: without numbers, inside such a block. The grade
# says why it is unsupported - a conclusion of the model (LLM_UNSUPPORTED_SENTENCES=mark), or knowledge it brought
# along because the request allowed that (enrichment=model-knowledge, docs/umbau.md U4).
CONCLUSION = "Schlussfolgerung"
MODEL_KNOWLEDGE = "Modellwissen"
# What a reader of the rendered text sees behind a sentence of model knowledge (D56, Jan): the comment around it is
# invisible once the markdown is rendered, and a sentence without a number looks like any other then
MODEL_KNOWLEDGE_LABEL = "[Modellwissen]"
_SELF_LABEL_RE = re.compile(r"^\s*Modellwissen\s*:\s*")
# "[5]: //evil.example/x" defines the target of every marker 5 in the document, text and citation table alike
_DEFINITION_RE = re.compile(r"^\s*\[\d{1,4}\]\s*:")


def opening_marker(grade: str) -> str:
    """The facet comment that opens a marked sentence; ``END_MARKER`` closes it."""
    return f"<!-- f: Evidenzgrad={grade} -->"


CONCLUSION_OPEN = opening_marker(CONCLUSION)
MODEL_KNOWLEDGE_OPEN = opening_marker(MODEL_KNOWLEDGE)
_OPENERS = (CONCLUSION_OPEN, MODEL_KNOWLEDGE_OPEN)
_MARKED_RE = re.compile(
    "(?:" + "|".join(re.escape(opener) for opener in _OPENERS) + ")" + r".*?" + re.escape(END_MARKER), re.DOTALL
)
# What may stay markup in a block the model wrote - evidence numbers, the comments around a marked sentence, the
# label - and escape_model_text decides whether it does
_SERVICE_TOKEN_RE = re.compile(
    "|".join([r"\[\d{1,4}\]", *(re.escape(token) for token in (*_OPENERS, END_MARKER, MODEL_KNOWLEDGE_LABEL))])
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
    evidence number consists of. Single and grouped markers go, and the space they leave with them - and so does
    the label of model knowledge (D56), which is apparatus of the same kind.
    """
    text = _MULTI_MARKER_RE.sub("", _MARKER_RE.sub("", text.replace(MODEL_KNOWLEDGE_LABEL, "")))
    # a run of blanks shrinks first: the two patterns behind it backtracked over a long one (review of D60)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)
    return re.sub(r"[ \t]+($|\n)", r"\1", text).strip()


def without_model_knowledge_label(text: str) -> str:
    """``text`` without the label behind its sentences of model knowledge: a finished text goes to end customers
    without it (D76, Jan, 2026-10-02). The comments around each sentence stay, so the markup still tells what the
    model added. The label stands where _as_marked puts it, right before the closing comment; a plain replacement
    stays linear on any text, a block kept from existing_markdown included."""
    return text.replace(f" {MODEL_KNOWLEDGE_LABEL}{END_MARKER}", END_MARKER)


def verify_citations(text: str, valid: set[int], *, mark: str = "") -> tuple[str, int]:
    """Keep only sentences with at least one valid marker; return the cleaned text and the number that failed.

    ``mark`` names the Evidenzgrad a failing sentence is kept under instead of being dropped; empty drops it. A
    question is dropped either way (_is_question).
    """
    dropped = 0
    paragraphs: list[str] = []
    for paragraph in re.split(r"\n\s*\n", _expand_markers(_COMMENT_RE.sub(" ", text))):
        kept: list[str] = []
        for unit in _units(paragraph):
            for sentence in _cited_sentences(_neutralized(unit)):
                if not _MARKER_RE.sub("", sentence).strip(" .;:,!?…()0123456789"):
                    continue  # a marker-only fragment or a list number is noise, not a claim
                if _DEFINITION_RE.match(sentence):
                    dropped += 1  # no claim, and it would turn every marker of its number into a link (SE-17)
                    continue
                markers = [int(m) for m in _MARKER_RE.findall(sentence)]
                if not any(m in valid for m in markers):
                    dropped += 1
                    if mark and not _is_question(sentence):
                        kept.append(_as_marked(sentence, mark))
                    continue
                clean = _MARKER_RE.sub(lambda m: m.group(0) if int(m.group(1)) in valid else "", sentence)
                clean = re.sub(r"\s+([.!?,;:…])", r"\1", collapse(_COMMENT_RE.sub(" ", clean)))
                kept.append(clean)
        if kept:
            paragraphs.append(" ".join(kept))
    return "\n\n".join(paragraphs), dropped


def _neutralized(text: str) -> str:
    """Model text without comments, images, link targets, tags and bare addresses (SE-04, SE-17)."""
    text = _IMAGE_RE.sub(" ", _COMMENT_RE.sub(" ", text))
    text = _TARGET_RE.sub("]", _LINK_RE.sub(lambda match: match.group(1), text))
    return _ADDRESS_RE.sub(" ", _without_tags(text))


def _without_tags(text: str) -> str:
    """``text`` without tags: from each "<" that opens one to the next ">", whatever "<" stands between - an attribute
    may hold one (SE-17). Linear: a start with no ">" after it leaves the rest as it is, as every later one would."""
    pieces: list[str] = []
    position = 0
    while (start := _TAG_START_RE.search(text, position)) is not None:
        end = text.find(">", start.start())
        if end < 0:
            break
        pieces.extend((text[position : start.start()], " "))
        position = end + 1
    pieces.append(text[position:])
    return "".join(pieces)


def neutralize(text: str) -> str:
    """Model text that is no markdown - a pair of /qa - on one line, without comments, images, link targets, tags and
    bare addresses (audit 2026-09-28, SE-17)."""
    return collapse(_neutralized(" ".join(text.split())))


def escape_model_text(text: str, numbers: Collection[int]) -> str:
    """A block the model wrote, as markdown that shows its words as typed (audit 2026-09-28, SE-17): only the comments
    that mark a sentence, the checked evidence ``numbers`` outside such a sentence and the label of model knowledge
    inside one stay markup. What the patterns above missed - nested or escaped brackets, a sign they do not know -
    shows as text, and so does what only looks like the service's own: a number of four digits the checks do not
    read, "[0012]" beside a checked 12, the label on a cited sentence or with sources-only (audit 2026-09-29, T3)."""
    own = {f"[{number}]" for number in numbers}
    pieces: list[str] = []
    position = 0
    marked = ""  # the opener of the marked sentence a token stands in
    for token in _SERVICE_TOKEN_RE.finditer(text):
        found = token.group(0)
        if found in _OPENERS or found == END_MARKER:
            marked = found if found in _OPENERS else ""
        elif found == MODEL_KNOWLEDGE_LABEL:
            if marked != MODEL_KNOWLEDGE_OPEN:
                continue
        elif marked or found not in own:
            continue  # a marked sentence keeps no number (_as_marked)
        pieces.extend((escape_text(text[position : token.start()]), found))
        position = token.end()
    pieces.append(escape_text(text[position:]))
    return "".join(pieces)


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


def _is_question(sentence: str) -> bool:
    """A question claims nothing, so it is no model knowledge and no conclusion either: kept marked, "Wie wird die
    Energie verfügbar gemacht? [Modellwissen]" would read as knowledge. In M31 three of 50 model-knowledge
    sentences were such questions, fillers for both judges (D60)."""
    plain = collapse(_COMMENT_RE.sub(" ", _MARKER_RE.sub("", sentence)))
    return plain.rstrip(" )").endswith("?")  # not a title in quotes: „Was ist Aufklärung?“ (review of D60)


def _as_marked(sentence: str, grade: str) -> str:
    """The sentence without its numbers inside a parseable block: a marker that proves nothing must not stay.

    Model knowledge also carries a visible label inside the block (D56); a conclusion does not.
    """
    # Removing a number can join "-" and "->" into a comment delimiter, so comments are stripped once more.
    plain = re.sub(r"\s+([.!?,;:…])", r"\1", collapse(_COMMENT_RE.sub(" ", _MARKER_RE.sub("", sentence))))
    label = ""
    if grade == MODEL_KNOWLEDGE:
        # The model sometimes labels the sentence itself (M31: "Modellwissen: In Zellstoffwerken …"); one label will do
        plain = _SELF_LABEL_RE.sub("", plain)
        label = f" {MODEL_KNOWLEDGE_LABEL}"
    return f"{opening_marker(grade)}{plain}{label}{END_MARKER}"


def marked_sentence(sentence: str, grade: str = MODEL_KNOWLEDGE) -> str:
    """``sentence`` as a written block carries a marked one: without numbers, labelled when it is model knowledge, and
    its words shown as typed - model text never becomes the service's markup (audit 2026-09-28, SE-17)."""
    return escape_model_text(_as_marked(sentence, grade), ())


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
        if not ends_a_sentence(head):
            continue
        pieces.append(head)
        start = match.end()
    pieces.append(sentence[start:])
    return pieces


def ends_a_sentence(head: str) -> bool:
    """Whether the full stop that ends ``head`` ends a sentence when the next one opens in lower case or with another
    sign the German splitter does not split before: after the markers that cite it, or after a real word."""
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


def _numbers(text: str) -> set[str]:
    """The values of the numbers ``text`` writes in digits, one spelling each: ``10.000``, ``10000`` and ``10
    Tausend`` alike, ``4,6 Milliarden`` as ``4.600.000.000``. Exact and of any length, as ``Decimal`` counts: a float
    overflowed on a long run of digits."""
    values: set[str] = set()
    for match in _NUMBER_RE.finditer(text):
        scale = _SCALE_RE.match(text, match.end())
        value = Decimal(_GROUP_RE.sub("", match.group()).replace(",", "."))
        values.add(str((value * (_SCALES[scale.group(1).lower()] if scale else 1)).normalize()))
    return values


def drop_unsupported(text: str, evidence: Mapping[int, str], *, mark: str = "") -> tuple[str, int]:
    """Drop sentences whose content words barely occur in the chunks they cite, or that name a number none of them
    does; a marker alone proves nothing.

    ``mark`` names the Evidenzgrad such a sentence is kept under instead; empty drops it, and so does a question.
    Returns the text and the number that failed.
    """
    stems_by_number = {number: _stems(chunk_text) for number, chunk_text in evidence.items()}
    numbers_by_number = {number: _numbers(chunk_text) for number, chunk_text in evidence.items()}
    unsupported = 0
    paragraphs: list[str] = []
    for paragraph in text.split("\n\n"):
        kept: list[str] = []
        for sentence in _split_claims(paragraph):
            if sentence.startswith(_OPENERS):
                kept.append(sentence)
                continue
            claim = _MARKER_RE.sub("", sentence)
            own = _stems(claim)
            markers = [int(number) for number in _MARKER_RE.findall(sentence)]
            cited: set[str] = set()
            values: set[str] = set()
            for number in markers:
                cited |= stems_by_number.get(number, set())
                values |= numbers_by_number.get(number, set())
            words_missing = len(own) >= MIN_CONTENT_STEMS and len(own & cited) / len(own) < MIN_SUPPORT
            if words_missing or (markers and not _numbers(_REFERENCE_RE.sub("", claim)) <= values):
                unsupported += 1
                if mark and not _is_question(sentence):
                    kept.append(_as_marked(sentence, mark))
                continue
            kept.append(sentence)
        if kept:
            paragraphs.append(" ".join(kept))
    return "\n\n".join(paragraphs), unsupported


def renumber(text: str, mapping: Mapping[int, int]) -> str:
    return _MARKER_RE.sub(lambda m: f"[{mapping[int(m.group(1))]}]" if int(m.group(1)) in mapping else m.group(0), text)
