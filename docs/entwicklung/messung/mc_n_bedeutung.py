"""M88: the articles the question N (D63) names for a topic - how often the archive's article of a named title has
another meaning than the topic, why, and what a check would cost, measured in the service's own flow
(``service.generate``, preset balanced, part 1) on the requests of M82: the gold of the article choice
(eval/artikelwahl, 94 requests) and the six group and aspect topics of the profile comparison
(mc_profilvergleich_boegen.py) that are not among them.

M86 found it once: for Optik the model named "Linsen", meaning lenses; the archive's article of that title is the
plant genus (Lens), and its botany was printed under "Gliederung". ``_look_up`` in app/knowledge/topic_articles.py
takes the archive's article of a named title as it stands, a disambiguation page drops out.

Two steps, both in the one-off container with the archives and gpt-6-luna over OpenAI directly (mc_openai_direkt.py):

- fragen: every request ``--runs`` times through ``service.generate``, all requests once before the next round, so
  every run hears a fresh answer of N (OpenAI directly keeps no answers). A run keeps what N heard and answered, the
  titles the archive made of it, the corpus, the printed paragraphs by source and every LLM answer by its question
  (``BApiClient.chat`` with the prompt and a hash of the messages), so the variants can hear the same answers.
- varianten: every run again once per variant of the step that turns a named title into an article (below), each LLM
  answer from the record of the same run; a question the record lacks is asked live and counted. Writes per run and
  variant the titles found, the corpus and the printed paragraphs.

Usage, from docs/entwicklung/messung, one container per part (at most two to four at a time, M59):
  cat mc_openai_direkt.py mc_n_bedeutung.py | MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T \\
      -v "$(pwd -W)/../../../eval/artikelwahl:/artikelwahl:ro" -v <ordner>:/out \\
      -e LLM_ENABLED=true -e B_API_KEY=direct -e B_API_BASE_URL=https://b-api.invalid -e OPENAI_API_KEY \\
      api python -u - fragen /out/m88_fragen_1.json --runs=5 --teil=1/3
The record of the answers goes beside the output (<out>_antworten.json), the printed texts too (<out>_texte.json);
both stay outside the repository. ``NUR=a|b`` runs some requests only (a trial). Then, with the outputs of all
parts of fragen (only the record of the answers is heard; OPENAI_API_KEY only for a question it lacks):
  ... api python -u - titel /out/m88_titel.json /out/m88_fragen_1.json /out/m88_fragen_2.json /out/m88_fragen_3.json
  ... api python -u - varianten /out/m88_varianten_1.json /out/m88_fragen_1.json /out/m88_fragen_2.json \\
      /out/m88_fragen_3.json --teil=1/3
titel is quick: per run the titles of heute, klammer and mehrdeutig (the variants that change titles) from
``ask_topic_articles`` alone, per named title how the archive answers it (``spuren``) and per article the start of
its first paragraph (``anfaenge``) - what the blind sheets need (mc_n_bedeutung_boegen.py). varianten generates a run
anew per variant only when the variant changed its corpus; otherwise the printed paragraphs are those of heute, and
heute itself is compared with the run of fragen (``wie_fragen``: the replay hears the same).
"""

import copy
import dataclasses
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

os.environ["LLM_ENABLED"] = "true"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import yaml  # noqa: E402

import app  # noqa: E402
import app.knowledge.main_article as main_article_module  # noqa: E402
from app.knowledge import corpus_sources as corpus_module  # noqa: E402
from app.knowledge import topic_articles as articles_module  # noqa: E402
from app.knowledge.corpus_sources import NAMED_ORIGIN, LinkedTo  # noqa: E402
from app.knowledge.topic import TopicMention, title_words  # noqa: E402
from app.llm.client import BApiClient, ChatResult, LlmError  # noqa: E402
from app.llm.deadline import Deadline  # noqa: E402

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

