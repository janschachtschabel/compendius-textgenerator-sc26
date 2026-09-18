"""Extract article HTML from local ZIM dumps into test fixtures.

The fixtures under tests/fixtures/zim_html/<project>/ are used to build small sample ZIM
archives offline in the test session (see tests/conftest.py). Run this script only when
fixtures need refreshing; it needs the real dumps.

    python scripts/extract_zim_fixtures.py --zim data/wikipedia_de_all_nopic_2026-01.zim \
        --project wikipedia --out tests/fixtures/zim_html Optik "Geometrische Optik"
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

import libzim


def safe_name(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9_().-]+", "_", path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zim", required=True, help="ZIM archive to read from")
    parser.add_argument("--project", required=True, help="wikipedia, klexikon, ...")
    parser.add_argument("--out", default="tests/fixtures/zim_html", help="fixture root directory")
    parser.add_argument("titles", nargs="+", help="article titles (redirects are followed)")
    args = parser.parse_args()

    archive = libzim.Archive(pathlib.Path(args.zim))
    out_dir = pathlib.Path(args.out) / args.project
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = pathlib.Path(args.out) / "MANIFEST.json"
    manifest: dict[str, object] = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries: list[dict[str, str]] = list(manifest.get("entries", []))  # type: ignore[arg-type]

    def meta(key: str) -> str:
        try:
            return archive.get_metadata(key).decode("utf-8", "replace")
        except Exception:  # metadata is optional
            return ""

    for title in args.titles:
        if not archive.has_entry_by_title(title):
            print(f"  ! nicht gefunden: {title}", file=sys.stderr)
            continue
        entry = archive.get_entry_by_title(title)
        if entry.is_redirect:
            entry = entry.get_redirect_entry()
        html = bytes(entry.get_item().content).decode("utf-8", "replace")
        file_name = safe_name(entry.path) + ".html"
        (out_dir / file_name).write_text(html, encoding="utf-8")
        entries = [e for e in entries if not (e["project"] == args.project and e["path"] == entry.path)]
        entries.append(
            {
                "project": args.project,
                "title": entry.title,
                "path": entry.path,
                "file": f"{args.project}/{file_name}",
                "zim": pathlib.Path(args.zim).name,
                "zim_date": meta("Date"),
                "license": "CC BY-SA 4.0",
            }
        )
        print(f"  + {entry.title:45s} -> {file_name} ({len(html) / 1024:.1f} KB)")

    manifest["note"] = (
        "Article HTML from Kiwix ZIM dumps (openZIM/mwoffliner), CC BY-SA 4.0. "
        "Used only to build small sample archives for offline tests."
    )
    manifest["entries"] = sorted(entries, key=lambda e: (e["project"], e["path"]))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
