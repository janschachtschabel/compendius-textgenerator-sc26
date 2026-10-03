"""Formulas the writing LLM puts in LaTeX, as text (D83).

The model writes formulas as LaTeX between \\( \\) or \\[ \\] - 48 of them in the 36 texts of M59, mostly in physics
and chemistry. A compendium is markdown for readers without a math renderer, and the escaping of markdown showed every
backslash, so a teacher read "\\(n_1\\sin\\theta_1\\)". This turns the LaTeX the model uses into readable text with
Unicode: indices and powers as sub- and superscripts where Unicode has them, Greek letters, operators, functions,
fractions and roots - "n₁ sin θ₁ = n₂ sin θ₂". What it does not know keeps its name without the backslash; text
outside the delimiters, a dollar sign included, stays as it is.
"""

from __future__ import annotations

import re

NNBSP = chr(0x202F)  # \, : the narrow no-break space of digit groups and between a number and its unit
VECTOR_ARROW = chr(0x20D7)  # the combining arrow above a letter, for \vec
MAX_FORMULA_CHARS = 500  # the search for the end of a formula is bounded, so an answer full of openings stays linear
_FORMULA = re.compile(rf"\\\((.{{1,{MAX_FORMULA_CHARS}}}?)\\\)|\\\[(.{{1,{MAX_FORMULA_CHARS}}}?)\\\]", re.DOTALL)
_MATHLIKE = re.compile(r"[\\^_=+<>]")  # signs of a formula: [ababbcbc], [Modellwissen] or [3] hold none

