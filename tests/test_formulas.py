"""Formulas the writing LLM puts in LaTeX come out as text: the compendium is markdown for readers without a math
renderer, and the escaping of markdown showed every backslash (D83)."""

import time

import pytest

from app.synthesis.formulas import plain_formulas

NNBSP = chr(0x202F)  # the narrow no-break space of \, - in digit groups and between a number and its unit
BACKSLASH = chr(92)


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
