# syntax=docker/dockerfile:1.7
# Ein einziges Image (Entscheidung vom 2026-09-20; sie ersetzt das geplante zweite Profil "ml"): Python 3.13,
# libzim, numpy, scikit-learn, das statische Embedding-Modell fuer den hybriden Matcher (D20) und spaCy fuer die
# Entitaeten und die QA-Regeln. torch, transformers und die beiden QA-Modelle (U5b) sind mit D57 entfallen.

# Basis ist das offizielle Python-Image, per Digest gepinnt: ein Build morgen ergibt dasselbe Image, und Debian-
# und CPython-Sicherheitskorrekturen kommen als neuer Digest, den Dependabot (.github/dependabot.yml) woechentlich
# vorschlaegt. uv nur im Builder, in derselben Version wie CI und Lockfile.
FROM ghcr.io/astral-sh/uv:0.7.13@sha256:6c1e19020ec221986a210027040044a5df8de762eb36d5240e382bc41d7a9043 AS uv

FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 AS builder
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
# Abhaengigkeiten zuerst (eigene Layer, aendern sich selten)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev --extra embeddings --extra entities
# Embedding-Modell zur Bauzeit laden, damit die Laufzeit den Hugging-Face-Hub nie anspricht. Die Revision ist
# festgelegt, damit jeder Build dasselbe Modell enthaelt (neue Revision: Eval neu messen, dann hier eintragen).
# MODEL2VEC_ID="" baut ohne Modell; der Matcher laeuft dann mit BM25 und Char-TF-IDF.
ARG MODEL2VEC_ID=JanSchachtschabel/m2v-gte-256-edu
ARG MODEL2VEC_REVISION=4e332ba73cd6e3551541163139e3cfa189398a41
RUN mkdir -p /models/m2v && if [ -n "$MODEL2VEC_ID" ]; then \
      /app/.venv/bin/python -c "import sys; from huggingface_hub import snapshot_download; from model2vec import StaticModel; StaticModel.from_pretrained(snapshot_download(sys.argv[1], revision=sys.argv[2])).save_pretrained('/models/m2v')" "$MODEL2VEC_ID" "$MODEL2VEC_REVISION"; \
    fi

# spaCy-Modell fuer die Entitaetserkennung (POST /api/v2/entities). Die Fassung ist festgelegt, damit jeder
# Build dasselbe Modell enthaelt; das Rad liegt bei den spacy-models-Releases, nicht auf PyPI. SPACY_MODEL=""
# baut ohne Modell - der Endpunkt antwortet dann nur mit den Begriffen, die einen Artikel in den Archiven haben.
# Der Projekt-Sync danach laeuft mit --inexact, sonst raeumt er das Modellrad wieder weg.
ARG SPACY_MODEL=de_core_news_md
ARG SPACY_MODEL_VERSION=3.8.0
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -n "$SPACY_MODEL" ]; then \
      uv pip install --python /app/.venv/bin/python --no-deps \
        "https://github.com/explosion/spacy-models/releases/download/${SPACY_MODEL}-${SPACY_MODEL_VERSION}/${SPACY_MODEL}-${SPACY_MODEL_VERSION}-py3-none-any.whl" \
      && /app/.venv/bin/python -c "import spacy, sys; spacy.load(sys.argv[1])" "$SPACY_MODEL"; \
    fi

COPY pyproject.toml uv.lock README.md ./
COPY app ./app
# uv caches the wheel it builds for this project under its version, and that version does not change
# between commits: measured on 2026-09-21 a build installed the app as it stood three commits earlier
# while every layer reported DONE. --reinstall-package rebuilds it, and the comparison afterwards proves
# the venv carries what was copied - a silently old image is worse than a failed build.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --inexact --no-dev --no-editable --reinstall-package compendious-text-fastapi \
      --extra embeddings --extra entities \
    && ! find app -name __pycache__ -print -quit | grep -q . \
    && installed=$(/app/.venv/bin/python -c "import app, pathlib; print(pathlib.Path(app.__file__).parent)") \
    && diff -r -x __pycache__ app "$installed"

FROM python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 AS runtime
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    ZIM_DIR=/data/zim \
    STATE_DIR=/data/state \
    CONFIG_DIR=/app/config \
    MODEL2VEC_PATH=/models/m2v \
    SPACY_MODEL=de_core_news_md \
    HF_HUB_OFFLINE=1 \
    WEB_CONCURRENCY=2
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/zim /data/state \
    && chown -R app:app /data
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /models /models
COPY --chown=app:app config ./config
USER app
VOLUME ["/data/zim", "/data/state"]
EXPOSE 8000
# Anlaufzeit gemessen am 2026-09-23 (Docker Desktop, zwei Worker): 144 s bis "Application startup complete",
# davon rund 100 s Modelle laden. 600 s lassen einem langsameren Host das Vierfache. Kosten hat der Wert nicht:
# Gelingt eine Probe frueher, gilt der Container sofort als healthy; die Frist verschiebt nur das Urteil
# unhealthy fuer einen Container, der nie hochkommt. Mit 30 s stand er nach jedem Start minutenlang auf unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"]
# API-Prozess (app/serve.py): legt PROMETHEUS_MULTIPROC_DIR an (Standard /tmp/prometheus), loescht darin nur die
# Metrik-Dateien eines frueheren Laufs und uebergibt per exec an uvicorn, das so die Signale bekommt (sauberes
# Herunterfahren). Die Worker-Zahl kommt aus WEB_CONCURRENCY (uvicorn liest die Variable selbst); /metrics
# summiert die Werte aller Worker. Die Sidecars laden die Metriken nicht.
# Der Updater nutzt dasselbe Image mit: compendium zim sync --loop
CMD ["python", "-m", "app.serve"]
