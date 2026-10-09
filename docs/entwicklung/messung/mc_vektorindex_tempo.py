"""M87: how fast this machine embeds Wikipedia paragraphs - the service's static model and three contextual ones
(D101).

Reads the paragraph sample of mc_vektorindex_stichprobe.py, embeds a slice per model after one warm-up batch and
prints paragraphs per second, the dimension and the device. Runs in the venv of the test app (torch,
sentence-transformers, model2vec), not in the project's.

Usage: python mc_vektorindex_tempo.py <sample.json>
"""

from __future__ import annotations

import json
import os
import sys
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")

import torch  # noqa: E402
from model2vec import StaticModel  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
paragraphs = json.load(open(sys.argv[1], encoding="utf-8"))["absaetze"]
device = "cuda" if torch.cuda.is_available() else "cpu"
print(
    f"device {device}, torch threads {torch.get_num_threads()}, {len(paragraphs)} paragraphs, "
    f"mean {sum(map(len, paragraphs)) / len(paragraphs):.0f} characters",
    flush=True,
)


def timed(name: str, encode, texts: list[str], dims: int) -> None:
    encode(texts[:32])  # warm-up
    started = time.perf_counter()
    encode(texts)
    seconds = time.perf_counter() - started
    print(
        f"{name:<40} {len(texts):>5} paragraphs in {seconds:7.2f} s = {len(texts) / seconds:9.1f} per s, {dims} dims",
        flush=True,
    )


static = StaticModel.from_pretrained("JanSchachtschabel/m2v-gte-256-edu")
timed("m2v-gte-256-edu (Dienst, statisch)", lambda t: static.encode(t), paragraphs[:3000], 256)

for name, count, prefix, kwargs in (
    ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", 400, "", {}),
    ("intfloat/multilingual-e5-small", 400, "passage: ", {}),
    ("BAAI/bge-m3", 120, "", {}),
):
    try:
        model = SentenceTransformer(name, device=device, **kwargs)
        model.max_seq_length = 256
        texts = [prefix + p for p in paragraphs[:count]]
        dims = model.get_sentence_embedding_dimension()
        timed(
            f"{name} (256 Token)", lambda t, m=model: m.encode(t, batch_size=32, show_progress_bar=False), texts, dims
        )
        del model
    except Exception as exc:  # one model that does not load must not end the measurement
        print(f"{name}: {type(exc).__name__}: {exc}"[:200], flush=True)