MODE = sys.argv[1]
ARGS = [a for a in sys.argv[2:] if not a.startswith("--")]
OPTIONS = dict(a[2:].split("=", 1) for a in sys.argv[2:] if a.startswith("--") and "=" in a)
OUT = Path(ARGS[0])
RUNS = int(OPTIONS.get("runs", "5"))
PART, PARTS = (int(x) for x in OPTIONS.get("teil", "1/1").split("/"))
PRESET = "balanced"
GOLD_DIR = Path(os.environ.get("ARTIKELWAHL", "/artikelwahl"))
GOLD_FILES = ("hauptartikel.yaml", "hauptartikel_validierung.yaml", "hauptartikel_test.yaml")
# The topics of the profile comparison (M48, M52, M82) beside the gold; Optik, Photosynthese and Französische
# Revolution are gold requests already
M82_TOPICS = (
    ("Dichter aus dem Mittelalter", "sammelthema"),
    ("Komponisten der Klassik", "sammelthema"),
    ("Philosophen der Aufklärung", "sammelthema"),
    ("OER-Förderungen", "aspekt"),
    ("Inklusion im Sportunterricht", "aspekt"),
    ("Künstliche Intelligenz im Unterricht", "aspekt"),
)
LEAD_CHARS = 600


def requests() -> list[dict]:
    """The requests of M82 in a fixed order: the three gold files, then the topics of the profile comparison."""
    found = []
    for name in GOLD_FILES:
        for entry in yaml.safe_load((GOLD_DIR / name).read_text("utf-8"))["anfragen"]:
            found.append(
                {"anfrage": entry["anfrage"], "art": entry["art"], "erwartet": entry["erwartet"], "datei": name}
            )
    known = {entry["anfrage"] for entry in found}
    found += [{"anfrage": t, "art": k, "erwartet": None, "datei": "m82"} for t, k in M82_TOPICS if t not in known]
    for number, entry in enumerate(found, 1):
        entry["nr"] = number
    return found


# --- every LLM answer by its question, recorded per run (fragen) or heard again (varianten) -------------------------
CURRENT: dict = {"key": None, "calls": [], "n": [], "replay": []}
COUNT = Counter()
_chat = BApiClient.chat


