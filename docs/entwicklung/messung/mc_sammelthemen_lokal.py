"""M40: can a small model that runs on the service's own CPU answer the question N of M37 for llm-free?

Jan, 2026-09-27: M38 asked small models of the b-api, but the question was whether a model small enough to run
locally - LFM2, LFM2.5, Qwen3 0.6B - can improve llm-free for set-like topics, in at most 2 to 3 s. Extracting models
(GLiNER, Flair, GBERT) only find names in a text; Jan chose to test the generative ones. Each model runs in
llama-server (llama.cpp b11206, CPU build, GGUF) in the development container with THREADS threads, one model at a
time; the question N goes to it word for word, with a JSON schema the answer has to follow (the model cannot answer
outside it) and without Qwen3's thinking. The named titles are looked up as in M37, and the articles found run through
part 1 of the service as L8 and Q30 did in M38 (the first one found is the main article, every paragraph kept).

Ways: LF7 LFM2-700M (Q4_K_M), LF12 LFM2.5-1.2B-Instruct (Q4_K_M), Q06 Qwen3-0.6B (Q8_0). R, B and N stay the runs of
M37 and M38 (their grades apply: MODEL2VEC_PATH empty, as there). The seconds of a question are measured by the
client, the server warmed up with one question first; the part 1 that follows does not overlap with it.

Every article a way printed that M37 or M38 did not grade is graded blind as there (eval/sammelthemen/); leads go to
the sheet only.

Usage (in the container, with this file, alter_linker.py, mc_sammelthemen.py and eval/artikelwahl/korpus_labels.yaml
in one directory on PYTHONPATH, the models under /opt/lokal/models and llama.cpp under /opt/lokal/llama-b11206):
python mc_sammelthemen_lokal.py <dir> <out.json> <sheet.json> <threads> [--normal]
"""

from __future__ import annotations

import ast
import json
import os
import signal
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

os.environ["MODEL2VEC_PATH"] = ""  # the matching of M37, so its grades apply
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import httpx  # noqa: E402
import yaml  # noqa: E402
from alter_linker import variations  # noqa: E402

from app.cli_common import cli_service  # noqa: E402
from app.domain.models import Compendium  # noqa: E402
from app.domain.requests import GenerateRequest  # noqa: E402
from app.knowledge.article_choice import read_object  # noqa: E402

MODELS = {
    "LF7": "LFM2-700M-Q4_K_M.gguf",
    "LF12": "LFM2.5-1.2B-Instruct-Q4_K_M.gguf",
    "Q06": "Qwen3-0.6B-Q8_0.gguf",
}
MODEL_DIR = "/opt/lokal/models"
LLAMA = "/opt/lokal/llama-b11206"
URL = "http://127.0.0.1:8081"
ANSWER_TOKENS = 400
SCHEMA = {
    "type": "object",
    "properties": {
        "uebersicht": {"type": "string"},
        "artikel": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
    },
    "required": ["uebersicht", "artikel"],
}

directory, out_path, sheet_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
THREADS = int(sys.argv[4])
NORMAL = "--normal" in sys.argv
m37 = ast.parse((directory / "mc_sammelthemen.py").read_text(encoding="utf-8"))
WANTED = ("TOPICS", "NEW_SYSTEM", "NEW_QUESTION", "MAX_NAMED")
M37 = {
    n.targets[0].id: ast.literal_eval(n.value)
    for n in m37.body
    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in WANTED
}
TOPICS: list[str] = M37["TOPICS"]
if NORMAL:
    TOPICS = list(yaml.safe_load((directory / "korpus_labels.yaml").read_text(encoding="utf-8"))["labels"])

service = cli_service(None)
wiki = service.registry.primary_archive
assert wiki is not None


def stop_servers() -> None:
    """The container has no pkill: end every llama-server found in /proc, and wait until none answers."""
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                if b"llama-server" in f.read().split(b"\0")[0]:
                    os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
    for _ in range(40):
        try:
            httpx.get(f"{URL}/health", timeout=1)
        except httpx.HTTPError:
            return
        time.sleep(0.5)
    raise SystemExit("an old llama-server still answers")


