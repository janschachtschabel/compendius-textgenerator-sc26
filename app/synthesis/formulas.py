"""Formulas in LaTeX, as text: those the writing LLM puts in its texts (D83) and those of the Wikipedia archive (D84).

The model writes formulas as LaTeX between \\( \\) or \\[ \\] - 48 of them in the 36 texts of M59, mostly in physics
and chemistry. A compendium is markdown for readers without a math renderer, and the escaping of markdown showed every
backslash, so a teacher read "\\(n_1\\sin\\theta_1\\)". This turns the LaTeX the model uses into readable text with
Unicode: indices and powers as sub- and superscripts where Unicode has them, Greek letters, operators, functions,
fractions and roots - "n₁ sin θ₁ = n₂ sin θ₂". What it does not know keeps its name without the backslash; text
outside the delimiters, a dollar sign included, stays as it is.

The Wikipedia archive holds its formulas as MathML with their LaTeX as alttext, and the parser dropped them, so the
text kept holes ("Ihr Formelzeichen ist das ."): 10,006 formulas in 70 of 80 school articles (M61). ``plain_latex``
writes such an alttext as text, and as nothing when it holds a command or an environment this reader does not know:
that formula stays out as before, for a name without its backslash would print a word the article does not have. For
the archive it knows more than the model writes - aligned equations, matrices and cases, the double-struck letters,
accents, the chemistry of mhchem, the fraction "over" - and the signs of M61.
"""

from __future__ import annotations

import re

NNBSP = chr(0x202F)  # \, : the narrow no-break space of digit groups and between a number and its unit
VECTOR_ARROW = chr(0x20D7)  # the combining arrow above a letter, for \vec
BACKSLASH = chr(92)
MAX_FORMULA_CHARS = 500  # the search for the end of a formula is bounded, so an answer full of openings stays linear
MAX_ALTTEXT_CHARS = 1_000  # longer alttexts are derivations over many lines (91 of the 10,006 of M61); they stay out
_FORMULA = re.compile(rf"\\\((.{{1,{MAX_FORMULA_CHARS}}}?)\\\)|\\\[(.{{1,{MAX_FORMULA_CHARS}}}?)\\\]", re.DOTALL)
_MATHLIKE = re.compile(r"[\\^_=+<>]")  # signs of a formula: [ababbcbc], [Modellwissen] or [3] hold none

