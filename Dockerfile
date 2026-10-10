# Ein einziges Image (Entscheidung vom 2026-09-20; sie ersetzt das geplante zweite Profil "ml"): Python 3.13,
# libzim, numpy, scikit-learn, das statische Embedding-Modell fuer den hybriden Matcher (D20) und spaCy fuer die
# Entitaeten und die QA-Regeln. torch, transformers und die beiden QA-Modelle (U5b) sind mit D57 entfallen.

# Die Modelle, die der Bau einbackt; ein leerer Wert baut ohne (Einzelheiten im Builder). Die Vorgaben stehen vor dem
# ersten FROM, weil ein ARG mit seiner Stage endet: Builder und Laufzeit deklarieren sie ohne Wert neu und sehen so
# denselben, und die Laufzeit nennt MODEL2VEC_PATH und SPACY_MODEL danach (Audit 2026-09-29, O9).
ARG MODEL2VEC_ID=JanSchachtschabel/m2v-gte-256-edu
ARG SPACY_MODEL=de_core_news_md

# Basis ist das offizielle Python-Image, per Digest gepinnt: ein Build morgen ergibt dasselbe Image, und Debian-
# und CPython-Sicherheitskorrekturen kommen als neuer Digest, den Dependabot (.github/dependabot.yml) woechentlich
# vorschlaegt. uv nur im Builder, in derselben Version wie CI und Lockfile. Keine syntax-Zeile: Sie holte bei jedem
# Bau das Frontend docker/dockerfile:1.7 ueber ein wanderndes Tag, und das Dockerfile braucht nichts, was das in
# BuildKit eingebaute Frontend nicht kann (RUN --mount=type=cache; Audit 2026-09-29, O4).
FROM ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 AS uv

FROM python:3.13-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641 AS builder
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
# Abhaengigkeiten zuerst (eigene Layer, aendern sich selten). Die Gruppe build bringt hatchling aus dem Lockfile, mit
# Pruefsumme: Das Projekt baut ohne Isolation daraus, statt es beim Bau ungeprueft von PyPI zu holen (pyproject.toml;
# Audit 2026-09-28, AB-05).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev --group build --extra embeddings --extra entities
# Embedding-Modell zur Bauzeit laden, damit die Laufzeit den Hugging-Face-Hub nie anspricht. Die Revision ist
# festgelegt, damit jeder Build dasselbe Modell enthaelt (neue Revision: Eval neu messen, dann hier eintragen).
# MODEL2VEC_ID="" baut ohne Modell; der Matcher laeuft dann mit BM25 und Char-TF-IDF, und MODEL2VEC_PATH bleibt leer.
ARG MODEL2VEC_ID
ARG MODEL2VEC_REVISION=4e332ba73cd6e3551541163139e3cfa189398a41
RUN mkdir -p /models/m2v && if [ -n "$MODEL2VEC_ID" ]; then \
      /app/.venv/bin/python -c "import sys; from huggingface_hub import snapshot_download; from model2vec import StaticModel; StaticModel.from_pretrained(snapshot_download(sys.argv[1], revision=sys.argv[2])).save_pretrained('/models/m2v')" "$MODEL2VEC_ID" "$MODEL2VEC_REVISION"; \
    fi
# save_pretrained schreibt die Gewichte mit 0600; die Laufzeitkopie gehoert root (SE-12), der Dienst konnte sie nicht
# lesen, und der Matcher lief ohne Embeddings (seit f167a9f, gefunden 2026-09-28). Ein eigener Schritt, damit der
# Download oben im Cache bleibt; die Laufzeit kopiert nur den fertigen Stand.
RUN chmod -R a+rX /models

# spaCy-Modell fuer die Entitaetserkennung (POST /api/v2/entities). Die Fassung ist festgelegt, damit jeder
# Build dasselbe Modell enthaelt; das Rad liegt bei den spacy-models-Releases, nicht auf PyPI. SPACY_MODEL=""
# baut ohne Modell - der Endpunkt antwortet dann nur mit den Begriffen, die einen Artikel in den Archiven haben.
# Der Projekt-Sync danach laeuft mit --inexact, sonst raeumt er das Modellrad wieder weg.
# Das Rad kommt nicht aus dem Lockfile; seine Pruefsumme steht in den Release-Notes des Modells, und ein Rad mit
# einer anderen wird nicht installiert (Audit 2026-09-27, SE-13). Eine neue Fassung aendert Version und Pruefsumme.
ARG SPACY_MODEL
ARG SPACY_MODEL_VERSION=3.8.0
ARG SPACY_MODEL_SHA256=b903f59220f1e76dd672acdaa7fa454d6703fe056c5ccd6457820e70874116d0
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -n "$SPACY_MODEL" ]; then \
      wheel="${SPACY_MODEL}-${SPACY_MODEL_VERSION}-py3-none-any.whl" \
      && python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" \
        "https://github.com/explosion/spacy-models/releases/download/${SPACY_MODEL}-${SPACY_MODEL_VERSION}/${wheel}" \
        "/tmp/${wheel}" \
      && echo "${SPACY_MODEL_SHA256}  /tmp/${wheel}" | sha256sum -c - \
      && uv pip install --python /app/.venv/bin/python --no-deps "/tmp/${wheel}" \
      && rm "/tmp/${wheel}" \
      && /app/.venv/bin/python -c "import spacy, sys; spacy.load(sys.argv[1])" "$SPACY_MODEL"; \
    fi

