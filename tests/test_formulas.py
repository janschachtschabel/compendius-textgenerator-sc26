"""Formulas come out as text: the LaTeX the writing LLM puts in its texts (D83) and the alttext of the formulas of the
Wikipedia archive (D84). The compendium is markdown for readers without a math renderer, and the escaping of markdown
showed every backslash."""

import time

import pytest

from app.markup.formulas import plain_formulas, plain_latex

NNBSP = chr(0x202F)  # the narrow no-break space of \, - in digit groups and between a number and its unit
BACKSLASH = chr(92)
OVERLINE, MACRON, DOT_ABOVE = chr(0x305), chr(0x304), chr(0x307)  # combining marks above the letter before them
VECTOR_ARROW = chr(0x20D7)


def latex(text: str) -> str:
    """``text`` with every / standing for a backslash, so the cases read like the LaTeX the model wrote."""
    return text.replace("/", BACKSLASH).replace("<slash>", "/")


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        # the formulas of the texts of M59, as the model wrote them
        (
            latex("Brechungsgesetz /(n_1/sin/theta_1=n_2/sin/theta_2/), wobei"),
            "Brechungsgesetz n₁ sin θ₁ = n₂ sin θ₂, wobei",
        ),
        (
            latex(
                "/(6/,/mathrm{CO_2}+6/,/mathrm{H_2O}+/text{Lichtenergie}/rightarrow/mathrm{C_6H_{12}O_6}+6/,/mathrm{O_2}/)"
            ),
            f"6{NNBSP}CO₂ + 6{NNBSP}H₂O + Lichtenergie → C₆H₁₂O₆ + 6{NNBSP}O₂",
        ),
        (latex("/(I=I_1+I_2+2/sqrt{I_1I_2}/cos/delta/)"), "I = I₁ + I₂ + 2√(I₁I₂) cos δ"),
        (latex("/(/nabla^2u-(1<slash>v^2)/partial^2u<slash>/partial t^2=0/)"), "∇²u − (1/v²)∂²u/∂t² = 0"),
        (latex("/(I=I_0/cos^2/theta/)"), "I = I₀ cos² θ"),
        (latex("/(1{,}22/lambda<slash>D/)"), "1,22λ/D"),
        (latex("/(d/sin/theta=m/lambda/)"), "d sin θ = mλ"),
        (
            latex("Im Vakuum beträgt /(c/) exakt /(299/,792/,458/ /mathrm{m/,s^{-1}}/)."),
            f"Im Vakuum beträgt c exakt 299{NNBSP}792{NNBSP}458 m{NNBSP}s⁻¹.",
        ),
        (latex("Der Brechungsindex ist /(n=c<slash>v/)."), "Der Brechungsindex ist n = c/v."),
        # display math, fractions, roots and indices the inventory did not happen to hold
        (latex("/[E=mc^2/]"), "E = mc²"),
        (latex("/(v=/frac{s}{t}/)"), "v = s/t"),
        (latex("/(E_{kin}=/frac{1}{2}mv^2/)"), "Eₖᵢₙ = ½mv²"),
        (latex("/(x=/frac{-b/pm/sqrt{b^2-4ac}}{2a}/)"), "x = (−b ± √(b² − 4ac))/(2a)"),
        (latex("/(T_{eff}/approx 5800/,/mathrm{K}/)"), f"T_eff ≈ 5800{NNBSP}K"),
        (latex("/(/Delta E=h/nu/)"), "ΔE = hν"),
        (latex("/(/vec{F}=m/cdot/vec{a}/)"), "F⃗ = m · a⃗"),
        (latex("/(e^{i/omega t}/)"), "e^(iωt)"),
    ],
)
def test_latex_becomes_text(written: str, expected: str) -> None:
    assert plain_formulas(written) == expected


def test_text_without_latex_and_the_markers_of_citations_stay_as_they_are() -> None:
    text = "Licht breitet sich geradlinig aus [2]. Ein Euro kostet 5 $ und drei kosten 15 $ [3]."
    assert plain_formulas(text) == text


def test_brackets_without_a_formula_in_them_are_no_display_formula() -> None:
    """A rhyme scheme, a label or a citation in escaped brackets is text: only signs of a formula make one."""
    for text in ("/[ababbcbc/]", "/[Modellwissen/]", "/[3/]", "/[Robert Hill/]"):
        assert plain_formulas(latex(text)) == latex(text)
    assert plain_formulas(latex("/[a^2+b^2=c^2/]")) == "a² + b² = c²"


def test_an_unclosed_formula_and_an_unknown_command_lose_nothing() -> None:
    assert plain_formulas(latex("Es gilt /(n_1 ohne Ende.")) == latex("Es gilt /(n_1 ohne Ende.")
    assert plain_formulas(latex("/(/foo{x}+1/)")) == "foox + 1"


