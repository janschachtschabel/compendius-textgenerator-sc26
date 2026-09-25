"""The rule stage of /qa (D55): varied questions from the parse, the templates, the glossary and the actors.

The parses are the ones de_core_news_md gave in the image (tests/recorded_spacy.py); the questions are what a
teacher should get from them. Every guard stands for a wrong question the prototype asked on real compendium
texts on 2026-09-25 - a pronoun nobody can resolve, a subject that reads as the object, a year left behind.
"""

from __future__ import annotations

from app.domain.models import ArticleSection, Paragraph, Source
from app.synthesis.actors import Actor, build_actors_section
from app.synthesis.glossary import build_glossary
from app.synthesis.qa_questions import clause_questions
from app.synthesis.qa_rules import (
    Candidate,
    actor_candidates,
    choose,
    glossary_candidates,
    is_person,
    rule_pairs,
    template_questions,
)
from app.synthesis.qa_words import parse_ready
from tests.recorded_spacy import RecordedNlp

NLP = RecordedNlp()


def asked(sentence: str, *, topic: str = "", person: str = "") -> set[tuple[str, str]]:
    doc = NLP(parse_ready(sentence))
    return {(question.kind, question.text) for question in clause_questions(doc, topic=topic, person=person)}


def templated(sentence: str) -> list[tuple[str, str]]:
    return [(question.kind, question.text) for question in template_questions(sentence, NLP(parse_ready(sentence)))]


# --- questions from the clause ------------------------------------------------------------------------------------


def test_a_time_in_front_becomes_wann_and_a_person_pronoun_the_name() -> None:
    sentence = "Im Jahr 1922 erhielt er den Nobelpreis für Physik."
    assert asked(sentence, person="Albert Einstein") == {
        ("Wann", "Wann erhielt Albert Einstein den Nobelpreis für Physik?")
    }
    assert asked(sentence) == set(), "without a person topic 'er' stays unresolved, and such a question is unclear"


def test_a_time_and_an_agent_in_the_middle_are_moved_to_the_front() -> None:
    assert asked("Der erste Elektromotor wurde 1829 von Ányos Jedlik gebaut.") == {
        ("Wann", "Wann wurde der erste Elektromotor von Ányos Jedlik gebaut?"),
        ("Von wem", "Von wem wurde der erste Elektromotor 1829 gebaut?"),
        ("Was", "Was wurde 1829 von Ányos Jedlik gebaut?"),
    }


def test_seit_asks_seit_wann() -> None:
    assert asked("Seit 1992 verbreitete sich das Leitbild der nachhaltigen Entwicklung in der Politik.") == {
        ("Wann", "Seit wann verbreitete sich das Leitbild der nachhaltigen Entwicklung in der Politik?")
    }


def test_a_person_subject_is_wer_even_when_the_parse_calls_it_a_noun() -> None:
    assert asked("Einstein wurde 1879 in Ulm geboren.") == {
        ("Wann", "Wann wurde Einstein in Ulm geboren?"),
        ("Wo", "Wo wurde Einstein 1879 geboren?"),
        ("Wer", "Wer wurde 1879 in Ulm geboren?"),
    }


def test_a_place_asks_wo() -> None:
    assert asked("Der Mauna Loa liegt auf Hawaii.") == {
        ("Wo", "Wo liegt der Mauna Loa?"),
        ("Was", "Was liegt auf Hawaii?"),
    }


def test_a_weil_clause_asks_warum_about_the_main_clause() -> None:
    sentence = "Von 1896 bis 1901 war er staatenlos, weil er keinen Militärdienst leisten wollte."
    assert asked(sentence, person="Albert Einstein") == {
        ("Wann", "Wann war Albert Einstein staatenlos?"),
        ("Warum", "Warum war Albert Einstein von 1896 bis 1901 staatenlos?"),
    }


def test_a_dass_clause_is_no_object_that_blocks_wer() -> None:
    assert asked("Christiaan Huygens bemerkte um 1650, dass Licht sich wie eine Welle ausbreitet.") == {
        ("Wann", "Wann bemerkte Christiaan Huygens, dass Licht sich wie eine Welle ausbreitet?"),
        ("Wer", "Wer bemerkte um 1650, dass Licht sich wie eine Welle ausbreitet?"),
    }