COPY pyproject.toml uv.lock README.md ./
COPY app ./app
# uv caches the wheel it builds for this project under its version, and that version does not change
# between commits: measured on 2026-09-21 a build installed the app as it stood three commits earlier
# while every layer reported DONE. --reinstall-package rebuilds it, and the comparison afterwards proves
# the venv carries what was copied - a silently old image is worse than a failed build.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --inexact --no-dev --group build --no-editable --reinstall-package compendious-text-fastapi \
      --extra embeddings --extra entities \
    && ! find app -name __pycache__ -print -quit | grep -q . \
    && installed=$(/app/.venv/bin/python -c "import app, pathlib; print(pathlib.Path(app.__file__).parent)") \
    && diff -r -x __pycache__ app "$installed"

FROM python:3.13-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641 AS runtime
WORKDIR /app
# Die Modelle, die der Bau eingebacken hat: Ohne Model2Vec-Modell bleibt MODEL2VEC_PATH leer; fest /models/m2v meldete
# jeder Start einen Fehler fuer ein Modell, das dem Image mit Absicht fehlt (Audit 2026-09-29, O9)
ARG MODEL2VEC_ID
ARG SPACY_MODEL
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    ZIM_DIR=/data/zim \
    STATE_DIR=/data/state \
    CONFIG_DIR=/app/config \
    MODEL2VEC_PATH=${MODEL2VEC_ID:+/models/m2v} \
    SPACY_MODEL=${SPACY_MODEL} \
    HF_HUB_OFFLINE=1
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data/zim /data/state \
    && chown -R app:app /data
# Code, Modelle und Konfiguration gehoeren root: der Dienst liest sie, aendern kann er sie nicht (Audit 2026-09-27,
# SE-12). Schreiben darf er nur in /data und, mit read_only in Compose, nach /tmp.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /models /models
COPY config ./config
USER app
VOLUME ["/data/zim", "/data/state"]
EXPOSE 8000
# Anlaufzeit gemessen am 2026-09-28 (Docker Desktop, zwei Worker, gehaertet wie in docker-compose.yml, die
# Beispielarchive): 22 bis 31 s bis /ready; vor D57 (torch und die QA-Modelle) waren es 144 s. Die 600 s stammen aus
# jener Zeit und lassen einem langsamen Host mit grossen Archiven viel Luft. Kosten hat der Wert nicht:
# Gelingt eine Probe frueher, gilt der Container sofort als healthy; die Frist verschiebt nur das Urteil
# unhealthy fuer einen Container, der nie hochkommt. Mit 30 s stand er nach jedem Start minutenlang auf unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"]
# API-Prozess (app/serve.py): legt PROMETHEUS_MULTIPROC_DIR an (Standard /tmp/prometheus), loescht darin nur die
# Metrik-Dateien eines frueheren Laufs und uebergibt per exec an uvicorn, das so die Signale bekommt (sauberes
# Herunterfahren). Die Worker-Zahl kommt aus WEB_CONCURRENCY (uvicorn liest die Variable selbst, app/serve.py gibt
# ihr die Vorgabe 2, auch bei leerem Eintrag); /metrics summiert die Werte aller Worker. Die Sidecars laden die
# Metriken nicht.
# Der Updater nutzt dasselbe Image mit: compendium zim sync --loop
# Der Commit, aus dem das Image entstand (der Job publish in ci.yml setzt ihn): /health und kompendium_build_info
# nennen ihn als revision, denn die Version aendert sich nur mit einem Release (Audit 2026-09-27, BE-03). Ganz am
# Ende, damit ein neuer Commit keine Schicht davor ungueltig macht.
ARG GIT_REVISION=""
ENV GIT_REVISION=$GIT_REVISION
CMD ["python", "-m", "app.serve"]