def start_server(model: str) -> subprocess.Popen[bytes]:
    stop_servers()
    server = subprocess.Popen(
        [f"{LLAMA}/llama-server", "-m", f"{MODEL_DIR}/{model}", "-t", str(THREADS), "-c", "4096", "-np", "1",
         "--host", "127.0.0.1", "--port", "8081", "--jinja"],
        env={"LD_LIBRARY_PATH": f"/opt/lokal/lib:{LLAMA}"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    for _ in range(120):
        try:
            if httpx.get(f"{URL}/health", timeout=2).status_code == 200:
                loaded = httpx.get(f"{URL}/props", timeout=5).json().get("model_path", "")
                if not loaded.endswith(model):
                    server.kill()
                    raise SystemExit(f"the server serves {loaded}, not {model}")
                return server
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    server.kill()
    raise SystemExit(f"llama-server did not come up with {model}")


def looked_up(labels: list[str]) -> list[str]:
    """The articles behind the labels, as M37: directly with redirects, then the old spelling variants."""
    titles: list[str] = []
    for label in labels:
        for candidate in [label, *variations(label)]:
            article = wiki.read_article(candidate)
            if article is not None:
                if not wiki.parse(article).is_disambiguation and article.title not in titles:
                    titles.append(article.title)
                break
    return titles


def entity_corpus(titles: list[str]) -> Callable[..., list[Any]]:
    """build_corpus for the named articles, the first one as main article, every paragraph kept (M23, M37)."""

    def build(resolution: Any, slots: Any, max_articles: int, material: str | None = None) -> list[Any]:
        sources: list[Any] = []
        seen: set[str] = set()
        for title in [resolution.title, *titles]:
            article = wiki.read_article(title)
            if article is None or wiki.parse(article).is_disambiguation or article.title.lower() in seen:
                continue
            seen.add(article.title.lower())
            source = wiki.to_source(article, is_primary=not sources)
            source.origin = "primary" if not sources else "entity"
            sources.append(source)
            if len(sources) == max_articles:
                break
        return sources

    return build


def generate(request: GenerateRequest, corpus: Callable[..., list[Any]]) -> tuple[Compendium, float]:
    original = service.registry.build_corpus
    service.registry.build_corpus = corpus  # type: ignore[method-assign]
    started = time.perf_counter()
    try:
        return service.generate(request), round(time.perf_counter() - started, 2)
    finally:
        service.registry.build_corpus = original  # type: ignore[method-assign]


def summary(result: Compendium, sheet: dict[str, str]) -> dict[str, Any]:
    """What a way printed, per article, as M37 and M38; the leads go to the sheet only."""
    by_id = {source.source_id: source for source in result.sources}
    printed: Counter[str] = Counter()
    for section in result.sections:
        for chunk_id in section.chunk_ids:
            source = by_id[chunk_id.rsplit(":c", 1)[0]]
            printed[source.title] += 1
            sheet.setdefault(source.title, source.lead[:400])
    return {
        "hauptartikel": result.resolution.title,
        "gedruckt": [{"titel": t, "absaetze": n} for t, n in printed.most_common()],
        "bausteine": result.audit.sections_filled,
    }


def ask_local(topic: str) -> dict[str, Any]:
    question = M37["NEW_QUESTION"].format(topic=topic, count=M37["MAX_NAMED"])
    body = {
        "messages": [{"role": "system", "content": M37["NEW_SYSTEM"]}, {"role": "user", "content": question}],
        "max_tokens": ANSWER_TOKENS,
        "temperature": 0,
        "response_format": {"type": "json_schema", "json_schema": {"schema": SCHEMA}},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.perf_counter()
    answer = httpx.post(f"{URL}/v1/chat/completions", json=body, timeout=120).json()
    seconds = round(time.perf_counter() - started, 2)
    data = read_object(answer["choices"][0]["message"]["content"]) or {}
    overview = str(data.get("uebersicht") or "").strip()
    named = [str(t).strip() for t in data.get("artikel") or [] if str(t).strip()][: M37["MAX_NAMED"]]
    return {
        "uebersicht": overview,
        "genannt": named,
        "gefunden": looked_up([overview, *named] if overview else named),
        "tokens_aus": answer.get("usage", {}).get("completion_tokens", 0),
        "sekunden_frage": seconds,
    }


rows: dict[str, dict[str, Any]] = {topic: {} for topic in TOPICS}
sheets: dict[str, dict[str, str]] = {topic: {} for topic in TOPICS}
for way, model in MODELS.items():
    server = start_server(model)
    try:
        ask_local("Wärme")  # warm-up, not counted
        for topic in TOPICS:
            asked = ask_local(topic)
            if asked["gefunden"]:
                request = GenerateRequest(topic=asked["gefunden"][0], parts=["world"], preset="llm-free")  # type: ignore[arg-type]
                result, seconds = generate(request, entity_corpus(asked["gefunden"]))
                rows[topic][way] = {"sekunden": seconds, **summary(result, sheets[topic]), **asked}
            else:
                rows[topic][way] = {"status": "keine Artikel", **asked}
            print(f"{way:5s} {topic:36s} {asked['sekunden_frage']:5.2f} s  "
                  f"{rows[topic][way].get('hauptartikel', 'keine Artikel')}", flush=True)  # fmt: skip
    finally:
        server.terminate()
        server.wait(timeout=30)

out = {"threads": THREADS, "modelle": MODELS, "themen": [{"thema": t, "wege": rows[t]} for t in TOPICS]}
out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
sheet_path.write_text(json.dumps(sheets, ensure_ascii=False, indent=1), encoding="utf-8")