def test_a_long_answer_full_of_openings_takes_linear_time() -> None:
    """Model text can carry what a source smuggled in; the search for the end of a formula is bounded."""
    text = latex("/(") * 20_000 + "x"
    started = time.perf_counter()
    plain_formulas(text)
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(
    ("alttext", "expected"),
    [
        # alttexts of the formulas in school articles of the Wikipedia archive (M61), as the parser reads them
        (latex("{/displaystyle n_{1}/sin /delta _{1}=n_{2}/sin /delta _{2}}"), "n₁ sin δ₁ = n₂ sin δ₂"),
        (latex("{/displaystyle a^{2}+b^{2}=c^{2}}"), "a² + b² = c²"),
        (latex("{/displaystyle R={/frac {U}{I}}=/mathrm {const.} }"), "R = U<slash>I = const.".replace("<slash>", "/")),
        (latex("{/displaystyle E_{/mathrm {kin} }={/frac {1}{2}}mv^{2}}"), "Eₖᵢₙ = ½mv²"),
        (latex("{/displaystyle {/tfrac {3}{4}}}"), "¾"),
        (latex("{/displaystyle 0{,}75}"), "0,75"),
        (latex("{/textstyle /mathrm {/langle CH_{2}O/rangle } }"), "⟨CH₂O⟩"),
        (latex("{/displaystyle D=/mathbb {R} /setminus /{3/}}"), "D = ℝ ∖ {3}"),
        (latex("{/displaystyle /{u_{1},/dotsc ,u_{n}/}}"), "{u₁, …, uₙ}"),
        (
            latex("{/displaystyle k=/left/{X/in E~/vert ~{/overline {MX}}=r/right/}.}"),
            f"k = {{X ∈ E | M{OVERLINE}X{OVERLINE} = r}}.",
        ),
        (
            latex("{/displaystyle {/begin{aligned}a&={/sqrt {c^{2}-b^{2}}}//b&={/sqrt {c^{2}-a^{2}}}/end{aligned}}}"),
            "a = √(c² − b²); b = √(c² − a²)",
        ),
        (latex("{/displaystyle f(t)={/begin{pmatrix}r/cos t//r/sin t/end{pmatrix}}}"), "f(t) = (r cos t; r sin t)"),
        (
            latex("{/displaystyle |x|={/begin{cases}x,&x/geq 0//-x,&x<0/end{cases}}}"),
            "|x| = {x, x ≥ 0; −x, x < 0}",
        ),
        (latex("{/displaystyle f={1 /over T}/quad }"), "f = 1<slash>T".replace("<slash>", "/")),
        (latex("{/displaystyle {/ce {2H2 + O2 -> 2H2O}}}"), "2H₂ + O₂ → 2H₂O"),
        (
            latex(
                "{/displaystyle /mathrm {CO_{2}+4/langle H/rangle / /xrightarrow {Licht} {}/ /langle CH_{2}O/rangle +/ H_{2}O} }"
            ),
            "CO₂ + 4⟨H⟩ → (Licht) ⟨CH₂O⟩ + H₂O",
        ),
        (latex("{/displaystyle /approx 0{,}29/ /mathrel {/widehat {=}} / 29/ /%}"), "≈ 0,29 ≙ 29 %"),
        (
            latex("{/displaystyle K_{2}=1000/;/mathrm {/euro} /cdot (1+2/cdot 0{,}05)=1100/;/mathrm {/euro} }"),
            "K₂ = 1000 € · (1 + 2 · 0,05) = 1100 €",
        ),
        (
            latex("{/displaystyle {/bar {v}}=10{,}6/cdot 10^{6}/,{/frac {/mathrm {m} }{/mathrm {s} }}}"),
            f"v{MACRON} = 10,6 · 10⁶{NNBSP}m/s",
        ),
        (latex("{/displaystyle {/dot {v}}/,v}"), f"v{DOT_ABOVE}{NNBSP}v"),
        (latex("{/displaystyle /operatorname {sgn}(p)}"), "sgn(p)"),
        (latex("{/displaystyle {/color {red}7}+1}"), "7 + 1"),
        (latex("{/displaystyle /sqrt[{n}]{x}}"), "ⁿ√x"),
        (latex("{/displaystyle 90^{/circ }}"), "90°"),
        (latex("{/displaystyle V_{/rm {M}}=500/ldots 1000/cdot /mathrm {NA} }"), "V_M = 500…1000 · NA"),
        (latex("{/displaystyle /sum _{i=1}^{n}i}"), "∑_(i = 1)ⁿi"),
        (latex("{/displaystyle /operatorname {arccot} x}"), "arccot x"),
        (latex("{/displaystyle x_{2}=5/ .}"), "x₂ = 5."),
        (
            latex("{/displaystyle 6/arctan {/tfrac {1}{/sqrt {3}}}+{/frac {12}{5}}}"),
            "6 arctan 1<slash>√3 + 12<slash>5".replace("<slash>", "/"),
        ),
        (latex("{/displaystyle {/tbinom {n}{k}}={n /choose k}}"), "(n über k) = (n über k)"),
        (latex("{/displaystyle {/overrightarrow {AB}}/ominus /imath }"), f"AB{VECTOR_ARROW} ⊖ ı"),
        # a matrix without brackets lays out a system of equations; its empty cells are no values
        (
            latex("{/displaystyle {/begin{matrix}a_{11}x_{1}&+&/cdots &=&b_{1}///vdots &&&&/vdots /end{matrix}}}"),
            "a₁₁x₁ + ⋯ = b₁; ⋮ ⋮",
        ),
    ],
)
def test_an_alttext_of_the_archive_becomes_text(alttext: str, expected: str) -> None:
    assert plain_latex(alttext) == expected


def test_an_alttext_with_a_command_the_converter_does_not_know_gives_nothing() -> None:
    """A formula of the archive with an unknown command stays out, as every formula did before D84: its name without
    the backslash would print a word that is not there ("underbrace1 − 1")."""
    assert plain_latex(latex("{/displaystyle /underbrace {1-1} _{x}}")) is None
    assert plain_latex(latex("{/displaystyle /begin{tabular}{cc}a&b/end{tabular}}")) is None
    assert plain_latex(latex("{/displaystyle {/mathbb {K}}}")) is None  # no double-struck letter of its own
    assert plain_latex("") is None
