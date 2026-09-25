"""Record the spaCy parse of new test inputs of the /qa rule stage into tests/fixtures/qa_rule_parses.json (D55).

The rule stage reads the parse of de_core_news_md, which lives in the image and not in the test environment; the
tests replay recorded parses (tests/recorded_spacy.py). A new test input has to be recorded here first, in the
image, as the rule stage hands it to spaCy. Copy the fixture in, run, copy the new one back - to a second path,
since a file ``docker cp`` put into the container belongs to root, not to the user the service runs as:

    docker cp tests/fixtures/qa_rule_parses.json <container>:/tmp/parses.json
    docker cp scripts/record_qa_parses.py <container>:/tmp/record_qa_parses.py
    docker exec -w /app <container> python /tmp/record_qa_parses.py /tmp/parses.json /tmp/new.json "Ein Satz." ...
    docker cp <container>:/tmp/new.json tests/fixtures/qa_rule_parses.json
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from app.knowledge.recognise import load_spacy
from app.settings import get_settings
from app.synthesis.qa_words import parse_ready


def recorded(doc: Any) -> dict[str, Any]:
    return {
        "ents": [[entity.start, entity.end, entity.label_] for entity in doc.ents],
        "tokens": [[t.text, t.whitespace_, t.pos_, t.tag_, t.dep_, t.head.i, t.lemma_, str(t.morph)] for t in doc],
    }


def dump(fixture: dict[str, Any]) -> str:
    """One token per line, so a diff of the fixture shows what changed."""
    lines = ["{", f' "model": {json.dumps(fixture["model"])},', f' "recorded": {json.dumps(fixture["recorded"])},']
    lines.append(' "parses": {')
    items = list(fixture["parses"].items())
    for number, (text, parse) in enumerate(items):
        tokens = ",\n".join("    " + json.dumps(token, ensure_ascii=False) for token in parse["tokens"])
        comma = "," if number < len(items) - 1 else ""
        lines.append(f'  {json.dumps(text, ensure_ascii=False)}: {{\n   "ents": {json.dumps(parse["ents"])},')
        lines.append(f'   "tokens": [\n{tokens}\n   ]\n  }}{comma}')
    lines += [" }", "}", ""]
    return "\n".join(lines)


def main(source: str, target: str, inputs: list[str]) -> None:
    model = get_settings().spacy_model
    nlp = load_spacy(model)
    if nlp is None:
        raise SystemExit(f"spaCy model {model!r} is not installed here; run this in the image")
    fixture = json.loads(Path(source).read_text(encoding="utf-8")) if Path(source).exists() else {"parses": {}}
    if inputs:
        fixture.update(model=model, recorded=date.today().isoformat())
    for text in inputs:
        prepared = parse_ready(text)
        fixture["parses"][prepared] = recorded(nlp(prepared))
    Path(target).write_text(dump(fixture), encoding="utf-8", newline="\n")
    print(f"{len(inputs)} recorded, {len(fixture['parses'])} in {target}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
