"""What the model writes carries no markup into a compendium or into a pair of /qa (audit 2026-09-28, SE-17).

SE-04 filtered the model's sentences with patterns on the raw text, each ending at a line end: a tag, a link word or
an image over two lines was whole again once the lines of a paragraph were joined, a "<" in an attribute and nested
brackets slipped past, and a reference definition "[5]: //evil.example/x" turned every evidence number 5 of the
document into a link to it, in the text and in the citation table. The pairs of /qa went out without any filter. An
instruction in a material text or in the keywords of a node is enough to make a model write such things.
"""

from __future__ import annotations

import re

import pytest

from app.llm.budget import TokenBudget
from app.synthesis.llm import LlmSection, LlmSynthesizer
from app.synthesis.qa import parse_pairs
from tests.markdown_safety import tags, unsafe
from tests.test_llm_client import FakeBApi
from tests.test_llm_synthesis import SCORED, SOURCES, _client, _slot

LF = chr(10)
CITED = "Das Thema ist ein Gebiet der Physik [1]."  # a sentence the evidence of SCORED supports
MODEL_TEXT = [
    CITED + " <img src=x" + LF + "onerror=alert(1) >",
    CITED + ' <img alt="<" src=x onerror=alert(2)>',
    "Das Thema ist ein Gebiet der Physik, siehe das [Arbeits" + LF + "blatt](//evil.example/x) [1].",
    "Das Thema ist ein Gebiet der Physik, siehe ![Bild" + LF + "](//evil.example/t.png) [1].",
    "Das [Blatt [1]](javascript:alert(document.cookie)) ist ein Gebiet der Physik [1].",
    CITED + LF + LF + '[1]: //evil.example/x "Titel"',
    "## Eine Überschrift des Modells" + LF + LF + CITED,
    "<script>alert(5)</script> " + CITED,
    CITED + " Mehr steht auf [dieser Seite](https://evil.example/phish) [1].",
    CITED + " <!-- versteckt",
]


@pytest.mark.parametrize("enrich", [False, True])
@pytest.mark.parametrize("answer", MODEL_TEXT)
def test_a_block_the_model_wrote_carries_no_markup(answer: str, enrich: bool) -> None:
    fake = FakeBApi(lambda body: answer)
    budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()

    result = LlmSynthesizer(_client(fake)).write_section(
        _slot(), SCORED, SOURCES, topic="Thema", citation_start=4, budget=budget, enrich=enrich
    )

    assert isinstance(result, LlmSection) and "[5]" in result.text
    # with the row of the citation table the sources block writes for number 5
    document = result.text + LF + LF + "| Beleg |" + LF + "| :---: |" + LF + "| [5] |"
    assert unsafe(document) == []
    assert not {"a", "img", "h2", "script"} & set(tags(document))  # the model's link targets go, web ones too (SE-04)


BS = chr(92)  # spelled out: tools on the way turn escapes in test text into other signs
# An evidence number or the label of model knowledge as a reader of the markup takes it: not escaped
OWN_TOKEN = re.compile("(?<!" + BS + BS + r")\[(?:\d+|Modellwissen)\]")
FORGED = {
    "four digits beside a checked number": ("Das Thema ist ein Gebiet der Physik [1] [1234].", ["[5]"], ["[5]"]),
    "a checked number spelled with zeros": ("Das Thema ist ein Gebiet der Physik [1] [0005].", ["[5]"], ["[5]"]),
    "the label on a cited sentence": ("Das Thema ist ein Gebiet der Physik [Modellwissen] [1].", ["[5]"], ["[5]"]),
    "four digits in model knowledge": (
        CITED + " Der Mond besteht vollständig aus grünem Käse und Schokolade [0012].",
        ["[5]"],
        ["[5]", "[Modellwissen]"],
    ),
}


@pytest.mark.parametrize(("answer", "sources_only", "enriched"), FORGED.values(), ids=FORGED.keys())
def test_only_the_checked_numbers_and_the_label_of_model_knowledge_stay_markup(
    answer: str, sources_only: list[str], enriched: list[str]
) -> None:
    """A number of four digits is none the checks read: "[1234]" stood beside a checked one and "[0012]" in a
    sentence of model knowledge, both as the service's markup, and the label stayed on a cited sentence, with
    sources-only as well (audit 2026-09-29, T3). The words stay, as typed."""
    for enrich, expected in ((False, sources_only), (True, enriched)):
        budget = TokenBudget(per_request=20_000, daily=2_000_000).open_request()
        result = LlmSynthesizer(_client(FakeBApi(lambda body: answer))).write_section(
            _slot(), SCORED, SOURCES, topic="Thema", citation_start=4, budget=budget, enrich=enrich
        )

        assert isinstance(result, LlmSection) and [citation.number for citation in result.citations] == [5]
        assert OWN_TOKEN.findall(result.text) == expected, (enrich, result.text)


def test_the_pairs_the_model_wrote_carry_no_markup() -> None:
    answer = LF.join(
        [
            "Was ist <img src=x onerror=alert(1)> Licht?;Licht ist [Strahlung](javascript:alert(2)).",
            'Was zeigt ![Bild](//evil.example/t.png) das?;Es zeigt <img alt="<" src=x onerror=alert(3)> die Brechung.',
            "Was steht im [Blatt [1]](javascript:alert(4))?;<script>alert(5)</script>Die Brechung.",
            "Was ist Optik?;Die Lehre vom Licht, siehe [hier](https://evil.example/phish).",
        ]
    )

    pairs = parse_pairs(answer, max_answer_length=300)

    assert len(pairs) == 4
    for pair in pairs:
        for text in (pair.question, pair.answer):
            assert unsafe(text) == [] and "a" not in tags(text), text
    assert [pair.answer for pair in pairs][::3] == ["Licht ist Strahlung.", "Die Lehre vom Licht, siehe hier."]
