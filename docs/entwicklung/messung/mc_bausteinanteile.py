"""M51: the share of model knowledge per block of part 1 - blocks with evidence (a citation number) apart from those
without -, by sentences, which the prompt of best-quality-generated caps at half, and by characters.

Reads the runs of mc_kompendium_profil.py (their texts stay outside the repository) and prints a line per variant.

Usage: python mc_bausteinanteile.py <runs.json> [<runs.json> ...] [--variants=a,b]
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

LABEL = "[Modellwissen]"
NUMBER = re.compile(r"\[\d+(?:,\s?\d+)*\]")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?!\[Modellwissen\])|(?<=\[Modellwissen\])\s+")
ORDINAL = re.compile(r"\d\.$")  # "im 19." - the sentence goes on in the next piece


def sentences(text: str) -> list[str]:
    """The sentences of a block, the pieces an ordinal ends joined to the next one."""
    found: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        for piece in SENTENCE_END.split(" ".join(paragraph.split())):
            if not piece.strip():
                continue
            if found and ORDINAL.search(found[-1]):
                found[-1] = f"{found[-1]} {piece}"
            else:
                found.append(piece)
    return found


def blocks(text: str) -> list[dict[str, float]]:
    """Per block: whether it cites, its sentences and characters, and how many of them are model knowledge."""
    found = []
    for part in re.split(r"^### ", text, flags=re.MULTILINE):
        body = part.split("\n", 1)[1] if "\n" in part else ""
        said = sentences(body)
        if not said:
            continue
        marked = [s for s in said if LABEL in s]
        found.append(
            {
                "cites": bool(NUMBER.search(body)),
                "sentences": len(said),
                "marked": len(marked),
                "chars": sum(len(s) for s in said),
                "marked_chars": sum(len(s) for s in marked),
            }
        )
    return found


def main() -> None:
    wanted = next((a.removeprefix("--variants=").split(",") for a in sys.argv[1:] if a.startswith("--variants=")), None)
    runs = [r for a in sys.argv[1:] if not a.startswith("--") for r in json.loads(Path(a).read_text(encoding="utf-8"))]
    variants = wanted or sorted({r["variant"] for r in runs})
    for variant in variants:
        mine = [r for r in runs if r["variant"] == variant and r.get("text")]
        cited, uncited, over = [], 0, 0
        shares_sentences, shares_chars = [], []
        for run in mine:
            per_run = blocks(run["text"])
            with_evidence = [b for b in per_run if b["cites"]]
            uncited += len(per_run) - len(with_evidence)
            cited += with_evidence
            over += sum(1 for b in with_evidence if b["marked"] > b["sentences"] / 2)
            if with_evidence:
                shares_sentences.append(sum(b["marked"] for b in with_evidence) / sum(b["sentences"] for b in with_evidence))
                shares_chars.append(
                    sum(b["marked_chars"] for b in with_evidence) / sum(b["chars"] for b in with_evidence)
                )
        if not mine:
            continue
        print(
            f"{variant:26s} {len(mine)} Läufe | Bausteine mit Beleg {len(cited)}, ohne {uncited} | "
            f"Modellwissen in Bausteinen mit Beleg: Sätze {statistics.median(shares_sentences):.0%} "
            f"({min(shares_sentences):.0%} bis {max(shares_sentences):.0%}), Zeichen "
            f"{statistics.median(shares_chars):.0%} | Bausteine mit Beleg über der Hälfte der Sätze: {over} von {len(cited)}"
        )


if __name__ == "__main__":
    main()
