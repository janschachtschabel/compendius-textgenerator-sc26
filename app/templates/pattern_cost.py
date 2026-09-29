"""How much work a heading pattern can do, checked before a template stores it.

Every heading of a compendium runs through the patterns of every block of its template (app/matching/lexicon.py):
a pattern whose work grows fast with the heading held a worker (audit 2026-09-28, AP-04; audit 2026-09-29, A08).
app/templates/schema.py sets the bounds and refuses a template beyond them.
"""

from __future__ import annotations

import importlib
from functools import lru_cache
from typing import Any

# A heading pattern reads the first HEADING_MAX_CHARS characters of a heading (app/matching/lexicon.py), so its work has
# a bound: the longest of the 390 headings of eval/gold has 91 characters, the longest of the 1,000 most frequent ones
# in eval/headings_top.csv 52
HEADING_MAX_CHARS = 120
STEPS_CAP = 10**12  # counting stops here, far beyond every bound
# The standard library's own parser of patterns, private but in every CPython since 3.11 (tests/test_template_bounds.py
# holds what it is used for); mypy has no stubs for it
_PARSER: Any = importlib.import_module("re._parser")
_CODES: Any = importlib.import_module("re._constants")


def nested_quantifier(pattern: str) -> bool:
    """Whether a repeat of ``pattern`` that has no upper bound holds another repeat of more than one pass, as (a+)+ or
    (a*)* or a repeated group of words do. Such a pattern tries every way to split a heading that nearly matches: its
    time grows exponentially with the length of the heading."""
    repeats = {_CODES.MAX_REPEAT, _CODES.MIN_REPEAT, _CODES.POSSESSIVE_REPEAT}

    def within(items: Any, unbounded_around: bool) -> bool:
        for code, value in items:
            if code in repeats:
                _low, high, inner = value
                if unbounded_around and high > 1:
                    return True
                parts = [(inner, unbounded_around or high == _CODES.MAXREPEAT)]
            elif code == _CODES.SUBPATTERN:
                parts = [(value[-1], unbounded_around)]
            elif code == _CODES.BRANCH:
                parts = [(branch, unbounded_around) for branch in value[1]]
            elif code in (_CODES.ASSERT, _CODES.ASSERT_NOT):
                parts = [(value[1], unbounded_around)]
            elif code == _CODES.ATOMIC_GROUP:
                parts = [(value, unbounded_around)]
            elif code == _CODES.GROUPREF_EXISTS:
                parts = [(branch, unbounded_around) for branch in value[1:] if branch is not None]
            else:
                continue
            if any(within(part, around) for part, around in parts):
                return True
        return False

    return within(_PARSER.parse(pattern), False)


_REPEATS = frozenset({_CODES.MAX_REPEAT, _CODES.MIN_REPEAT, _CODES.POSSESSIVE_REPEAT})
_ONE_CHARACTER = frozenset({_CODES.LITERAL, _CODES.NOT_LITERAL, _CODES.ANY, _CODES.IN})


class _UnboundedGroupError(Exception):
    """An unbounded repeat of more than one character: the ways it can split a heading have no small bound."""


def _one_character(items: Any) -> bool:
    """Whether ``items`` match exactly one character, in one way: a letter, a class such as [ab], or a group of one."""
    if len(items) != 1:
        return False
    code, value = items[0]
    if code == _CODES.SUBPATTERN:
        return _one_character(value[-1])
    return code in _ONE_CHARACTER


def _repeat_ways(body: int, low: int, high: int) -> int:
    """The ways of ``low`` to ``high`` passes of what matches in ``body`` ways: body**low + ... + body**high."""
    if body == 1:
        return min(high - low + 1, STEPS_CAP)
    total, power = 0, 1
    for passes in range(high + 1):
        if passes >= low:
            total += power
        if total >= STEPS_CAP or power >= STEPS_CAP:
            return STEPS_CAP
        power *= body
    return total


def _ways(items: Any) -> int:
    """At most how many ways ``items`` can match at one position of a heading of HEADING_MAX_CHARS characters."""
    total = 1
    for code, value in items:
        if code in _REPEATS:
            low, high, inner = value
            if _one_character(inner):
                count = max(1, min(high, HEADING_MAX_CHARS) - low + 1)
            elif high == _CODES.MAXREPEAT:
                raise _UnboundedGroupError
            else:
                count = _repeat_ways(_ways(inner), low, high)
        elif code in (_CODES.BRANCH, _CODES.GROUPREF_EXISTS):
            branches = value[1] if code == _CODES.BRANCH else [branch for branch in value[1:] if branch is not None]
            count = sum(_ways(branch) for branch in branches)
        elif code == _CODES.SUBPATTERN:
            count = _ways(value[-1])
        elif code in (_CODES.ASSERT, _CODES.ASSERT_NOT):
            count = _ways(value[1])
        elif code == _CODES.ATOMIC_GROUP:
            count = _ways(value)
        elif code == _CODES.GROUPREF:
            count = HEADING_MAX_CHARS + 1  # compares up to a whole heading, on every way that reaches it
        else:
            count = 1
        total = min(total * count, STEPS_CAP)
    return total


def _anchored(parsed: Any) -> bool:
    """Whether ``parsed`` can match only at the start of a heading, so that search tries one position, not every one."""
    if not len(parsed):
        return False
    code, value = parsed[0]
    if code != _CODES.AT:
        return False
    if value == _CODES.AT_BEGINNING_STRING:
        return True
    return value == _CODES.AT_BEGINNING and not parsed.state.flags & _CODES.SRE_FLAG_MULTILINE


@lru_cache(maxsize=4096)  # a template's check and every reload of the volume ask again for the same patterns
def pattern_steps(pattern: str) -> int | None:
    """At most how many steps ``search`` takes with ``pattern`` on a heading of HEADING_MAX_CHARS characters: the ways
    the pattern can match at one position, times the positions it is tried at - one when it starts with ^. None when
    an unbounded repeat (*, +, {n,}) repeats more than one character, as (a|aa)+ does: its ways have no small bound.

    A sequence multiplies the ways of its parts and alternatives add theirs up. A repeat of one character has a way
    for each length it can take, a bounded repeat of more the ways of each number of passes, a lookaround the ways of
    its content and a back reference one way for each character it compares. The count is an upper bound; the
    optimizations of the re module often make a pattern much faster than it says.

    Measured 2026-09-29 (Python 3.13 on a laptop, best of five runs, three rounds): of 19 families of allowed patterns
    built to backtrack - overlapping alternatives in a row, optional or repeated, adjacent and lazy repeats,
    lookaheads, back references - the largest within PATTERN_STEPS_MAX took at most 0.77 ms on a heading of
    HEADING_MAX_CHARS characters, at most about 100 ns per step; a template at TEMPLATE_PATTERN_STEPS_MAX took at most
    2.6 ms per heading in HeadingLexicon.classify. Twelve .* in a row, which the check before this one let through,
    took 21.5 s on 24 characters (audit 2026-09-29, A08).
    """
    parsed = _PARSER.parse(pattern)
    try:
        ways = _ways(parsed)
    except _UnboundedGroupError:
        return None
    return min(ways * (1 if _anchored(parsed) else HEADING_MAX_CHARS + 1), STEPS_CAP)
