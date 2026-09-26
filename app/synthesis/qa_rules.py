"""The rule stage of POST /api/v2/qa (D55): varied questions without a language model.

Three sources feed it, all from the compendium the pairs are about. The sentences of the text give the questions
of the clause (app/synthesis/qa_questions.py: Wann, Wo, Wer, Was, Worauf, Wie viele, Warum …) and of a few templates -
a definition asks "Was ist ein Vulkan?" with the sentence's own article, "Als X bezeichnet man …" asks "Was
bezeichnet man als X?". The glossary of the compendium adds the first definition of each related article, and its
actor list "Wer war Niels Bohr?" - answered with the definition and the first sentence of the person's article.
Nothing is invented: every answer is a sentence of the compendium.

What makes the pairs varied is how they are chosen, not only how many rules there are. The kinds take turns, so
twenty pairs are not twenty year questions, and every sentence is asked once before any is asked twice. Glossary
terms of related articles and the actors only fill up what the text leaves, because they are about the topic's
neighbours rather than the topic. Measured against the old templates (app/synthesis/qa.py) in M30.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.knowledge.segmentation import ends_with_abbreviation, split_sentences
from app.synthesis.qa import MIN_SENTENCE_CHARS, QaPair, cut
from app.synthesis.qa_questions import Question, clause_questions
from app.synthesis.qa_words import parse_ready, unclear, words

# The order in which the kinds take turns; a definition of the topic is the natural first question
KINDS = (
    "Definition", "Wann", "Wer", "Was", "Wo+Präposition", "Objekt", "Wie viele", "Von wem", "Wo", "Warum",
    "Bestandteile", "Zweck",
)  # fmt: skip
FILLER_KINDS = ("Begriff", "Person", "Akteur")  # about the topic's neighbours: only when the text runs out

_FUNCTION_WORDS = frozenset(
    {"als", "im", "in", "bei", "mit", "nach", "von", "auf", "unter", "für", "durch", "zu", "aus", "an", "am"}
)
_ARTICLES = frozenset({"der", "die", "das", "ein", "eine"})
# "der 16." is where a sentence splitter cut "der 16. Präsident"; "Klassen 5 bis 12." ends with its number
_ORDINAL_LEADS = frozenset({"der", "die", "das", "den", "dem", "des", "am", "im", "vom", "zum", "zur", "beim"})
_TERM = r"(?P<term>[A-ZÄÖÜ][\wäöüß-]*(?:\s+[A-ZÄÖÜ][\wäöüß-]*)?)"
# "Ein Vulkan ist eine …", "Nachhaltigkeit ist ein …": an article behind the copula makes it a definition;
# "Der Rotor ist leicht" is none, and "beschreibt" says what a thing does, not what it is
_DEFINITION = re.compile(
    rf"^(?:(?:Der|Die|Das|Ein|Eine)\s+)?{_TERM}(?:\s+(?P<verb>ist|sind|war|waren)\s+(?:ein|eine|einer|der|die|das)\b"
    r"|\s+(?:bezeichnet|bedeutet)\b)"
)
_CALLED = re.compile(rf"^Als {_TERM} bezeichnet man\b")
_NAMED = re.compile(rf"^{_TERM} nennt man\b")
_UNDERSTOOD = re.compile(rf"^Unter (?:dem Begriff )?{_TERM} versteht man\b")
_COPULA_START = re.compile(r"^(?P<np>(?:Der|Die|Das|Ein|Eine)\s+[^,;:()]{1,60}?)\s+(?P<verb>ist|war|sind|waren)\b")
_PARTS = re.compile(
    r"^(?P<subject>.{3,60}?)\s+(?P<verb>besteht aus|bestehen aus|gliedert sich in|gliedern sich in|umfasst|umfassen)\b"
)
_PURPOSE = re.compile(r"^(?P<subject>.{3,60}?)\s+(?P<verb>dient|dienen|ermöglicht|ermöglichen)\b")
_PLURAL_VERB = re.compile(r"(?:bestehen|gliedern|umfassen|dienen|ermöglichen)\b")
_NOT_A_SUBJECT_START = frozenset({"ADV", "ADP"})
# The definition cell is taken whole and trimmed in code: blanks around a lazy cell backtracked cubically on a
# run of blanks in a text the caller sends (review of D60)
_GLOSSARY_ROW = re.compile(r"^\|\s*\*\*(?P<term>[^|*]+)\*\*\s*\|(?P<definition>[^|]+)\|\s*`(?P<relation>[^`]+)`")
_ACTOR_ROW = re.compile(r"^- \*\*\[(?P<name>[^\]]+)\]\([^)]*\)\*\* — (?P<summary>.+)$")
_KIND_HEADING = re.compile(r"^#### (?P<kind>\w+)")
_RELATION_ORDER = {"skos:prefLabel": 0, "skos:narrower": 1, "skos:related": 2}
_ASKED_FOR = re.compile(
    r"^(?:wer (?:war|ist|waren|sind)|was versteht man unter(?: dem begriff)?|was bezeichnet man als|was nennt man"
    r"|was (?:ist|war|sind|waren)(?: der| die| das| ein| eine)?) "
)


@dataclass(frozen=True)
class Candidate:
    origin: str  # the sentence or entry asked; each is asked once before any is asked twice
    kind: str
    question: str
    answer: str


def rule_pairs(
    text: str,
    *,
    nlp: Any,
    count: int,
    max_answer_length: int,
    topic: str | None = None,
    glossary: str = "",
    actors: str = "",
    level_property: str | None = None,
) -> list[QaPair]:
    """Up to ``count`` pairs from the text, then the glossary and actor blocks of its compendium, if any.

    ``topic`` keeps the topic from becoming an answer and, for a person, stands in for "er" and "sie".
    Fewer pairs than ``count`` means the text holds no more questions these rules can ask.
    """
    sentences = [s for s in split_sentences(" ".join(text.split())) if _usable(s)]
    person = topic if topic and is_person(topic, nlp) else ""
    candidates: list[Candidate] = []
    parsed = nlp.pipe([parse_ready(sentence) for sentence in sentences])
    for index, (sentence, doc) in enumerate(zip(sentences, parsed, strict=True)):
        questions = template_questions(sentence, doc) + clause_questions(doc, topic=topic or "", person=person)
        candidates.extend(Candidate(f"s{index}", q.kind, q.text, sentence) for q in questions)
    candidates.extend(glossary_candidates(glossary, nlp))
    candidates.extend(actor_candidates(actors))
    return [
        QaPair(question=chosen.question, answer=cut(chosen.answer, max_answer_length), level_property=level_property)
        for chosen in choose(candidates, count)
    ]


def _usable(sentence: str) -> bool:
    """Neither a line of a flattened list ("Roman von … - 2001: …") nor half of a thought ("nicht nur …")."""
    if len(sentence) < MIN_SENTENCE_CHARS or " - " in sentence:
        return False
    return "nicht nur" not in sentence or "sondern" in sentence


def is_person(name: str, nlp: Any) -> bool:
    return any(entity.label_ == "PER" for entity in nlp(name).ents)


def template_questions(sentence: str, doc: Any) -> list[Question]:
    """Definitions, names, parts and purposes; ``doc`` is the parse of the sentence, for persons and word classes."""
    questions: list[Question] = []
    for pattern, asking in (
        (_CALLED, "Was bezeichnet man als"),
        (_NAMED, "Was nennt man"),
        (_UNDERSTOOD, "Was versteht man unter"),
    ):
        found = pattern.match(sentence)
        if found:
            questions.append(Question("Definition", f"{asking} {found.group('term')}?"))
    definition = _DEFINITION.match(sentence)
    if definition and not questions:
        term = definition.group("term")
        named = sentence[: definition.end("term")]  # "Ein Vulkan", or "Daneben", which is no noun at all
        if (
            term.split()[0].lower() not in _FUNCTION_WORDS | _ARTICLES
            and not unclear(term)
            and _is_noun_phrase(named, doc)
        ):
            if _names_person(term, doc):
                verb = definition.group("verb") or "ist"
                questions.append(Question("Definition", f"Wer {verb} {term}?"))
            else:
                questions.append(Question("Definition", what_is(sentence, term)))
    for pattern, kind, singular, plural in (
        (_PARTS, "Bestandteile", "Woraus besteht", "Woraus bestehen"),
        (_PURPOSE, "Zweck", "Wozu dient", "Wozu dienen"),
    ):
        found = pattern.match(sentence)
        if found and _is_noun_phrase(found.group("subject"), doc) and not unclear(found.group("subject")):
            asking = plural if _PLURAL_VERB.match(found.group("verb")) else singular
            questions.append(Question(kind, f"{asking} {_lower_article(found.group('subject'))}?"))
    return questions


def what_is(sentence: str, term: str) -> str:
    """ "Was ist ein Vulkan?" with the sentence's own article and tense; without an article "Was versteht man unter".

    A term of several words keeps its own form in quotes: "unter Nachhaltige Entwicklung" is no German.
    """
    start = _COPULA_START.match(sentence)
    if start and words(term) <= words(start.group("np")):
        phrase = start.group("np")
        return f"Was {start.group('verb')} {phrase[0].lower()}{phrase[1:]}?"
    if len(term.split()) > 1:
        return f"Was versteht man unter dem Begriff „{term}“?"
    return f"Was versteht man unter {term}?"


def _names_person(term: str, doc: Any) -> bool:
    """Whether a person entity of ``doc`` covers the whole term - a first name alone makes nobody a person."""
    return any(entity.label_ == "PER" and words(term) <= words(entity.text) for entity in doc.ents)


def _is_noun_phrase(subject: str, doc: Any) -> bool:
    """The leading tokens that make up ``subject`` start with no adverb or preposition and hold a noun."""
    tokens, length = [], 0
    for token in doc:
        if length >= len(subject):
            break
        tokens.append(token)
        length += len(token.text_with_ws)
    if not tokens or tokens[0].pos_ in _NOT_A_SUBJECT_START:
        return False  # "Daneben sind …", "Als Reduktionsmittel dienen …": the subject comes later
    return any(token.pos_ in {"NOUN", "PROPN"} for token in tokens)


def _lower_article(subject: str) -> str:
    first, _, rest = subject.partition(" ")
    return f"{first.lower()} {rest}" if first.lower() in _ARTICLES and rest else subject


def glossary_candidates(markdown: str, nlp: Any) -> list[Candidate]:
    """The glossary block of a compendium (app/synthesis/glossary.py) as questions for its definitions.

    The topic's own term and its narrower terms count as definitions, related terms fill up. An alternative name
    is no question, and neither is a definition cut at an abbreviation ("… bis 700 m ü.") or one that does not
    speak of its term ("Er ist ein makroskopischer Nachweis …").
    """
    found: list[tuple[int, Candidate]] = []
    for index, line in enumerate(markdown.splitlines()):
        row = _GLOSSARY_ROW.match(line.strip())
        if row is None or row.group("relation") not in _RELATION_ORDER:
            continue
        # blanks collapsed first: the patterns below backtrack over a long run of them (review of D60)
        # "[^()]", not "[^)]": over a run of "(" every try read to the end (review of D60)
        term = re.sub(r"\s*\([^()]*\)$", "", " ".join(row.group("term").split()))
        definition = " ".join(row.group("definition").split())
        tokens = definition.rstrip(".").split()
        last = tokens[-1] if tokens else ""
        # "… bis 700 m ü." is cut at an abbreviation; "… mit der Ordnungszahl 8." ends with its number (M30),
        # "… der 16." is cut at an ordinal (review of D60)
        ordinal = last.isdigit() and len(tokens) > 1 and tokens[-2].lower() in _ORDINAL_LEADS
        if (
            definition.endswith("…")
            or (len(last) <= 2 and (not last.isdigit() or ordinal))
            or ends_with_abbreviation(definition)
        ):
            continue
        if not words(term) & set(re.findall(r"[\wäöüß]+", definition.lower())[:6]) or unclear(
            " ".join(definition.split()[:3])
        ):
            continue
        # A person needs a name of two words here: a parse once called a whole definition a person, and
        # "Wer ist Konkordanzdemokratie?" came of it
        if len(term.split()) > 1 and _names_person(term, nlp(definition)):
            tense = "war" if "war" in words(definition) else "ist"
            question = f"Wer {tense} {term}?"
        else:
            question = what_is(definition, term)
        relation = row.group("relation")
        kind = "Begriff" if relation == "skos:related" else "Definition"
        found.append((_RELATION_ORDER[relation], Candidate(f"g{index}", kind, question, definition)))
    return [candidate for _, candidate in sorted(found, key=lambda item: item[0])]


def is_glossary_block(markdown: str) -> bool:
    """Whether a generated block is the glossary (app/synthesis/glossary.py): it has glossary rows."""
    return any(_GLOSSARY_ROW.match(line.strip()) for line in markdown.splitlines())


def is_actor_block(markdown: str) -> bool:
    """Whether a generated block is the actor list (app/synthesis/actors.py): actor rows under headings of their
    kinds ("#### Person"). The sources block lists its articles in rows of the same form, without such headings."""
    lines = [line.strip() for line in markdown.splitlines()]
    return any(_KIND_HEADING.match(line) for line in lines) and any(_ACTOR_ROW.match(line) for line in lines)


def actor_candidates(markdown: str) -> list[Candidate]:
    """The actor block of a compendium (app/synthesis/actors.py): "Wer war …?" for a person, "Was ist …?" else.

    The answer is the first sentence of the actor's article without its brackets - dates, pronunciation, visible
    facets. A sentence cut at an abbreviation ("Benjamin Franklin (* 6.") says nothing and is left out.
    """
    candidates: list[Candidate] = []
    kind = ""
    for index, line in enumerate(markdown.splitlines()):
        heading = _KIND_HEADING.match(line.strip())
        if heading:
            kind = heading.group("kind")
            continue
        row = _ACTOR_ROW.match(line.strip())
        if row is None:
            continue
        # blanks collapsed first: the patterns below backtrack over a long run of them (review of D60)
        summary = " ".join(row.group("summary").split())
        summary = re.sub(r"\s*\[[^\[\]]*\]", "", re.sub(r"\s*\([^()]*\)", "", summary))
        summary = " ".join(summary.split())
        if (
            summary.endswith("…")
            or len(summary) < MIN_SENTENCE_CHARS
            or not re.search(r"\b(war|ist|waren|sind)\b", summary)
        ):
            continue
        name = re.sub(r"\s*\([^()]*\)$", "", " ".join(row.group("name").split()))
        tense = "war" if re.search(r"\bwar\b", summary) else "ist"
        if kind == "Person":
            candidates.append(Candidate(f"a{index}", "Person", f"Wer {tense} {name}?", summary))
        else:  # "Was ist eine politische Partei?" with the article and case of the summary
            candidates.append(Candidate(f"a{index}", "Akteur", what_is(summary, name), summary))
    return candidates


def choose(candidates: Sequence[Candidate], count: int) -> list[Candidate]:
    """Up to ``count`` candidates: the kinds take turns and every origin comes once; when the text runs out the
    glossary and the actors fill up, and only then is a sentence asked a second time (Jan, D60).

    In M30 20 of 23 pairs of the glossary and the actors were flawless for both judges, 2 of 5 second questions of a
    sentence. One term is asked for once, whoever asks for it - the text's own definition of the topic and the
    glossary's are the same question in other words.
    """
    chosen: list[Candidate] = []
    used: set[str] = set()
    asked: set[str] = set()
    for kinds, again in ((KINDS, False), (FILLER_KINDS, False), (KINDS, True)):
        pools = {kind: [c for c in candidates if c.kind == kind] for kind in kinds}
        progress = True
        while progress and len(chosen) < count:
            progress = False
            for kind in kinds:
                taken = _take(pools[kind], used if not again else set(), asked)
                if taken is None:
                    continue
                chosen.append(taken)
                used.add(taken.origin)
                asked.add(_asked_for(taken.question))
                progress = True
                if len(chosen) >= count:
                    break
    return chosen


def _take(pool: list[Candidate], used: set[str], asked: set[str]) -> Candidate | None:
    while pool:
        candidate = pool.pop(0)
        if candidate.origin not in used and _asked_for(candidate.question) not in asked:
            return candidate
    return None


def _asked_for(question: str) -> str:
    return _ASKED_FOR.sub("", question.casefold()).rstrip("?").strip().strip("„“")