def test_a_thing_subject_asks_was() -> None:
    assert asked("Die Nutzung des Stromes begann in der Mitte des 19. Jahrhunderts mit der Telegrafie.") == {
        ("Wann", "Wann begann die Nutzung des Stromes mit der Telegrafie?"),
        ("Was", "Was begann in der Mitte des 19. Jahrhunderts mit der Telegrafie?"),
    }


def test_a_subject_behind_the_verb_is_asked_for_with_the_front_field_moved_behind_the_verb() -> None:
    """The name stands in apposition behind the head noun "Franzose"; the entity makes it a person."""
    assert asked("Im Jahr 1832 konstruierte der Franzose Hippolyte Pixii einen Generator.") == {
        ("Wann", "Wann konstruierte der Franzose Hippolyte Pixii einen Generator?"),
        ("Wer", "Wer konstruierte im Jahr 1832 einen Generator?"),
    }


def test_an_object_and_a_number_ask_was_and_wie_viele() -> None:
    assert asked("Einstein veröffentlichte 1905 vier bahnbrechende Arbeiten.") == {
        ("Wann", "Wann veröffentlichte Einstein vier bahnbrechende Arbeiten?"),
        ("Objekt", "Was veröffentlichte Einstein 1905?"),
        ("Wie viele", "Wie viele bahnbrechende Arbeiten veröffentlichte Einstein 1905?"),
        ("Wer", "Wer veröffentlichte 1905 vier bahnbrechende Arbeiten?"),
    }


def test_a_prepositional_object_asks_wo_and_the_preposition() -> None:
    assert asked("Klimaveränderungen beruhen oft auf mehreren Faktoren.") == {
        ("Wo+Präposition", "Worauf beruhen Klimaveränderungen oft?")
    }


def test_a_verb_that_governs_its_preposition_asks_with_it_and_a_naming_word_is_no_subject_to_ask_for() -> None:
    """The parse calls "von der Insel Vulcano" a modifier; "ableiten von" makes it the verb's own phrase."""
    assert asked("Das Wort „Vulkan“ leitet sich von der Insel Vulcano ab.") == {
        ("Wo+Präposition", "Wovon leitet sich das Wort „Vulkan“ ab?")
    }


def test_a_year_split_off_before_the_full_stop_leaves_no_year_in_wann() -> None:
    """spaCy reads a final "1893." as one ordinal token; parse_ready splits it, so the number joins its phrase."""
    assert parse_ready("im Jahr 1893.") == "im Jahr 1893 ."
    assert asked("Wilhelm Wien erweiterte das Strahlungsgesetz im Jahr 1893.") == {
        ("Wann", "Wann erweiterte Wilhelm Wien das Strahlungsgesetz?"),
        ("Objekt", "Was erweiterte Wilhelm Wien im Jahr 1893?"),
        ("Wer", "Wer erweiterte das Strahlungsgesetz im Jahr 1893?"),
    }


def test_a_demonstrative_leaves_the_question_unclear_and_asks_nothing() -> None:
    assert asked("Diese Form des Stroms bezeichnet man auch als Konvektionsstrom.") == set()


def test_was_is_not_asked_when_the_object_would_read_as_the_subject() -> None:
    """ "Was erzählt das Privatleben …?" reads as a question about what the private life tells."""
    questions = asked("Das Stück erzählt das Privatleben von Albert Einstein.")
    assert not any(text.startswith("Was erzählt das Privatleben") for _, text in questions)


def test_a_colon_ends_the_clause_and_what_follows_it_stays_in_the_answer() -> None:
    """The list behind the colon hangs on the object as an apposition; the question takes the object without it."""
    assert asked("Einstein nannte zwei Gründe: den Krieg und die Politik.") == {
        ("Wer", "Wer nannte zwei Gründe?"),
        ("Objekt", "Was nannte Einstein?"),
        ("Wie viele", "Wie viele Gründe nannte Einstein?"),
    }


def test_a_clause_that_points_ahead_to_its_colon_asks_nothing() -> None:
    """ "Was haben Historiker so rekonstruiert?" - what "so" stands for comes only behind the colon."""
    assert asked("Historiker haben die Geschichte der Stadt so rekonstruiert: Zuerst kamen die Könige.") == set()


def test_a_vague_time_asks_no_wann() -> None:
    questions = asked("Die Staatsform wandelte sich im Laufe der Zeit zur Republik.")
    assert not any(kind == "Wann" for kind, _ in questions)


