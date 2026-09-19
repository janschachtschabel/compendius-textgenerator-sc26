"""CLI round trip on the sample archives: eval export -> reviewed CSV -> eval import -> eval run."""

import csv
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.cli import main
from app.settings import get_settings
from tests.conftest import ROOT


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_zims: dict[str, Path]) -> Iterator[Path]:
    env = {
        "ZIM_PATHS": ",".join(str(p) for p in sample_zims.values()),
        "ZIM_REQUIRED": "wikipedia_de_sample,klexikon_de_sample",
        "ZIM_DIR": str(tmp_path / "zim"),
        "CONFIG_DIR": str(ROOT / "config"),
        "STATE_DIR": str(tmp_path / "state"),
        "EVAL_GOLD_DIR": str(tmp_path / "gold"),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _accept_suggestions(csv_path: Path) -> int:
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    for row in rows:
        row["gold_slot"] = row["suggested_slot"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def test_export_import_run_round_trip(cli_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv_path = cli_env / "optik.csv"
    assert main(["eval", "export", "--topic", "Optik", "--out", str(csv_path)]) == 0
    count = _accept_suggestions(csv_path)  # the current assignment as gold: a smoke test, not a quality claim
    assert count > 10

    gold_path = cli_env / "gold" / "optik.jsonl"
    assert (
        main(["eval", "import", str(csv_path), "--topic", "Optik", "--out", str(gold_path), "--labeled-by", "t"]) == 0
    )
    assert gold_path.exists()
    assert "Labels" in capsys.readouterr().out

    report_path = cli_env / "report.json"
    argv = ["eval", "run", "--gold", str(cli_env / "gold"), "--matcher", "hybrid_light", "--matcher", "lexicon_only"]
    assert main([*argv, "--json", str(report_path)]) == 0
    out = capsys.readouterr().out
    assert "hybrid_light" in out
    assert "macro-F1" in out
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["runs"][0]["topic"] == "Optik"
    assert report["runs"][0]["labeled"] == count
    assert report["aggregate"]["hybrid_light"]["macro_f1"] == pytest.approx(1.0)  # gold equals its own output
    assert report["aggregate"]["lexicon_only"]["macro_f1"] < 1.0

    assert main([*argv, "--min-f1", "1.01"]) == 1


def test_run_without_gold_files_exits_2(cli_env: Path) -> None:
    (cli_env / "empty").mkdir()
    assert main(["eval", "run", "--gold", str(cli_env / "empty")]) == 2


def test_export_unknown_topic_exits_1(cli_env: Path) -> None:
    assert main(["eval", "export", "--topic", "Xyzzyplomb", "--out", str(cli_env / "x.csv")]) == 1


def test_run_with_llm_extraction_but_no_llm_says_so_and_evaluates_the_rules(
    cli_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = cli_env / "optik.csv"
    assert main(["eval", "export", "--topic", "Optik", "--out", str(csv_path)]) == 0
    _accept_suggestions(csv_path)
    gold_path = cli_env / "gold" / "optik.jsonl"
    assert main(["eval", "import", str(csv_path), "--topic", "Optik", "--out", str(gold_path)]) == 0
    capsys.readouterr()
    argv = ["eval", "run", "--gold", str(cli_env / "gold"), "--matcher", "hybrid_light", "--llm-extraction"]
    assert main(argv) == 0
    captured = capsys.readouterr()
    assert "hybrid_light" in captured.out and "hybrid_light+llm" not in captured.out
    assert "LLM-Extraktion nicht bewertet" in captured.err and "konfiguriert" in captured.err