GREEK = dict(
    zip(
        "alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi rho sigma tau "
        "upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega "
        "varrho varsigma varpi varkappa".split(),
        "αβγδεεζηθϑικλμνξπρστυφφχψωΓΔΘΛΞΠΣΥΦΨΩϱςϖϰ",
        strict=True,
    )
)
RELATIONS = {
    "=": "=", "<": "<", ">": ">", "approx": "≈", "neq": "≠", "ne": "≠", "leq": "≤", "le": "≤", "geq": "≥",
    "ge": "≥", "equiv": "≡", "sim": "∼", "propto": "∝", "rightarrow": "→", "to": "→", "longrightarrow": "→",
    "leftarrow": "←", "leftrightarrow": "↔", "Rightarrow": "⇒", "Leftrightarrow": "⇔", "rightleftharpoons": "⇌",
    "ll": "≪", "gg": "≫",
    # D84: what the archive writes beyond the model's LaTeX (M61)
    "leqslant": "≤", "geqslant": "≥", "simeq": "≃", "cong": "≅", "doteq": "≐", "triangleq": "≜", "mapsto": "↦",
    "implies": "⇒", "iff": "⇔", "Longrightarrow": "⟹", "Leftarrow": "⇐", "gets": "←", "uparrow": "↑",
    "downarrow": "↓", "in": "∈", "notin": "∉", "ni": "∋", "subset": "⊂", "subseteq": "⊆", "supset": "⊃",
    "supseteq": "⊇", "mid": "|", "leftrightharpoons": "⇋", "subsetneq": "⊊", "supsetneq": "⊋", "nmid": "∤",
    "lesssim": "≲", "gtrsim": "≳",
}  # fmt: skip
BINARY = {
    "+": "+", "-": "−", "pm": "±", "mp": "∓", "cdot": "·", "times": "×", "div": "÷", "*": "·",
    "setminus": "∖", "circ": "∘", "wedge": "∧", "land": "∧", "vee": "∨", "lor": "∨", "oplus": "⊕", "otimes": "⊗",
    "odot": "⊙", "ast": "∗", "ominus": "⊖",
}  # fmt: skip
SYMBOLS = {
    "infty": "∞", "partial": "∂", "nabla": "∇", "sum": "∑", "prod": "∏", "int": "∫", "oint": "∮", "hbar": "ħ",
    "ell": "ℓ", "degree": "°", "ldots": "…", "dots": "…", "cdots": "⋯", "angle": "∠", "perp": "⊥",
    "parallel": "∥", "cup": "∪", "cap": "∩", "forall": "∀", "exists": "∃",
    "%": "%", "{": "{", "}": "}", "$": "$", "&": "&", "#": "#", "_": "_",
    "vert": "|", "|": "‖", "colon": ":", "dotsc": "…", "dotsb": "…", "dotsm": "…", "dotso": "…", "dotsi": "…",
    "vdots": "⋮", "ddots": "⋱", "langle": "⟨", "rangle": "⟩", "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈",
    "rceil": "⌉", "euro": "€", "prime": "′", "emptyset": "∅", "varnothing": "∅", "neg": "¬", "lnot": "¬",
    "star": "⋆", "bullet": "•", "Re": "ℜ", "Im": "ℑ", "aleph": "ℵ", "triangle": "△", "square": "□",
    "backslash": "∖", "dagger": "†", "textdegree": "°", "ddagger": "‡", "imath": "ı", "jmath": "ȷ", "top": "⊤",
    "bot": "⊥", "iint": "∬", "iiint": "∭", "bigcap": "⋂", "bigcup": "⋃", "bigoplus": "⨁", "measuredangle": "∡",
    "lbrace": "{", "rbrace": "}",
}  # fmt: skip
FUNCTIONS = frozenset(
    "sin cos tan cot arcsin arccos arctan sinh cosh tanh log ln lg exp lim max min det "
    "sec csc coth arg deg gcd dim ker inf sup Pr bmod mod arsinh arcosh artanh sgn".split()
)
STYLES = frozenset(
    "mathrm text textrm textit mathit mathbf mathsf mathcal boldsymbol mbox "
    "mathfrak mathtt textbf textsf texttt textup textnormal mathnormal emph".split()
)
SPACES = {",": NNBSP, ";": " ", ":": " ", " ": " ", "quad": " ", "qquad": " ", "!": "", ">": " ", "enspace": " "}
FRACTIONS = {("1", "2"): "½", ("1", "3"): "⅓", ("2", "3"): "⅔", ("1", "4"): "¼", ("3", "4"): "¾"}
SUBSCRIPT = str.maketrans("0123456789+−=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")
SUPERSCRIPT = str.maketrans("0123456789+−=()in", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁱⁿ")
_SUBSCRIPTABLE = frozenset("0123456789+−=()aehijklmnoprstuvx")
_SUPERSCRIPTABLE = frozenset("0123456789+−=()in")

# D84: commands that print nothing themselves - sizes, styles of what follows, "left" and "right" before a delimiter
IGNORED = frozenset(
    "displaystyle textstyle scriptstyle scriptscriptstyle limits nolimits left right middle big Big bigg Bigg bigl "
    "bigr Bigl Bigr biggl biggr Biggl Biggr bigm Bigm biggm Biggm rm it bf sf tt cal nonumber notag strut hline "
    "allowbreak".split()
)
SKIPPED = frozenset("color phantom hphantom vphantom vspace label cline".split())  # one argument that prints nothing
DOUBLE_STRUCK = {"N": "ℕ", "Z": "ℤ", "Q": "ℚ", "R": "ℝ", "C": "ℂ", "P": "ℙ", "H": "ℍ"}
ACCENTS = {
    "overline": 0x305, "bar": 0x304, "underline": 0x332, "hat": 0x302, "widehat": 0x302, "tilde": 0x303,
    "widetilde": 0x303, "dot": 0x307, "ddot": 0x308, "check": 0x30C, "breve": 0x306, "acute": 0x301, "grave": 0x300,
    "mathring": 0x30A,
}  # fmt: skip
NEGATED = {"=": "≠", "∈": "∉", "≡": "≢", "⊂": "⊄", "⊆": "⊈", "<": "≮", ">": "≯", "≤": "≰", "≥": "≱", "∼": "≁"}
ARROWS = {"xrightarrow": "→", "xleftarrow": "←", "xrightleftharpoons": "⇌", "xleftrightarrow": "↔"}
# An environment as text: (opening, between cells, between rows, closing); the rows of an aligned system stand as
# one line, joined by semicolons, for a paragraph holds no line breaks
_ALIGNED = ("", " ", "; ", "")
ENVIRONMENTS = {
    **dict.fromkeys(
        "aligned align align* alignat alignat* alignedat gathered gather gather* split eqnarray eqnarray* multline "
        "array matrix smallmatrix".split(),  # a matrix without brackets lays out equations (M61)
        _ALIGNED,
    ),
    "pmatrix": ("(", ", ", "; ", ")"),
    "bmatrix": ("[", ", ", "; ", "]"), "Bmatrix": ("{", ", ", "; ", "}"), "vmatrix": ("|", ", ", "; ", "|"),
    "Vmatrix": ("‖", ", ", "; ", "‖"), "cases": ("{", " ", "; ", "}"), "dcases": ("{", " ", "; ", "}"),
    "rcases": ("", " ", "; ", "}"),
}  # fmt: skip
_SPECIFIED = frozenset({"array", "alignat", "alignat*", "alignedat"})  # a column count or layout follows the name
_ATOMIC = re.compile("[0-9]+(?:,[0-9]+)?|[√∛∜].")  # a number or the root of one sign, which "/" needs no brackets for
_CHEMICAL_INDEX = re.compile(r"(?<=[]A-Za-z)])([0-9]+)")  # digits after an element or a bracket: H2O, (OH)2
_CHEMICAL_SCRIPT = re.compile(r"([_^])(?:{([^{}]*)}|([0-9+-]))")


def plain_formulas(text: str) -> str:
    """``text`` with every LaTeX formula between \\( \\) or \\[ \\] written out as text."""
    return _FORMULA.sub(_replace, text)


def plain_latex(latex: str) -> str | None:
    """One formula of the Wikipedia archive - the LaTeX of its alttext, ``{\\displaystyle …}`` - as text (D84);
    ``None`` when it holds a command or an environment this reader does not know, is too long, or comes out empty."""
    if len(latex) > MAX_ALTTEXT_CHARS:
        return None
    formula = _Formula(latex, unknown=set())
    text = formula.text()
    return text if text and not formula.unknown else None


def _replace(match: re.Match[str]) -> str:
    inline, display = match.groups()
    if display is not None and not _MATHLIKE.search(display):
        return match.group(0)  # escaped brackets around text, no display formula
    return _Formula(inline if inline is not None else display).text()


class _Formula:
    """A small reader of the LaTeX of one formula: pieces of text, relations, binary operators and functions, joined
    with spaces around relations, binary operators and functions as typeset formulas show them.

    ``unknown`` collects the commands and environments it does not know (D84); without it a command keeps its name.
    """

    def __init__(self, source: str, unknown: set[str] | None = None) -> None:
        self.source = source
        self.at = 0
        self.unknown = unknown

    def text(self) -> str:
        return _joined(self._pieces(closing=None))

    def _pieces(self, closing: str | None) -> list[tuple[str, str]]:
        pieces: list[tuple[str, str]] = []
        while self.at < len(self.source):
            sign = self.source[self.at]
            if sign == closing:
                self.at += 1
                return _over(pieces)
            self.at += 1
            if sign == BACKSLASH:
                piece = self._command()
                if piece is not None:
                    pieces.append(piece)
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
            elif sign == "~":
                pieces.append(("text", " "))
            elif sign == ",":
                pieces.append(("text", "," if self._decimal(pieces) else ", "))
            else:
                pieces.append(("text", sign))
        return _over(pieces)

    def _decimal(self, pieces: list[tuple[str, str]]) -> bool:
        """Whether a comma stands between digits, as in a German decimal written without braces: 3,5."""
        return self.source[self.at : self.at + 1].isdigit() and bool(pieces) and pieces[-1][1][-1:].isdigit()

    def _command(self) -> tuple[str, str] | None:
        name = re.match(r"[A-Za-z]+|.?", self.source[self.at :], re.DOTALL)
        word = name.group(0) if name else ""
        self.at += len(word)
        for table, kind in ((SPACES, "text"), (GREEK, "text"), (RELATIONS, "relation"), (BINARY, "binary")):
            if word in table:
                return (kind, table[word])
        if word in SYMBOLS:
            return ("text", SYMBOLS[word])
        if word in FUNCTIONS:
            return ("function", word)
        if word in IGNORED:
            if word in ("left", "right", "middle") and self.source[self.at : self.at + 1] == ".":
                self.at += 1  # the delimiter that shows nothing
            return None
        if word in SKIPPED:
            self._raw_argument()
            return None
        return self._structure(word)

    def _structure(self, word: str) -> tuple[str, str] | None:
        """The commands that read arguments: styles, fractions, roots, accents, environments and the rest of D84."""
        if word in STYLES:
            return ("text", self._argument(spaced=word.startswith("text") or word in ("mbox", "emph")))
        if word == "operatorname":
            return ("function", self._argument())
        if word in ("frac", "tfrac", "dfrac", "cfrac"):
            return ("text", _fraction(self._argument(), self._argument()))
        if word in ("binom", "tbinom", "dbinom"):
            return ("text", f"({self._argument()} über {self._argument()})")
        if word == "sqrt":
            return ("text", _root(self._optional(), self._argument()))
        if word in ("vec", "overrightarrow"):
            return ("text", self._argument() + VECTOR_ARROW)
        if word in ACCENTS:
            return self._accent(word)
        if word == "mathbb":
            return ("text", self._double_struck(self._argument()))
        if word in ("mathrel", "mathbin", "mathop", "mathord", "mathopen", "mathclose"):
            kinds = {"mathrel": "relation", "mathbin": "binary"}
            return (kinds.get(word, "text"), self._argument())
        if word in ARROWS:
            self._optional()  # the label below the arrow
            label = self._argument()
            return ("relation", f"{ARROWS[word]} ({label})" if label else ARROWS[word])
        if word == "not":
            return self._negated()
        if word in ("over", "choose"):
            return (word, "")
        if word == "begin":
            return ("text", self._environment())
        if word == "ce":
            return ("text", _chemistry(self._raw_argument()))
        if word == "pmod":
            return ("text", f"(mod {self._argument()})")
        if word == "hspace":
            self._raw_argument()
            return ("text", " ")
        if self.unknown is not None:
            self.unknown.add(word)
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
        if sign != BACKSLASH:
            return sign
        piece = self._command()
        return _joined([piece]) if piece is not None else ""

    def _raw_argument(self) -> str:
        """The next group as written, braces inside it included, or the next sign."""
        while self.at < len(self.source) and self.source[self.at].isspace():
            self.at += 1
        if self.source[self.at : self.at + 1] != "{":
            sign = self.source[self.at : self.at + 1]
            self.at += len(sign)
            return sign
        depth, start = 0, self.at
        while self.at < len(self.source):
            sign = self.source[self.at]
            self.at += 1
            if sign == BACKSLASH:
                self.at += 1  # an escaped brace counts for nothing
            elif sign == "{":
                depth += 1
            elif sign == "}":
                depth -= 1
                if depth == 0:
                    return self.source[start + 1 : self.at - 1]
        return self.source[start + 1 :]

    def _optional(self) -> str:
        if self.source[self.at : self.at + 1] != "[":
            return ""
        end = self.source.find("]", self.at)
        if end < 0:
            return ""
        inner, self.at = self.source[self.at + 1 : end], end + 1
        return _Formula(inner, self.unknown).text()

    def _script(self, base: tuple[str, str], sign: str) -> tuple[str, str]:
        content = self._argument()
        kind, text = base
        if sign == "_":
            if set(content) <= _SUBSCRIPTABLE:
                script = content.translate(SUBSCRIPT)
            else:
                script = f"_{content}" if content.isalnum() else f"_({content})"
        elif content in ("∘", "°", "′", "′′", "′′′"):  # degrees and primes stand up already
            script = "°" if content == "∘" else content
        else:
            script = content.translate(SUPERSCRIPT) if set(content) <= _SUPERSCRIPTABLE else f"^({content})"
        return (kind if kind == "function" else "text", text + script)

    def _accent(self, word: str) -> tuple[str, str]:
        """A mark above or below each sign of the argument: x̄, M̅X̅; "≙" for the hat over an equals sign."""
        argument = self._argument()
        if argument == "=" and word in ("hat", "widehat"):
            return ("relation", "≙")
        return ("text", "".join(sign + chr(ACCENTS[word]) for sign in argument))

    def _double_struck(self, letters: str) -> str:
        if letters and all(letter in DOUBLE_STRUCK for letter in letters):
            return "".join(DOUBLE_STRUCK[letter] for letter in letters)
        if self.unknown is not None:
            self.unknown.add("mathbb")
        return letters

    def _negated(self) -> tuple[str, str]:
        """What follows a negating slash: "not =" is "≠"."""
        while self.at < len(self.source) and self.source[self.at].isspace():
            self.at += 1
        sign = self.source[self.at : self.at + 1]
        self.at += len(sign)
        piece = self._command() if sign == BACKSLASH else ("relation", RELATIONS.get(sign, sign))
        if piece is not None and piece[1] in NEGATED:
            return ("relation", NEGATED[piece[1]])
        if self.unknown is not None:
            self.unknown.add("not")
        return piece or ("text", "")

    def _environment(self) -> str:
        """An environment between begin and end: its cells and rows as one line (D84)."""
        name = self._raw_argument()
        if name in _SPECIFIED:
            self._raw_argument()  # the column layout or count
        opening, closing_tag = f"{BACKSLASH}begin{{{name}}}", f"{BACKSLASH}end{{{name}}}"
        depth, at = 1, self.at
        while depth:
            begin, end = self.source.find(opening, at), self.source.find(closing_tag, at)
            if end < 0:
                end = len(self.source)
                break
            if 0 <= begin < end:
                depth, at = depth + 1, begin + len(opening)
            else:
                depth, at = depth - 1, end + len(closing_tag)
        body, self.at = self.source[self.at : end], min(len(self.source), end + len(closing_tag))
        if name not in ENVIRONMENTS:
            if self.unknown is not None:
                self.unknown.add(f"begin{{{name}}}")
            return name
        start, between_cells, between_rows, close = ENVIRONMENTS[name]
        rows = []
        for row in _split(body, BACKSLASH * 2):
            row = re.sub(r"^\s*\[[^]]*\]", "", row)  # the space after a line break: \\[2pt]
            cells = [_Formula(cell, self.unknown).text() for cell in _split(row, "&")]
            if any(cells):
                rows.append(between_cells.join(cell for cell in cells if cell).strip())
        return f"{start}{between_rows.join(rows)}{close}"


def _split(body: str, separator: str) -> list[str]:
    """``body`` cut at ``separator`` (a row's \\\\ or a cell's &) outside braces and inner environments."""
    parts, depth, start, at = [], 0, 0, 0
    while at < len(body):
        if body.startswith(f"{BACKSLASH}begin{{", at):
            depth, at = depth + 1, at + 7
        elif body.startswith(f"{BACKSLASH}end{{", at):
            depth, at = depth - 1, at + 5
        elif depth == 0 and body.startswith(separator, at):
            parts.append(body[start:at])
            at = start = at + len(separator)
        elif body[at] == BACKSLASH:
            at += 2  # a command or an escaped sign: its next sign separates nothing
        else:
            depth += {"{": 1, "}": -1}.get(body[at], 0)
            at += 1
    parts.append(body[start:])
    return parts


def _over(pieces: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """A group with "over" in it is a fraction of what stands before and after (plain TeX): {1 over T} is 1/T; with
    "choose" a binomial coefficient."""
    kinds = [kind for kind, _ in pieces]
    at = next((index for index, kind in enumerate(kinds) if kind in ("over", "choose")), None)
    if at is None:
        return pieces
    above, below = _joined(pieces[:at]), _joined(pieces[at + 1 :])
    return [("text", _fraction(above, below) if kinds[at] == "over" else f"({above} über {below})")]


def _chemistry(formula: str) -> str:
    """A formula of mhchem as text: indices after an element or a bracket, charges, arrows - "2H₂ + O₂ → 2H₂O"."""

    def script(match: re.Match[str]) -> str:
        content = (match.group(2) if match.group(2) is not None else match.group(3)).replace("-", "−")
        return content.translate(SUBSCRIPT if match.group(1) == "_" else SUPERSCRIPT)

    text = _CHEMICAL_SCRIPT.sub(script, " ".join(formula.split()))
    for arrow, sign in (("<=>", "⇌"), ("<->", "↔"), ("->", "→"), ("<-", "←")):
        text = text.replace(arrow, f" {sign} ")
    text = _CHEMICAL_INDEX.sub(lambda match: match.group(1).translate(SUBSCRIPT), text)
    return re.sub(" {2,}", " ", text).strip()


def _fraction(numerator: str, denominator: str) -> str:
    if (numerator, denominator) in FRACTIONS:
        return FRACTIONS[(numerator, denominator)]
    return f"{_wrapped(numerator)}/{_wrapped(denominator)}"


def _root(index: str, radicand: str) -> str:
    """√x, ∛x, ∜x, or the index raised before the sign: ⁿ√x."""
    if index in ("", "2"):
        sign = "√"
    elif index in ("3", "4"):
        sign = {"3": "∛", "4": "∜"}[index]
    else:
        sign = (index.translate(SUPERSCRIPT) if set(index) <= _SUPERSCRIPTABLE else f"^({index})") + "√"
    return sign + _wrapped(radicand)


def _wrapped(term: str) -> str:
    """A term of one sign, a number or the root of one sign stands as it is, a longer one in parentheses: √x, 12/5,
    1/√3, √(b² − 4ac), (2a)."""
    return term if len(term) <= 1 or _ATOMIC.fullmatch(term) else f"({term})"


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
            if previous == "function" and text.startswith(("(", "[")):
                out = out.rstrip()  # sin(π/7), as typeset
            out += text
        previous = kind if text else previous
    # a space before the closing full stop or comma of a formula is the space command before it: "x₂ = 5."
    return re.sub(" ([.,])(?= |$)", r"\1", re.sub(" {2,}", " ", out)).strip()