def test_the_topic_itself_is_no_answer_to_ask_for() -> None:
    questions = asked("Das Römische Reich war ein Staat der Antike.", topic="Römisches Reich")
    assert not any(kind == "Was" for kind, _ in questions), "the answer would be the topic of the whole quiz"


def test_an_object_of_one_of_two_joined_verbs_asks_nothing() -> None:
    sentence = "Das Konzept beschreibt die Herstellung von Gütern und behandelt die Pflege von Daten."
    assert not any(kind == "Objekt" for kind, _ in asked(sentence))


def test_a_plural_subject_is_not_asked_for_with_a_singular_question_word() -> None:
    assert asked("Gleichströme sind ab 2 mA spürbar.") == set()


def test_a_dash_that_cuts_off_the_verb_particle_asks_nothing() -> None:
    sentence = "Am 1. März 2025 fand im Theater die Uraufführung des Stücks Einstein – Eine Zeitreise statt."
    assert asked(sentence) == set()


def test_an_abstract_phrase_is_no_place() -> None:
    assert asked("Im Gegensatz dazu steht die direkte Demokratie.") == set()


def test_the_participle_of_a_full_verb_completes_no_verb() -> None:
    """Only an auxiliary takes a participle into its clause; "findet sich bezogen auf" is no "Worauf findet …"."""
    questions = asked("Die erste Erwähnung findet sich bezogen auf die Attische Demokratie bei Herodot.")
    assert not any(text.startswith("Worauf") for _, text in questions)


def test_reported_speech_in_the_subjunctive_asks_nothing() -> None:
    assert asked("Die Wirkung sei so nicht möglich.") == set()


def test_a_second_main_clause_behind_a_comma_ends_the_first() -> None:
    assert asked("Oft wird die These vertreten, in Deutschland sei das Recht stabil.") == {
        ("Was", "Was wird oft vertreten?")
    }


def test_a_word_that_answers_an_earlier_sentence_leaves_the_question_unclear() -> None:
    assert asked("Die Wahl obliegt aber einzig der gewählten Vertretung.") == set()
    assert asked("Das Mittelalter liegt also zwischen Antike und Neuzeit.") == set()
    assert asked("Die Definition war wegweisend für den Begriff.") == set(), "which Begriff?"


def test_a_second_root_inside_the_clause_is_a_parse_not_to_trust() -> None:
    """The parse made the name the object and the rest a sentence of its own; "Wen kritisiert …?" came of it."""
    assert asked("Jürgen Kaube kritisiert Crouchs normative Herangehensweise.") == set()


# --- templates ----------------------------------------------------------------------------------------------------


def test_a_definition_takes_the_sentences_own_article_and_tense() -> None:
    assert templated("Ein Vulkan ist eine geologische Struktur.") == [("Definition", "Was ist ein Vulkan?")]
    assert templated("Das Römische Reich war ein Staat der Antike.") == [("Definition", "Was war das Römische Reich?")]
    assert templated("Nachhaltigkeit ist ein Prinzip für den Umgang mit Ressourcen.") == [
        ("Definition", "Was versteht man unter Nachhaltigkeit?")
    ]


def test_als_x_bezeichnet_man_asks_what_is_called_x() -> None:
    assert templated("Als Nachhaltigkeitsstrategie bezeichnet man einen Plan zur Umsetzung von Zielen.") == [
        ("Definition", "Was bezeichnet man als Nachhaltigkeitsstrategie?")
    ]


def test_a_person_is_defined_with_wer() -> None:
    assert templated("Albert Einstein war ein Physiker und Nobelpreisträger.") == [
        ("Definition", "Wer war Albert Einstein?")
    ]


def test_no_definition_without_a_noun_in_front_or_an_article_behind_the_verb() -> None:
    assert templated("Das war eine lange Mauer mit einem Graben.") == []
    assert templated("Der Rotor ist leicht und schnell.") == []
    assert templated("Das Konzept beschreibt die Herstellung von Gütern und behandelt die Pflege von Daten.") == []


def test_parts_and_purpose_agree_with_the_verb() -> None:
    assert templated("Theorien bestehen aus Begriffssystemen und Aussagen.") == [
        ("Bestandteile", "Woraus bestehen Theorien?")
    ]
    assert templated("Eine Sammellinse dient der Bündelung von Lichtstrahlen.") == [
        ("Zweck", "Wozu dient eine Sammellinse?")
    ]


