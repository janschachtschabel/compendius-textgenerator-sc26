"""Fetch the two models of the QA stage ``models`` at image build time (docs/umbau.md U5b).

The runtime never talks to the Hugging Face hub (``HF_HUB_OFFLINE=1``), so both models are baked in with a
pinned revision: the same build tomorrow yields the same image. Only the files the loaders need are fetched -
gelectra ships its weights three times (safetensors, .bin, TensorFlow .h5) and the generator keeps its
training traces beside them, which together would add about a gigabyte of dead weight.

After downloading, both models are loaded once - a download that cannot be loaded has to fail the build, not
the first request of an operator - and their weights are then stored in half precision (see ``shrink``).

    python scripts/fetch_qa_models.py --qg-id dehio/german-qg-t5-quad --qg-revision <sha> ...
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

# Weights, config and tokenizer - nothing else. Both lists are deliberately narrow.
QG_FILES = ["config.json", "*token*", "spiece.model", "pytorch_model.bin", "*.safetensors"]
QA_FILES = ["config.json", "*token*", "vocab.txt", "*.safetensors"]


def fetch(model_id: str, revision: str, target: Path, patterns: list[str]) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(model_id, revision=revision, local_dir=str(target), allow_patterns=patterns)


def shrink(path: Path, loader: Any) -> None:
    """Store the weights in half precision and prove they still load in full precision.

    Both models arrive in fp32: the generator as a pickled ``pytorch_model.bin`` of 892 MB, the answer model
    as 437 MB of safetensors. Measured in the image on 2026-09-20, rounding the stored weights to fp16 changed
    neither the 12 generated questions nor the 8 extracted answer spans, and takes 664 MB off a 3.4 GB image.
    The generator's pickle goes with it - safetensors needs no ``torch.load``.

    What is halved is the file, not the arithmetic: ``load_qa_models`` names ``float32`` when it loads, because
    transformers follows the dtype of the file and CPU support for fp16 is not something this image can promise
    for every host. The reload here proves the weights load; that they still answer is what the model check of
    ``scripts/smoke_image.py`` proves, which CI runs against every built image - a conversion that destroyed a
    model would leave it without the three pairs that check demands.
    """
    import torch

    model = loader.from_pretrained(str(path)).half()
    # half() saturates a weight above 65504 to infinity without a word. Nothing downstream would notice
    # until the answers turned to noise, so the build asks here.
    if not all(torch.isfinite(parameter).all() for parameter in model.parameters()):
        raise SystemExit(f"{path}: half precision put infinities into the weights")
    model.save_pretrained(str(path), safe_serialization=True)
    del model
    (path / "pytorch_model.bin").unlink(missing_ok=True)  # save_pretrained wrote safetensors beside it
    # Reloaded *without* a dtype on purpose: naming one would cast, and the check would pass whatever the
    # file holds. What has to be proven here is that the file itself is half precision.
    reloaded = loader.from_pretrained(str(path))
    if reloaded.dtype is not torch.float16:
        raise SystemExit(f"{path} was not stored in half precision: {reloaded.dtype}")


def prepare(qg: Path, qa: Path) -> None:
    """Load both models so a broken download fails the build instead of the first request, then shrink them."""
    from transformers import AutoModelForQuestionAnswering, AutoModelForSeq2SeqLM, AutoTokenizer

    AutoTokenizer.from_pretrained(str(qg))
    AutoTokenizer.from_pretrained(str(qa))
    shrink(qg, AutoModelForSeq2SeqLM)
    shrink(qa, AutoModelForQuestionAnswering)


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
    prepare(qg, qa)
    for name, path in (("question generator", qg), ("answer model", qa)):
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        print(f"{name}: {size / 1e6:.0f} MB in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
