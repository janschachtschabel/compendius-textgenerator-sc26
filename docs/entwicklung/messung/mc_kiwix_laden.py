"""Fetch the further Kiwix archives of M84 again (project venv): the measured archives were deleted after M84 (D99).

The same steps as ``ZimSync``: the newest dump of a name and flavour from the Kiwix catalog, its metalink from an
allowed host, then the download checked against the metalink's size and SHA-256, each archive in a folder of its own
under ``<target_root>/<archive id>/``, where mc_kiwix_quellen.py reads them. On 2026-10-09 the catalog offered the dumps
M84 measured; a newer dump gives other numbers. About 7 GB.

Usage: python mc_kiwix_laden.py [<target_root>]  (default: C:/Users/jan/staging/Windsurf/kompendium-test/data/zusatz)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from app.sources.zim.catalog import KiwixCatalog
from app.sources.zim.downloader import DEFAULT_ALLOWED_HOSTS, Downloader, check_download_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
WANTED = [("wikibooks_de_all", "nopic"), ("wikiversity_de_all", "nopic"), ("wiktionary_de_all", "nopic"),
          ("wikisource_de_all", "nopic"), ("wikiquote_de_all", "nopic"), ("wikivoyage_de_all", "nopic")]
DEFAULT_ROOT = Path(r"C:\Users\jan\staging\Windsurf\kompendium-test\data\zusatz")

root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ROOT
catalog, downloader = KiwixCatalog(), Downloader()


def check(url: str) -> None:
    check_download_url(url, DEFAULT_ALLOWED_HOSTS)


for name, flavour in WANTED:
    entry = catalog.latest(name, flavour)
    if entry is None:
        print(f"{name} {flavour}: not in the catalog", flush=True)
        continue
    check(entry.metalink_url)
    metalink = catalog.metalink(entry.metalink_url, check=check)
    check(metalink.source_url)
    target = root / entry.archive_id
    print(f"{entry.file_name}: {metalink.size / 1e9:.2f} GB -> {target}", flush=True)
    path = downloader.download(entry.download_url, target, digest=metalink.sha256, size=metalink.size)
    print(f"OK {path} ({path.stat().st_size} bytes, SHA-256 checked)", flush=True)