# --- glossary and actors ------------------------------------------------------------------------------------------


def _source(title: str, lead: str, *, primary: bool = False) -> Source:
    return Source(
        source_id=title,
        project="wikipedia",
        title=title,
        url=f"https://de.wikipedia.org/wiki/{title.replace(' ', '_')}",
        is_primary=primary,
        sections=[ArticleSection(paragraphs=[Paragraph(text=lead)])],
    )


def test_the_glossary_asks_for_its_definitions_and_the_topics_own_ones_first() -> None:
    """Built with the compendium's own builder, so a change of its table breaks this test, not the endpoint."""
    primary = _source("Optik", "Die Optik ist ein Gebiet der Physik.", primary=True)
    others = [
        _source("Auge", "Das Auge ist ein Sinnesorgan für Licht."),
        _source("Niels Bohr", "Niels Bohr war ein dänischer Physiker."),
        _source("Vulkaneifel", "Die Vulkaneifel ist ein Mittelgebirge bis 700 m ü. NHN."),
        _source("Einstein-de-Haas-Effekt", "Er ist ein makroskopischer Nachweis des Spins."),
    ]
    markdown = build_glossary("Optik", primary, [primary, *others], aliases=["Lehre vom Licht"])
    found = [(c.kind, c.question, c.answer) for c in glossary_candidates(markdown, NLP)]
    assert found == [
        ("Definition", "Was ist die Optik?", "Die Optik ist ein Gebiet der Physik."),
        ("Begriff", "Was ist das Auge?", "Das Auge ist ein Sinnesorgan für Licht."),
        ("Begriff", "Wer war Niels Bohr?", "Niels Bohr war ein dänischer Physiker."),
    ], "the alias, the cut definition and the one that is no definition of its term are left out"


def test_a_term_of_several_words_without_an_article_is_asked_for_as_a_term() -> None:
    """ "Was versteht man unter Nachhaltige Entwicklung?" is no German; the quoted term keeps its own form."""
    lead = "Nachhaltige Entwicklung ist eine Entwicklung für heutige und künftige Generationen."
    primary = _source("Nachhaltige Entwicklung", lead, primary=True)
    markdown = build_glossary("Nachhaltigkeit", primary, [primary], aliases=[])
    assert [c.question for c in glossary_candidates(markdown, NLP)] == [
        "Was versteht man unter dem Begriff „Nachhaltige Entwicklung“?"
    ]


class _PersonEntity:
    label_ = "PER"

    def __init__(self, text: str) -> None:
        self.text = text


class _AllPersonDoc:
    def __init__(self, text: str) -> None:
        self.ents = [_PersonEntity(text)]


def test_a_single_word_term_is_no_person_whatever_the_parse_says() -> None:
    """A parse that calls a whole definition a person asked "Wer ist Konkordanzdemokratie?" on 2026-09-25."""
    lead = "Konkordanzdemokratie ist ein Typ der Demokratie mit breiter Beteiligung."
    primary = _source("Konkordanzdemokratie", lead, primary=True)
    markdown = build_glossary("Konkordanzdemokratie", primary, [primary], aliases=[])
    assert [c.question for c in glossary_candidates(markdown, _AllPersonDoc)] == [
        "Was versteht man unter Konkordanzdemokratie?"
    ]


def test_the_actors_ask_who_or_what_they_are_without_brackets_and_cut_summaries() -> None:
    actors = [
        Actor(
            "Niels Bohr",
            "Person",
            "Niels Bohr (* 7. Oktober 1885 in Kopenhagen) war ein dänischer Physiker.",
            "u",
            [],
            "",
        ),
        Actor("Benjamin Franklin", "Person", "Benjamin Franklin (* 6.", "u", [], ""),
        Actor("Club of Rome", "Organisation", "Der Club of Rome ist ein Zusammenschluss von Fachleuten.", "u", [], ""),
        Actor(
            "Politische Partei",
            "Organisation",
            "Eine politische Partei ist eine Vereinigung von Menschen.",
            "u",
            [],
            "",
        ),
    ]
    for visible in (False, True):  # visible facets add bracketed functions behind the summary
        found = [(c.kind, c.question, c.answer) for c in actor_candidates(build_actors_section(actors, visible))]
        assert found == [
            ("Person", "Wer war Niels Bohr?", "Niels Bohr war ein dänischer Physiker."),
            ("Akteur", "Was ist der Club of Rome?", "Der Club of Rome ist ein Zusammenschluss von Fachleuten."),
            ("Akteur", "Was ist eine politische Partei?", "Eine politische Partei ist eine Vereinigung von Menschen."),
        ], visible


