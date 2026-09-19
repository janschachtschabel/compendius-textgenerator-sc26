# syntax=docker/dockerfile:1.7
# Image-Profil "base" (PLAN.md 10): Python 3.13, libzim, numpy, scikit-learn, Extra "embeddings" mit
# dem statischen Embedding-Modell fuer den hybriden Matcher (Entscheidung D20). Das Profil "ml"
# (torch, Cross-Encoder) bleibt Phase 7 vorbehalten, falls die Evaluation den Mehrwert zeigt.

# Basis-Image mit derselben uv-Version wie CI und Lockfile, damit ein Build morgen dasselbe Image ergibt
FROM ghcr.io/astral-sh/uv:0.7.13-python3.13-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
# Abhaengigkeiten zuerst (eigene Layer, aendern sich selten)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev --extra embeddings
COPY pyproject.toml uv.lock README.md ./
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --extra embeddings
# Embedding-Modell zur Bauzeit laden, damit die Laufzeit den Hugging-Face-Hub nie anspricht. Die Revision ist
# festgelegt, damit jeder Build dasselbe Modell enthaelt (neue Revision: Eval neu messen, dann hier eintragen).
# MODEL2VEC_ID="" baut ohne Modell; der Matcher laeuft dann mit BM25 und Char-TF-IDF.
ARG MODEL2VEC_ID=JanSchachtschabel/m2v-gte-256-edu
ARG MODEL2VEC_REVISION=4e332ba73cd6e3551541163139e3cfa189398a41
RUN mkdir -p /models/m2v && if [ -n "$MODEL2VEC_ID" ]; then \
      /app/.venv/bin/python -c "import sys; from huggingface_hub import snapshot_download; from model2vec import StaticModel; StaticModel.from_pretrained(snapshot_download(sys.argv[1], revision=sys.argv[2])).save_pretrained('/models/m2v')" "$MODEL2VEC_ID" "$MODEL2VEC_REVISION"; \
    fi

FROM ghcr.io/astral-sh/uv:0.7.13-python3.13-bookworm-slim AS runtime
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    ZIM_DIR=/data/zim \
    STATE_DIR=/data/state \
    CONFIG_DIR=/app/config \
    MODEL2VEC_PATH=/models/m2v \
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
