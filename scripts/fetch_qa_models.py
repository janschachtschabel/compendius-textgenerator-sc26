"""Fetch the two models of the QA stage ``models`` at image build time (docs/umbau.md U5b).

The runtime never talks to the Hugging Face hub (``HF_HUB_OFFLINE=1``), so both models are baked in with a
pinned revision: the same build tomorrow yields the same image. Only the files the loaders need are fetched -
gelectra ships its weights three times (safetensors, .bin, TensorFlow .h5) and the generator keeps its
training traces beside them, which together would add about a gigabyte of dead weight.

After downloading, both models are loaded once. A download that cannot be loaded has to fail the build, not
the first request of an operator.

    python scripts/fetch_qa_models.py --qg-id dehio/german-qg-t5-quad --qg-revision <sha> ...
"""

from __future__ import annotations

import argparse
from pathlib import Path

# Weights, config and tokenizer - nothing else. Both lists are deliberately narrow.
QG_FILES = ["config.json", "*token*", "spiece.model", "pytorch_model.bin", "*.safetensors"]
QA_FILES = ["config.json", "*token*", "vocab.txt", "*.safetensors"]


def fetch(model_id: str, revision: str, target: Path, patterns: list[str]) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(model_id, revision=revision, local_dir=str(target), allow_patterns=patterns)


def load_once(qg: Path, qa: Path) -> None:
    """Load both models so a broken download fails the build instead of the first request."""
    from transformers import AutoModelForQuestionAnswering, AutoModelForSeq2SeqLM, AutoTokenizer

    AutoTokenizer.from_pretrained(str(qg))
    AutoModelForSeq2SeqLM.from_pretrained(str(qg))
    AutoTokenizer.from_pretrained(str(qa))
    AutoModelForQuestionAnswering.from_pretrained(str(qa))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qg-id", required=True, help="Question generator; empty skips the whole stage")
    parser.add_argument("--qg-revision", required=True)
    parser.add_argument("--qg-target", default="/models/qg")
    parser.add_argument("--qa-id", required=True, help="Extractive answer model")
    parser.add_argument("--qa-revision", required=True)
    parser.add_argument("--qa-target", default="/models/qa")
    args = parser.parse_args()

    if not args.qg_id or not args.qa_id:
        print("no QA models requested; the stage `models` will report itself unavailable")
        return 0
    qg, qa = Path(args.qg_target), Path(args.qa_target)
    fetch(args.qg_id, args.qg_revision, qg, QG_FILES)
    fetch(args.qa_id, args.qa_revision, qa, QA_FILES)
    load_once(qg, qa)
    for name, path in (("question generator", qg), ("answer model", qa)):
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        print(f"{name}: {size / 1e6:.0f} MB in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