def question(messages) -> str:
    return hashlib.sha256(json.dumps(list(messages), ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


def chat(self, messages, **kwargs):  # the signature of BApiClient.chat
    prompt = str(kwargs.get("prompt") or "")
    asked = question(messages)
    for call in CURRENT["replay"]:
        if not call.get("_used") and call["prompt"] == prompt and call["frage"] == asked:
            call["_used"] = True
            COUNT["wiederholt"] += 1
            if "fehler" in call:
                raise LlmError(call["fehler"], call.get("status"))
            return ChatResult(**call["result"])
    COUNT["live"] += 1
    try:
        result = _chat(self, messages, **kwargs)
    except LlmError as exc:
        CURRENT["calls"].append({"prompt": prompt, "frage": asked, "fehler": str(exc)[:300], "status": exc.status})
        raise
    CURRENT["calls"].append({"prompt": prompt, "frage": asked, "result": dataclasses.asdict(result)})
    return result


BApiClient.chat = chat

# --- the variants of the step from a named title to an article (varianten) ------------------------------------------
# heute: as built. klammer: a named title without a qualifier becomes "<title> (<word>)" or the same with the
# singular of its last word, where the archive has such an article and the word is one of the request's: a subject,
# a qualifier of the titles N named, a word of the topic or the overview (singulars too) - "Linsen" for Optik becomes
# "Linse (Optik)". anfang: a named article (not the overview) joins the corpus only when its first paragraph names a
# word of the topic, of a subject or of the overview (``TopicMention``). verlinkt: only when it links to or from the
# main article or N's overview (``LinkedTo``, as full-text hits since M25). mehrdeutig: only a name the archive marks
# as ambiguous - a page "<title> (Begriffsklärung)", a singular that is a disambiguation or has such a page, a first
# name or family name article - gets a qualifier as in klammer, and without one its article must pass anfang or
# verlinkt.
# Two narrow rules after the first round (the hits had none of the archive's signs of several meanings):
# fachfremd: a named title whose qualifier is a subject of the catalogue other than the request's drops out
# ("Intervall (Mathematik)" for Intervall in Musik). uebersicht: the overview without its qualifier (V1a, M49) only
# where the first paragraph of that article names the qualifier ("Delta (Geografie)" found the Greek letter).
VARIANTS = ("heute", "klammer", "anfang", "verlinkt", "mehrdeutig", "fachfremd", "uebersicht")
STATE = {"variant": "heute"}
CTX: dict = {}  # the question N in progress: what it heard and answered, its overview, what the variant did
DISAMBIGUATION = " (Begriffsklärung)"
NAME_ARTICLE = re.compile(
    r"(?:ist|sind) (?:ein|eine|der|die) (?:männliche[rn]? |weibliche[rn]? |deutsche[rn]? )?"
    r"(?:Vorname|Familienname|Nachname|Personenname|Name)"
)
_PLURAL_ENDINGS = ("innen", "nen", "en", "n", "e", "s", "er")
_LETTERS = re.compile(r"[^\W\d_]{4,}")


def singular_forms(label: str) -> list[str]:
    """Rough singulars of a named title, on its last word ("Linsen" -> "Linse", "Lins"): only ever looked up."""
    head, _, last = label.rpartition(" ")
    forms = [
        f"{head} {last[: -len(e)]}".strip() for e in _PLURAL_ENDINGS if last.endswith(e) and len(last) > len(e) + 2
    ]
    return [form for form in dict.fromkeys(forms) if form != label]


def capitalized(word: str) -> str:
    return word[:1].upper() + word[1:]


def qualifier_words() -> list[str]:
    """The words a qualifier of the request may be: subjects, qualifiers N used, words of topic and overview."""
    words = list(CTX.get("subjects", []))
    answer = CTX.get("answer") if isinstance(CTX.get("answer"), dict) else {}
    named = answer.get("artikel") if isinstance(answer.get("artikel"), list) else []
    for title in [str(answer.get("uebersicht") or ""), *map(str, named), CTX.get("overview_title") or ""]:
        found = articles_module.QUALIFIER.search(title)
        if found:
            words.append(found.group(0).strip()[1:-1].strip())
    for text in (CTX.get("topic", ""), CTX.get("overview_title") or ""):
        for word in _LETTERS.findall(articles_module.QUALIFIER.sub("", text)):
            words += [capitalized(word), *map(capitalized, singular_forms(word))]
    return [word for word in dict.fromkeys(words) if word]


def with_qualifier(archive, label: str) -> str | None:
    """The article "<label> (<word>)" or "<singular> (<word>)" of a request word, the first the archive has."""
    for base in [label, *singular_forms(label)]:
        for word in qualifier_words():
            title = f"{base} ({word})"
            if not archive.has(title):
                continue
            article = archive.read_article(title)
            if article is not None and not archive.parse(article).is_disambiguation:
                return article.title
    return None


def first_paragraph(archive, title: str) -> str:
    article = archive.read_article(title)
    if article is None:
        return ""
    parsed = archive.parse(article)
    return next((p.text for s in parsed.sections for p in s.paragraphs if p.text.strip()), "")


def ambiguity(archive, label: str, built: str | None) -> list[str]:
    """Why the archive marks a named title as a name of several meanings; empty when it does not."""
    reasons = []
    if archive.has(label + DISAMBIGUATION):
        reasons.append("Begriffsklärung zum Titel")
    for form in singular_forms(label):
        article = archive.read_article(form)
        if (article is not None and archive.parse(article).is_disambiguation) or archive.has(form + DISAMBIGUATION):
            reasons.append(f"Begriffsklärung zur Grundform {form}")
            break
    if built is not None and NAME_ARTICLE.search(first_paragraph(archive, built)[:200]):
        reasons.append("Namensartikel")
    return reasons


def qualifier_of(title: str) -> str | None:
    found = articles_module.QUALIFIER.search(title)
    return found.group(0).strip()[1:-1].strip() if found else None


def other_subject(label: str) -> bool:
    """Whether the qualifier of a named title is a subject of the catalogue (config/subjects.yaml, labels and
    aliases; not the vocabularies, whose terms include fields such as Optik) other than the request's subjects."""
    qualifier = qualifier_of(label)
    named = service.subjects.resolve(qualifier) if qualifier and CTX.get("subjects") else None
    asked = {subject.id for name in CTX.get("subjects", []) if (subject := service.subjects.resolve(name))}
    return named is not None and named.id not in asked


def drop(label: str, built: str, why: str) -> None:
    CTX["checks"].append({"titel": built, "genannt": label, "grund": why, "genommen": False})
    return None


def look_up_variant(archive, label):
    """``topic_articles._look_up`` as built, and in klammer and mehrdeutig the qualifier of the request first."""
    built = _look_up_built(archive, label)
    variant = STATE["variant"]
    if variant == "fachfremd" and not CTX.get("in_overview") and label != CTX.get("overview_title"):
        return built if built is None or not other_subject(label) else drop(label, built, "Fach der Klammer")
    if variant not in ("klammer", "mehrdeutig") or CTX.get("in_overview") or label == CTX.get("overview_title"):
        return built
    if articles_module.QUALIFIER.search(label):  # a named title with a qualifier is specific already
        return built
    reasons = ambiguity(archive, label, built) if variant == "mehrdeutig" else []
    if variant == "mehrdeutig" and not reasons:
        return built
    better = with_qualifier(archive, label)
    if better is not None and better != built:
        CTX["klammer"].append({"genannt": label, "statt": built, "titel": better})
        return better
    if reasons and built is not None:
        CTX["ambiguous"][built] = reasons
    return built


def overview_kept(archive, label):
    """``topic_articles._overview`` as built; the variants keep the overview and leave it unchecked."""
    CTX["in_overview"] = True
    try:
        title = _overview_built(archive, label)
        if STATE["variant"] == "uebersicht" and title is not None and _look_up_built(archive, label) is None:
            # the overview came without its qualifier: only where its first paragraph names the qualifier
            words = title_words(qualifier_of(label) or "")
            if words and not any(TopicMention.of(word).found_in(first_paragraph(archive, title)) for word in words):
                title = drop(label, title, "Übersicht ohne Klammer, erster Absatz ohne das Klammerwort")
    finally:
        CTX["in_overview"] = False
    CTX["overview_title"] = title
    return title


def answer_kept(text):
    data = _read_object_built(text)
    CTX["answer"] = data
    return data


def request_words() -> list[str]:
    words = title_words(CTX.get("topic", ""))
    for text in [*CTX.get("subjects", []), CTX.get("overview_title") or ""]:
        words += title_words(text)
    return list(dict.fromkeys(words))


def add_named_variant(self, archive, titles, sources, seen, cap):
    """``_CorpusBuilder._add_named`` as built, and in anfang, verlinkt and mehrdeutig the check before a part joins."""
    variant = STATE["variant"]
    if variant not in ("anfang", "verlinkt", "mehrdeutig"):
        return _add_named_built(self, archive, titles, sources, seen, cap)
    primary = next((s for s in sources if s.is_primary), None)
    # the main article, and N's overview where it is another article ("Elektrischer Strom" beside the main article
    # "Strom (Physik)", whose few links miss the parts): a part may link with either
    anchors = [LinkedTo(archive, primary)] if primary is not None else []
    overview = CTX.get("overview_title")
    words = request_words()
    for title in titles:
        if len(sources) >= cap:
            return None
        part = self._read_source(archive, title, seen)
        if part is None:
            continue
        if title != overview and (variant != "mehrdeutig" or title in CTX.get("ambiguous", {})):
            lead = next((p.text for s in part.sections for p in s.paragraphs if p.text.strip()), "")
            by_link = any(linked(part) for linked in anchors)
            by_lead = any(TopicMention.of(word).found_in(lead) for word in words)
            taken = {"anfang": by_lead, "verlinkt": by_link, "mehrdeutig": by_link or by_lead}[variant]
            CTX["checks"].append({"titel": part.title, "verlinkt": by_link, "anfang": by_lead, "genommen": taken})
            if not taken:
                continue
        part.origin = NAMED_ORIGIN
        sources.append(part)
        if title == overview:
            anchors.append(LinkedTo(archive, part))
    return None


_look_up_built = articles_module._look_up
_overview_built = articles_module._overview
_read_object_built = articles_module.read_object
_add_named_built = corpus_module._CorpusBuilder._add_named
if MODE in ("titel", "varianten"):
    articles_module._look_up = look_up_variant
    articles_module._overview = overview_kept
    articles_module.read_object = answer_kept
    corpus_module._CorpusBuilder._add_named = add_named_variant

# --- what N heard and what the archive made of it -------------------------------------------------------------------
_ask = main_article_module.ask_topic_articles


def ask_recorded(job, archive, topic, subjects=(), context=""):
    CTX.clear()
    CTX.update(topic=topic, subjects=list(subjects), answer=None, overview_title=None, klammer=[], ambiguous={})
    CTX["checks"] = []
    report = _ask(job, archive, topic, subjects, context)
    CURRENT["n"].append({"thema": topic, "faecher": list(subjects), "kontext": context, "report": report})
    return report


main_article_module.ask_topic_articles = ask_recorded

if "install" in globals():  # piped in after mc_openai_direkt.py: every call goes to OpenAI directly
    install()  # noqa: F821

from app.cli_common import cli_service  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402

service = cli_service(None)  # the archives of ZIM_PATHS in the container
if service.llm is None:
    raise SystemExit("LLM_ENABLED did not reach the settings")
captured: list = []
_prepare = service.prepare


def keep_prepared(*args, **kwargs):
    prepared = _prepare(*args, **kwargs)
    captured.append(prepared)
    return prepared


service.prepare = keep_prepared


def n_record(entry: dict) -> dict:
    report = entry["report"]
    return {
        "thema": entry["thema"],
        "faecher": entry["faecher"],
        "kontext": entry["kontext"],
        "uebersicht": report.overview,
        "genannt": list(report.named),
        "uebersicht_titel": report.overview_title,
        "gefunden": list(report.found),
        "ersetzt_haupt": report.main,
        "deckt_ab": report.covers,
        "teile": report.parts,
        "rueckfall": report.fallback,
    }


def run_once(entry: dict, leads: dict) -> tuple[dict, list]:
    """One request through generate; the run's row and its printed texts."""
    CURRENT["calls"], CURRENT["n"] = [], []
    captured.clear()
    before = Counter(COUNT)
    started = time.perf_counter()
    compendium = service.generate(GenerateRequest(topic=entry["anfrage"], parts=["world"], preset=PRESET))
    seconds = time.perf_counter() - started
    prepared = captured[-1]
    chunks = {chunk.chunk_id: chunk for chunk in prepared.chunks}
    sources = {source.source_id: source for source in prepared.sources}
    kept = Counter(chunk.source_id for chunk in prepared.chunks)
    for source in prepared.sources:
        leads.setdefault(f"{source.project}:{source.title}", source.lead_text[:LEAD_CHARS])
    content = {slot.id for slot in prepared.template.content_slots()}
    printed, texts = [], []
    for section in compendium.sections:
        if section.slot_id not in content:
            continue
        for citation in section.citations:
            chunk, source = chunks.get(citation.chunk_id), sources.get(citation.source_id)
            row = {
                "baustein": section.title,
                "quelle": citation.source_title,
                "projekt": source.project if source else "?",
                "herkunft": source.origin if source else "?",
                "position": chunk.position if chunk else None,
            }
            printed.append(row)
            texts.append({**row, "text": chunk.text if chunk else citation.snippet})
    resolution = compendium.resolution
    row = {
        "nr": entry["nr"],
        "anfrage": entry["anfrage"],
        "art": entry["art"],
        "erwartet": entry["erwartet"],
        "hauptartikel": resolution.title,
        "methode": resolution.method,
        "sicher": resolution.confident,
        "n": [n_record(n) for n in CURRENT["n"]],
        "korpus": [
            {"titel": s.title, "projekt": s.project, "herkunft": s.origin, "absaetze": kept.get(s.source_id, 0)}
            for s in prepared.sources
        ],
        "gedruckt": printed,
        "bausteine_gefuellt": sum(1 for s in compendium.sections if s.slot_id in content and s.text.strip()),
        "tokens": compendium.audit.llm_tokens,
        "llm_live": COUNT["live"] - before["live"],
        "llm_wiederholt": COUNT["wiederholt"] - before["wiederholt"],
        "sekunden": round(seconds, 2),
        "marken": marks(),
    }
    return row, texts


def marks() -> dict:
    """What the variant did to the titles N named: qualifiers taken, ambiguous names kept, checks before the corpus."""
    return {
        "klammer": list(CTX.get("klammer", [])),
        "mehrdeutig": dict(CTX.get("ambiguous", {})),
        "pruefungen": list(CTX.get("checks", [])),
    }


def load(path: Path, empty):
    return json.loads(path.read_text("utf-8")) if path.exists() else empty


def ask_all() -> None:
    """fragen: every request of this part ``RUNS`` times, round by round; resumes where an output stops."""
    answers_path = OUT.with_name(OUT.stem + "_antworten.json")
    texts_path = OUT.with_name(OUT.stem + "_texte.json")
    data = load(OUT, {"zeilen": [], "einleitungen": {}})
    answers, pool = load(answers_path, {}), load(texts_path, {})
    done = {(row["nr"], row["lauf"]) for row in data["zeilen"] if "fehler" not in row}
    data["zeilen"] = [row for row in data["zeilen"] if "fehler" not in row]
    mine = [entry for entry in requests() if (entry["nr"] - 1) % PARTS == PART - 1]
    if os.environ.get("NUR"):
        mine = [entry for entry in mine if entry["anfrage"] in os.environ["NUR"].split("|")]
    print("app:", app.__file__, "| Teil", f"{PART}/{PARTS}", "| Anfragen:", len(mine), "| Läufe:", RUNS, flush=True)
    for run in range(1, RUNS + 1):
        for entry in mine:
            if (entry["nr"], run) in done:
                continue
            key = f"{entry['nr']}:{run}"
            CURRENT["key"], CURRENT["replay"] = key, []
            row, texts = None, []
            for attempt in range(3):
                try:
                    row, texts = run_once(entry, data["einleitungen"])
                    break
                except Exception as exc:  # a failed request is recorded, not hidden
                    print(
                        f"  Fehler {entry['anfrage']} Lauf {run} (Versuch {attempt + 1}): {type(exc).__name__}: {exc}"
                    )
                    row = {"nr": entry["nr"], "anfrage": entry["anfrage"], "fehler": f"{type(exc).__name__}: {exc}"}
                    time.sleep(5)
            row["lauf"] = run
            data["zeilen"].append(row)
            answers[key] = CURRENT["calls"]
            pool[key] = texts
            if "fehler" not in row:
                n = row["n"][0] if row["n"] else {}
                print(
                    f"{entry['nr']:>3}.{run} {entry['anfrage'][:34]:<34} -> {str(row['hauptartikel'])[:26]:<26} "
                    f"N {n.get('uebersicht')!s:.24} + {len(n.get('genannt', []))} genannt, {len(n.get('gefunden', []))}"
                    f" gefunden | gedruckt {len(row['gedruckt'])} | LLM {row['llm_live']} | {row['sekunden']:.1f}s",
                    flush=True,
                )
            OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
            answers_path.write_text(json.dumps(answers, ensure_ascii=False), "utf-8")
            texts_path.write_text(json.dumps(pool, ensure_ascii=False), "utf-8")
    print("LLM live", COUNT["live"], "wiederholt", COUNT["wiederholt"], flush=True)


def prepared_only(entry: dict):
    """The start of generate up to the corpus, as M72 ran it: admission, budget, the LLM jobs, ``prepare``."""
    CURRENT["calls"], CURRENT["n"] = [], []
    captured.clear()
    deadline = Deadline(service.settings.request_time_limit_s)
    request = GenerateRequest(topic=entry["anfrage"], parts=["world"], preset=PRESET)
    request, profile = service._admit(request, deadline)  # noqa: SLF001 - the first step of generate
    budget = service.open_budget(profile)
    _, _, choice = service.article_choice_job(request.article_choice, deadline, budget)
    budget = choice.budget if choice is not None else budget
    wording = service.wording_job(request.generation, choice, deadline, budget)
    return service.prepare(request, deadline, choice, wording=wording)


def corpus_of(corpus: list[dict]) -> list[tuple]:
    return [(source["projekt"], source["titel"], source["herkunft"]) for source in corpus]


def trace(archive, label: str) -> dict:
    """How the archive answers a named title, for the causes: entry, redirect, article, disambiguation, spelling
    variant, a page of other meanings, singular forms and, for a name with signs of several meanings, the titles of
    the same name with a qualifier."""
    entry = archive._entry(label)  # noqa: SLF001 - the redirect flag, for the record only
    read = archive.read(label)
    article = archive.read_article(label)
    info = {
        "eintrag": str(entry.title) if entry is not None else None,
        "weiterleitung": str(entry.get_redirect_entry().title) if entry is not None and entry.is_redirect else None,
        "abschnitt": bool(article is not None and read is not None and article.title != read.title),
        "artikel": article.title if article is not None else None,
        "begriffsklaerung": bool(article is not None and archive.parse(article).is_disambiguation),
        "schreibvariante": None,
        "ergebnis": _look_up_built(archive, label),
        "bkl_seite": archive.has(label + DISAMBIGUATION),
        "namensartikel": False,
        "grundformen": [],
        "geschwister": [],
    }
    if article is None or info["begriffsklaerung"]:
        for spelling in articles_module._spellings(label):  # noqa: SLF001 - as _look_up tries them
            found = archive.read_article(spelling)
            if found is not None:
                disambiguation = archive.parse(found).is_disambiguation
                info["schreibvariante"] = {"form": spelling, "artikel": found.title, "begriffsklaerung": disambiguation}
                break
    if info["ergebnis"]:
        info["namensartikel"] = bool(NAME_ARTICLE.search(first_paragraph(archive, info["ergebnis"])[:200]))
    for form in singular_forms(label):
        found = archive.read_article(form)
        page = archive.has(form + DISAMBIGUATION)
        if found is not None or page:
            disambiguation = bool(found is not None and archive.parse(found).is_disambiguation)
            info["grundformen"].append(
                {
                    "form": form,
                    "artikel": found.title if found else None,
                    "begriffsklaerung": disambiguation,
                    "bkl_seite": page,
                }
            )
    signs = info["bkl_seite"] or info["begriffsklaerung"] or info["namensartikel"] or not info["ergebnis"]
    if signs or any(form["begriffsklaerung"] or form["bkl_seite"] for form in info["grundformen"]):
        bare = articles_module.QUALIFIER.sub("", label).strip()
        for base in dict.fromkeys([bare, *singular_forms(bare)]):
            for title in archive.suggest(f"{base} (", 40):
                if title.startswith(base + " (") and title.endswith(")") and title not in info["geschwister"]:
                    info["geschwister"].append(title)
    return info


def beginning(archive, title: str) -> dict:
    """The start of an article for the graders: its first paragraph, the second too when the first is short."""
    article = archive.read_article(title)
    if article is None:
        return {"text": "", "fehlt": True}
    parsed = archive.parse(article)
    paragraphs = [p.text.strip() for s in parsed.sections for p in s.paragraphs if p.text.strip()]
    text = paragraphs[0] if paragraphs else ""
    if len(text) < 200 and len(paragraphs) > 1:
        text = f"{text} {paragraphs[1]}"
    return {"text": text[:LEAD_CHARS], "begriffsklaerung": parsed.is_disambiguation}


def vary_one(entry: dict, asked: dict, variant: str, answers: list, heute: dict | None, leads: dict):
    """One run under one variant; the printed paragraphs are those of heute when the corpus is the same."""
    STATE["variant"] = variant
    CTX.clear()
    CURRENT["replay"] = copy.deepcopy(answers)
    if variant == "heute":
        row, texts = run_once(entry, leads)
        same = row["gedruckt"] == asked["gedruckt"] and corpus_of(row["korpus"]) == corpus_of(asked["korpus"])
        row["wie_fragen"] = same
        return row, texts
    before = Counter(COUNT)
    prepared = prepared_only(entry)
    corpus = [(source.project, source.title, source.origin) for source in prepared.sources]
    if heute is not None and corpus == corpus_of(heute["korpus"]):
        row = {
            "nr": entry["nr"],
            "anfrage": entry["anfrage"],
            "art": entry["art"],
            "hauptartikel": prepared.resolution.title,
            "n": [n_record(n) for n in CURRENT["n"]],
            "korpus": heute["korpus"],
            "gedruckt": heute["gedruckt"],
            "wie_heute": True,
            "marken": marks(),
            "llm_live": COUNT["live"] - before["live"],
            "llm_wiederholt": COUNT["wiederholt"] - before["wiederholt"],
        }
        return row, None
    CURRENT["replay"] = copy.deepcopy(answers)
    row, texts = run_once(entry, leads)
    row["wie_heute"] = False
    return row, texts


def vary_all() -> None:
    """varianten: every run of this part again per variant, under the answers recorded for it (step fragen)."""
    rows, answers = recorded(ARGS[1:])
    entries = {entry["nr"]: entry for entry in requests()}
    mine = [row for row in rows if (row["nr"] - 1) % PARTS == PART - 1]
    if os.environ.get("NUR"):
        mine = [row for row in mine if row["anfrage"] in os.environ["NUR"].split("|")]
    texts_path = OUT.with_name(OUT.stem + "_texte.json")
    data = load(OUT, {"zeilen": [], "einleitungen": {}})
    pool = load(texts_path, {})
    done = {(row["nr"], row["lauf"], row["variante"]): row for row in data["zeilen"] if "fehler" not in row}
    data["zeilen"] = list(done.values())
    print(
        "app:", app.__file__, "| Teil", f"{PART}/{PARTS}", "| Läufe:", len(mine), "| Varianten:", VARIANTS, flush=True
    )
    for asked in mine:
        entry, key = entries[asked["nr"]], f"{asked['nr']}:{asked['lauf']}"
        CURRENT["key"] = key
        line = []
        for variant in VARIANTS:
            if (asked["nr"], asked["lauf"], variant) in done:
                continue
            heute = done.get((asked["nr"], asked["lauf"], "heute"))
            try:
                row, texts = vary_one(entry, asked, variant, answers.get(key, []), heute, data["einleitungen"])
            except Exception as exc:  # a failed run is recorded, not hidden
                row = {"nr": entry["nr"], "anfrage": entry["anfrage"], "fehler": f"{type(exc).__name__}: {exc}"[:300]}
                texts = None
                print(f"  Fehler {entry['anfrage']} Lauf {asked['lauf']} {variant}: {row['fehler']}", flush=True)
            row.update(lauf=asked["lauf"], variante=variant)
            data["zeilen"].append(row)
            if "fehler" not in row:
                done[(asked["nr"], asked["lauf"], variant)] = row
                found = row["n"][0]["gefunden"] if row["n"] else []
                same = row.get("wie_fragen", row.get("wie_heute"))
                line.append(f"{variant} {len(found)}/{'=' if same else '≠'}/live {row['llm_live']}")
            if texts is not None:
                pool[f"{key}:{variant}"] = texts
        print(f"{asked['nr']:>3}.{asked['lauf']} {asked['anfrage'][:30]:<30} " + " | ".join(line), flush=True)
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        texts_path.write_text(json.dumps(pool, ensure_ascii=False), "utf-8")
    print("LLM live", COUNT["live"], "wiederholt", COUNT["wiederholt"], flush=True)


def recorded(paths: list[str]) -> tuple[list[dict], dict]:
    """The runs of fragen and the record of their answers, from the outputs of all its parts."""
    rows, answers = [], {}
    for name in paths:
        path = Path(name)
        rows += [row for row in json.loads(path.read_text("utf-8"))["zeilen"] if "fehler" not in row]
        answers.update(json.loads(path.with_name(path.stem + "_antworten.json").read_text("utf-8")))
    return sorted(rows, key=lambda r: (r["nr"], r["lauf"])), answers


def titles_all() -> None:
    """titel: per run the titles the archive gives for N's answer in heute, klammer and mehrdeutig - the variants
    that change the titles, the others check them before the corpus - through ``ask_topic_articles`` as the service
    calls it, the answer from the record; then the traces of every named title and the start of every article, for
    the graders before the slower step varianten. heute is compared with the run of fragen (``wie_fragen``)."""
    from app.knowledge.article_choice import ArticleChoiceJob

    rows, answers = recorded(ARGS[1:])
    archive = service.registry.primary_archive
    data = {"zeilen": [], "spuren": {}, "anfaenge": {}}
    for asked in rows:
        if not asked["n"]:
            continue
        heard, key = asked["n"][0], f"{asked['nr']}:{asked['lauf']}"
        for variant in ("heute", "klammer", "mehrdeutig"):
            STATE["variant"] = variant
            CURRENT["key"], CURRENT["replay"], CURRENT["n"] = key, copy.deepcopy(answers.get(key, [])), []
            job = ArticleChoiceJob(service.llm.client, service.llm.open_budget(), None)
            main_article_module.ask_topic_articles(job, archive, heard["thema"], heard["faecher"], heard["kontext"])
            n = n_record(CURRENT["n"][-1])
            row = {
                "nr": asked["nr"],
                "lauf": asked["lauf"],
                "anfrage": asked["anfrage"],
                "art": asked["art"],
                "variante": variant,
                "hauptartikel": asked["hauptartikel"],
                "n": [n],
                "marken": marks(),
            }
            if variant == "heute":
                row["wie_fragen"] = n["gefunden"] == heard["gefunden"]
            data["zeilen"].append(row)
    labels = {label for row in rows for n in row["n"] for label in [n["uebersicht"], *n["genannt"]] if label}
    for label in sorted(labels):
        data["spuren"][label] = trace(archive, label)
    titles = {row["hauptartikel"] for row in rows if row.get("hauptartikel")}
    titles |= {title for row in data["zeilen"] for title in row["n"][0]["gefunden"]}
    for title in sorted(titles):
        data["anfaenge"][title] = beginning(archive, title)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    same = sum(1 for row in data["zeilen"] if row.get("wie_fragen"))
    heute = sum(1 for row in data["zeilen"] if row["variante"] == "heute")
    print(
        f"Läufe {len(rows)} | heute wie fragen {same}/{heute} | LLM live {COUNT['live']} wiederholt "
        f"{COUNT['wiederholt']} | Spuren {len(data['spuren'])} | Anfänge {len(data['anfaenge'])}",
        flush=True,
    )


if MODE == "fragen":
    ask_all()
elif MODE == "titel":
    titles_all()
elif MODE == "varianten":
    vary_all()
else:
    raise SystemExit(f"unbekannter Schritt {MODE!r}")