GREEK = dict(
    zip(
        "alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi rho sigma tau "
        "upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega".split(),
        "αβγδεεζηθϑικλμνξπρστυφφχψωΓΔΘΛΞΠΣΥΦΨΩ",
        strict=True,
    )
)
RELATIONS = {
    "=": "=", "<": "<", ">": ">", "approx": "≈", "neq": "≠", "ne": "≠", "leq": "≤", "le": "≤", "geq": "≥",
    "ge": "≥", "equiv": "≡", "sim": "∼", "propto": "∝", "rightarrow": "→", "to": "→", "longrightarrow": "→",
    "leftarrow": "←", "leftrightarrow": "↔", "Rightarrow": "⇒", "Leftrightarrow": "⇔", "rightleftharpoons": "⇌",
    "ll": "≪", "gg": "≫",
}  # fmt: skip
BINARY = {"+": "+", "-": "−", "pm": "±", "mp": "∓", "cdot": "·", "times": "×", "div": "÷", "*": "·"}
SYMBOLS = {
    "infty": "∞", "partial": "∂", "nabla": "∇", "sum": "∑", "prod": "∏", "int": "∫", "oint": "∮", "hbar": "ħ",
    "ell": "ℓ", "degree": "°", "circ": "°", "ldots": "…", "dots": "…", "cdots": "⋯", "angle": "∠", "perp": "⊥",
    "parallel": "∥", "in": "∈", "notin": "∉", "subset": "⊂", "cup": "∪", "cap": "∩", "forall": "∀", "exists": "∃",
    "%": "%", "{": "{", "}": "}", "$": "$", "&": "&", "#": "#", "_": "_",
}  # fmt: skip
FUNCTIONS = frozenset("sin cos tan cot arcsin arccos arctan sinh cosh tanh log ln lg exp lim max min det".split())
STYLES = frozenset("mathrm text textrm textit mathit mathbf mathsf mathcal boldsymbol operatorname mbox".split())
SPACES = {",": NNBSP, ";": " ", ":": " ", " ": " ", "quad": " ", "qquad": " ", "!": ""}
FRACTIONS = {("1", "2"): "½", ("1", "3"): "⅓", ("2", "3"): "⅔", ("1", "4"): "¼", ("3", "4"): "¾"}
SUBSCRIPT = str.maketrans("0123456789+−=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")
SUPERSCRIPT = str.maketrans("0123456789+−=()in", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁱⁿ")
_SUBSCRIPTABLE = frozenset("0123456789+−=()aehijklmnoprstuvx")
_SUPERSCRIPTABLE = frozenset("0123456789+−=()in")


def plain_formulas(text: str) -> str:
    """``text`` with every LaTeX formula between \\( \\) or \\[ \\] written out as text."""
    return _FORMULA.sub(_replace, text)


def _replace(match: re.Match[str]) -> str:
    inline, display = match.groups()
    if display is not None and not _MATHLIKE.search(display):
        return match.group(0)  # escaped brackets around text, no display formula
    return _Formula(inline if inline is not None else display).text()


class _Formula:
    """A small reader of the LaTeX of one formula: pieces of text, relations, binary operators and functions, joined
    with spaces around relations, binary operators and functions as typeset formulas show them."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.at = 0

    def text(self) -> str:
        return _joined(self._pieces(closing=None))

    def _pieces(self, closing: str | None) -> list[tuple[str, str]]:
        pieces: list[tuple[str, str]] = []
        while self.at < len(self.source):
            sign = self.source[self.at]
            if sign == closing:
                self.at += 1
                return pieces
            self.at += 1
            if sign == "\\":
                pieces.append(self._command())
            elif sign == "{":
                pieces.append(("text", _joined(self._pieces(closing="}"))))
            elif sign in "_^":
                pieces.append(self._script(pieces.pop() if pieces else ("text", ""), sign))
            elif sign.isspace():
                continue
            elif sign in RELATIONS:
                pieces.append(("relation", RELATIONS[sign]))
            elif sign in BINARY:
                pieces.append(("binary", BINARY[sign]))
            else:
                pieces.append(("text", sign))
        return pieces

    def _command(self) -> tuple[str, str]:
        name = re.match(r"[A-Za-z]+|.?", self.source[self.at :], re.DOTALL)
        word = name.group(0) if name else ""
        self.at += len(word)
        if word in SPACES:
            return ("text", SPACES[word])
        if word in GREEK:
            return ("text", GREEK[word])
        if word in RELATIONS:
            return ("relation", RELATIONS[word])
        if word in BINARY:
            return ("binary", BINARY[word])
        if word in SYMBOLS:
            return ("text", SYMBOLS[word])
        if word in FUNCTIONS:
            return ("function", word)
        if word in STYLES:
            return ("text", self._argument(spaced=word.startswith("text") or word == "mbox"))
        if word == "frac":
            return ("text", _fraction(self._argument(), self._argument()))
        if word == "sqrt":
            index = self._optional()
            radicand = self._argument()
            return ("text", {"3": "∛", "4": "∜"}.get(index, "√") + _wrapped(radicand))
        if word == "vec":
            return ("text", self._argument() + VECTOR_ARROW)
        if word in ("left", "right", "displaystyle", "big", "Big", "bigl", "bigr"):
            return ("text", "")
        return ("text", word)

    def _argument(self, *, spaced: bool = False) -> str:
        """The next group or single sign, as text; a \\text group keeps its spaces."""
        while self.at < len(self.source) and self.source[self.at].isspace():
            self.at += 1
        if self.at >= len(self.source):
            return ""
        if self.source[self.at] == "{":
            self.at += 1
            if spaced:
                end = self.source.find("}", self.at)
                end = len(self.source) if end < 0 else end
                inner, self.at = self.source[self.at : end], end + 1
                return inner
            return _joined(self._pieces(closing="}"))
        sign = self.source[self.at]
        self.at += 1
        return _joined([self._command()]) if sign == "\\" else sign

    def _optional(self) -> str:
        if self.source[self.at : self.at + 1] != "[":
            return ""
        end = self.source.find("]", self.at)
        if end < 0:
            return ""
        inner, self.at = self.source[self.at + 1 : end], end + 1
        return inner

    def _script(self, base: tuple[str, str], sign: str) -> tuple[str, str]:
        content = self._argument()
        kind, text = base
        if sign == "_":
            script = content.translate(SUBSCRIPT) if set(content) <= _SUBSCRIPTABLE else f"_{content}"
        else:
            script = content.translate(SUPERSCRIPT) if set(content) <= _SUPERSCRIPTABLE else f"^({content})"
        return (kind if kind == "function" else "text", text + script)


def _fraction(numerator: str, denominator: str) -> str:
    if (numerator, denominator) in FRACTIONS:
        return FRACTIONS[(numerator, denominator)]
    return f"{_wrapped(numerator)}/{_wrapped(denominator)}"


def _wrapped(term: str) -> str:
    """A term of one sign stands as it is, a longer one in parentheses: √x, √(b² − 4ac), (2a)."""
    return term if len(term) <= 1 else f"({term})"


def _joined(pieces: list[tuple[str, str]]) -> str:
    """The pieces as text: spaces around relations and binary operators, a minus without one where it is a sign, and a
    function apart from its neighbours."""
    out = ""
    previous = "start"
    for kind, text in pieces:
        if kind == "relation":
            out = f"{out.rstrip()} {text} "
        elif kind == "binary":
            unary = previous in ("start", "relation", "binary") or out.endswith("(")
            out = f"{out}{text}" if unary else f"{out.rstrip()} {text} "
        elif kind == "function":
            separated = out and not out.endswith((" ", "(", NNBSP))
            out = f"{out}{' ' if separated else ''}{text} "
        else:
            out += text
        previous = kind if text else previous
    return re.sub(" {2,}", " ", out).strip()
