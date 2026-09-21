# syntax=docker/dockerfile:1.7
# Ein einziges Image (Entscheidung vom 2026-09-20; sie ersetzt das geplante zweite Profil "ml"): Python 3.13,
# libzim, numpy, scikit-learn, das statische Embedding-Modell fuer den hybriden Matcher (D20), spaCy fuer die
# Entitaeten und torch/transformers samt den beiden QA-Modellen (U5b). torch kommt als CPU-Rad ueber den
# Index in pyproject.toml - der PyPI-Standard ist der CUDA-Bau und zoege Treiber nach, die hier nie laufen.

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
    uv sync --locked --no-install-project --no-dev --extra embeddings --extra entities --extra qa-models
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

# Die beiden Modelle der QA-Stufe `models` (docs/umbau.md U5b), beide MIT und deutsch: ein Fragengenerator
# (T5, antwortbewusst - die Antwort wird im Satz mit <hl> markiert) und ein extraktives Antwortmodell, das
# die Stelle im Text markiert, statt zu formulieren. Revisionen festgelegt; das Skript holt nur die Dateien,
# die die Lader brauchen, und laedt beide einmal, damit ein kaputter Download den Bau scheitern laesst.
ARG QG_MODEL_ID=dehio/german-qg-t5-quad
ARG QG_MODEL_REVISION=e5eeeeaef49576b5679469f2d186971e4f647ea7
ARG QA_MODEL_ID=deepset/gelectra-base-germanquad
ARG QA_MODEL_REVISION=b2c4057739c802027af43f59a44bcd1beb9666d1
COPY scripts/fetch_qa_models.py ./scripts/fetch_qa_models.py
RUN /app/.venv/bin/python scripts/fetch_qa_models.py \
      --qg-id "$QG_MODEL_ID" --qg-revision "$QG_MODEL_REVISION" \
      --qa-id "$QA_MODEL_ID" --qa-revision "$QA_MODEL_REVISION"

COPY pyproject.toml uv.lock README.md ./
COPY app ./app
# uv caches the wheel it builds for this project under its version, and that version does not change
# between commits: measured on 2026-09-21 a build installed the app as it stood three commits earlier
# while every layer reported DONE. --reinstall-package rebuilds it, and the comparison afterwards proves
# the venv carries what was copied - a silently old image is worse than a failed build.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --inexact --no-dev --no-editable --reinstall-package compendious-text-fastapi \
      --extra embeddings --extra entities --extra qa-models \
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
    QG_MODEL_PATH=/models/qg \
    QA_MODEL_PATH=/models/qa \
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
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"]
# API-Prozess (app/serve.py): legt PROMETHEUS_MULTIPROC_DIR an (Standard /tmp/prometheus), loescht darin nur die
# Metrik-Dateien eines frueheren Laufs und uebergibt per exec an uvicorn, das so die Signale bekommt (sauberes
# Herunterfahren). Die Worker-Zahl kommt aus WEB_CONCURRENCY (uvicorn liest die Variable selbst); /metrics
# summiert die Werte aller Worker. Die Sidecars laden die Metriken nicht.
# Der Updater nutzt dasselbe Image mit: compendium zim sync --loop
CMD ["python", "-m", "app.serve"]