# --- choosing and the pairs ---------------------------------------------------------------------------------------


def _candidate(origin: str, kind: str, question: str) -> Candidate:
    return Candidate(origin=origin, kind=kind, question=question, answer=f"Satz {origin}.")


def test_the_kinds_take_turns_before_one_repeats() -> None:
    candidates = [
        _candidate("s0", "Wann", "Wann A?"),
        _candidate("s1", "Wann", "Wann B?"),
        _candidate("s2", "Was", "Was C?"),
        _candidate("s3", "Wo", "Wo D?"),
    ]
    assert [c.question for c in choose(candidates, 3)] == ["Wann A?", "Was C?", "Wo D?"]
    assert [c.question for c in choose(candidates, 4)] == ["Wann A?", "Was C?", "Wo D?", "Wann B?"]


def test_every_sentence_gets_one_question_before_any_gets_a_second() -> None:
    candidates = [
        _candidate("s0", "Wann", "Wann A?"),
        _candidate("s0", "Was", "Was A?"),
        _candidate("s1", "Wer", "Wer B?"),
    ]
    assert [c.question for c in choose(candidates, 2)] == ["Wann A?", "Wer B?"]
    assert [c.question for c in choose(candidates, 3)] == ["Wann A?", "Wer B?", "Was A?"]


def test_glossary_terms_and_actors_only_fill_up_what_the_text_leaves() -> None:
    candidates = [_candidate("g0", "Begriff", "Was ist das Auge?"), _candidate("s0", "Was", "Was A?")]
    assert [c.question for c in choose(candidates, 1)] == ["Was A?"]
    assert [c.question for c in choose(candidates, 2)] == ["Was A?", "Was ist das Auge?"]


def test_one_term_is_asked_for_once_whoever_asks_for_it() -> None:
    candidates = [
        _candidate("s0", "Definition", "Was versteht man unter Optik?"),
        _candidate("g0", "Definition", "Was ist die Optik?"),
        _candidate("g1", "Begriff", "Wer war Niels Bohr?"),
        _candidate("a0", "Person", "Wer war Niels Bohr?"),
    ]
    assert [c.question for c in choose(candidates, 10)] == ["Was versteht man unter Optik?", "Wer war Niels Bohr?"]


def test_a_person_topic_is_recognised_by_its_entity() -> None:
    assert is_person("Albert Einstein", NLP) and not is_person("Vulkan", NLP)


def test_the_pairs_are_varied_answered_with_their_sentence_and_bounded() -> None:
    text = (
        "Einstein wurde 1879 in Ulm geboren. Die Theorie war nicht nur neu. "
        "Einstein veröffentlichte 1905 vier bahnbrechende Arbeiten. "
        "Wilhelm Wien erweiterte das Strahlungsgesetz im Jahr 1893."
    )
    pairs = rule_pairs(text, nlp=NLP, count=3, max_answer_length=300)
    assert len(pairs) == 3
    assert len({pair.question.split()[0] for pair in pairs}) >= 2, "not three questions of one kind"
    assert all(pair.answer in text for pair in pairs), "the answer is the sentence, nothing invented"
    assert not any("nicht nur" in pair.answer for pair in pairs), "half of a thought is no answer"
    assert len({pair.answer for pair in pairs}) == 3, "three sentences before any answers twice"
    short = rule_pairs(text, nlp=NLP, count=1, max_answer_length=20)
    assert len(short) == 1 and len(short[0].answer) <= 20


def test_a_person_topic_resolves_er_in_the_pairs() -> None:
    pairs = rule_pairs(
        "Im Jahr 1922 erhielt er den Nobelpreis für Physik.",
        nlp=NLP,
        count=5,
        max_answer_length=300,
        topic="Albert Einstein",
    )
    assert [pair.question for pair in pairs] == ["Wann erhielt Albert Einstein den Nobelpreis für Physik?"]
