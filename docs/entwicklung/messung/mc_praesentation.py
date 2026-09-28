"""Pages 01, 09 and 07 of docs/entwicklung as one HTML page for the presentation, every chart inline (project venv).

The page needs nothing beside itself: the charts of bilder/ are embedded, so it opens in any browser after a download.
Links to the other pages of the docs point to GitHub. Run it again after one of the three pages or a chart changed
(the charts come from mc_grafiken.py); it names the last commit of its sources and warns about uncommitted changes.

Usage: python mc_praesentation.py [<ziel.html>] [--fragment]
  default target: docs/entwicklung/praesentation.html
  --fragment: without <!doctype>, <html>, <head> and <body>, for a Claude artifact, which adds its own
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

from markdown_it import MarkdownIt

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DOCS = Path(__file__).resolve().parents[1]
REPO = DOCS.parents[1]
GITHUB = "https://github.com/janschachtschabel/compendius-textgenerator-sc26/blob/main/docs/entwicklung/"
# order on the page; 07 claims its anchors first, so links into the former single page of 07 keep working
PAGES = [("01", "01-alt-und-neu.md"), ("09", "09-methoden-und-profile.md"), ("07", "07-entscheidungsvorlage.md")]
INTERNAL = {name: f"#seite-{number}" for number, name in PAGES}
PROFILE_CLASS = {"llm-free": "p-free", "balanced": "p-balanced", "best-quality": "p-best",
                 "best-quality-generated": "p-gen"}

md = MarkdownIt("commonmark", {"html": False}).enable("table")
used_ids: set[str] = set()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=DOCS, capture_output=True, text=True, check=True).stdout.strip()


def source_commit() -> str:
    """The last commit of the three pages and the charts; a warning, and a note on the page, if they changed since."""
    sources = [name for _, name in PAGES] + ["bilder"]
    commit = git("log", "-1", "--format=%h", "--", *sources)
    changed = git("status", "--porcelain", "--", *sources)
    if changed:
        print(f"Warnung: ungesicherte Änderungen an den Quellen, die Seite nennt sie:\n{changed}", file=sys.stderr)
        return f"Commit <code>{commit}</code> und ungesicherte Änderungen"
    return f"Commit <code>{commit}</code>"


def strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def slug(text: str) -> str:
    plain = strip_tags(text).lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        plain = plain.replace(a, b)
    base = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")
    anchor, n = base, 2
    while anchor in used_ids:
        anchor, n = f"{base}-{n}", n + 1
    used_ids.add(anchor)
    return anchor


def link(match: re.Match[str]) -> str:
    target = match.group(1)
    if target.startswith("#"):
        return f'href="{target}"'
    if target.startswith(("http://", "https://")):
        return f'href="{target}" target="_blank" rel="noopener"'
    page = target.split("#", 1)[0]
    if page in INTERNAL:
        return f'href="{INTERNAL[page]}"'
    return f'href="{GITHUB}{target}" target="_blank" rel="noopener"'


def figure(match: re.Match[str]) -> str:
    name, alt = match.group(1), match.group(2)
    svg = (DOCS / "bilder" / name).read_text(encoding="utf-8").strip()
    return f'<figure class="chart" role="group" aria-label="{alt}">{svg}<figcaption>{alt}</figcaption></figure>'


def profile_head(match: re.Match[str]) -> str:
    cell = match.group(1)
    first = re.match(r"<code>([a-z-]+)</code>", cell)
    css = PROFILE_CLASS.get(first.group(1)) if first else None
    return f'<th class="{css}">{cell}</th>' if css else f"<th>{cell}</th>"


def mark_profile_tables(body: str) -> str:
    """Profile columns get their colour; a table keeps about 150 px per column (up to the width of the page on a desktop)
    and scrolls on a phone instead of squeezing its columns."""

    def table(match: re.Match[str]) -> str:
        html = re.sub(r"<th>(.*?)</th>", profile_head, match.group(0))
        columns = html.split("</thead>", 1)[0].count("<th")
        css = ' class="profiles"' if 'class="p-' in html else ""
        return html.replace("<table>", f'<table{css} style="min-width: {min(150 * columns, 900)}px">', 1)

    return re.sub(r"<table>.*?</table>", table, body, flags=re.S)


def render(number: str, name: str) -> dict:
    source = (DOCS / name).read_text(encoding="utf-8").replace("\r\n", "\n")
    title_line, _, rest = source.partition("\n")
    title = title_line.removeprefix("# ").strip()
    meta_md, _, body_md = rest.strip().partition("\n\n")
    stand = re.search(r"Stand (\d{2})\.(\d{2})\.(\d{4})", meta_md)
    if stand is None:
        raise SystemExit(f"{name} nennt keinen Stand in der zweiten Zeile")
    body = md.render(body_md)
    missing = [n for n in re.findall(r'<img src="bilder/([^"]+)"', body) if not (DOCS / "bilder" / n).exists()]
    if missing:
        raise SystemExit(f"{name}: Grafik fehlt: {missing}")
    body = re.sub(r'<p><img src="bilder/([^"]+)" alt="([^"]*)" /></p>', figure, body)
    if "<img" in body:
        raise SystemExit(f"{name}: ein Bild steht nicht allein in seinem Absatz")
    body = body.replace("<h3>", "<h4>").replace("</h3>", "</h4>")
    sections: list[tuple[str, str]] = []

    def h3(match: re.Match[str]) -> str:
        anchor = slug(match.group(1))
        sections.append((anchor, strip_tags(match.group(1))))
        return f'<h3 id="{anchor}">{match.group(1)}</h3>'

    body = re.sub(r"<h2>(.*?)</h2>", h3, body)
    body = mark_profile_tables(body)
    body = body.replace("<table", '<div class="table-wrap"><table').replace("</table>", "</table></div>")
    body = re.sub(r'href="([^"]+)"', link, body)
    meta = re.sub(r'href="([^"]+)"', link, md.render(meta_md)).replace("<p>", "").replace("</p>", "").strip()
    return {"number": number, "title": title, "meta": meta, "body": body, "sections": sections,
            "stand": (stand.group(3), stand.group(2), stand.group(1))}


args = [arg for arg in sys.argv[1:] if arg != "--fragment"]
fragment = "--fragment" in sys.argv[1:]
out = Path(args[0]) if args else DOCS / "praesentation.html"
commit = source_commit()
version = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
last_measurement = max(int(m) for m in re.findall(r"^## M(\d+) ", (DOCS / "05-messprotokoll.md").read_text(
    encoding="utf-8"), flags=re.M))

rendered = {number: render(number, name) for number, name in sorted(PAGES, key=lambda p: p[0] != "07")}
pages = [rendered[number] for number, _ in PAGES]
year, month, day = max(page["stand"] for page in pages)

toc = "\n".join(
    f'<div class="toc-group"><p class="toc-head"><a href="#seite-{p["number"]}"><span class="num">{p["number"]}</span>'
    f'{p["title"]}</a></p><ol>' + "".join(f'<li><a href="#{a}">{t}</a></li>' for a, t in p["sections"]) + "</ol></div>"
    for p in pages
)
docs = "\n".join(
    f'<section class="doc" id="seite-{p["number"]}" aria-labelledby="seite-{p["number"]}-titel">\n'
    f'<div class="doc-head"><p class="doc-label">Seite {p["number"]} der Entwicklungsdoku</p>'
    f'<a class="to-top" href="#inhalt">Inhalt ↑</a></div>\n'
    f'<h2 class="doc-title" id="seite-{p["number"]}-titel">{p["title"]}</h2>\n<p class="meta">{p["meta"]}</p>\n'
    f'{p["body"]}</section>'
    for p in pages
)

head = """<title>Verfahrenswahl Kompendium SC26</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&display=swap">
<style>
:root {
  --ground: #f4f6f9; --surface: #ffffff; --soft: #eaeff5; --ink: #1c2530; --muted: #536071; --rule: #d9dfe7;
  --local: #2f6db5; --mix: #7a5aa6; --llm: #c46f1c; --gen: #b24c63; --code: #e9edf3; --link: #245aa0;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground: #10141a; --surface: #161c24; --soft: #1c2430; --ink: #e2e7ee; --muted: #9ba7b6; --rule: #2a3340;
    --local: #7aa8e8; --mix: #b39ddb; --llm: #eba55c; --gen: #e58aa0; --code: #1c2430; --link: #8db6f0;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --ground: #10141a; --surface: #161c24; --soft: #1c2430; --ink: #e2e7ee; --muted: #9ba7b6; --rule: #2a3340;
  --local: #7aa8e8; --mix: #b39ddb; --llm: #eba55c; --gen: #e58aa0; --code: #1c2430; --link: #8db6f0;
  color-scheme: dark;
}
body {
  margin: 0; background: var(--ground); color: var(--ink);
  font: 16px/1.62 "IBM Plex Sans", "Segoe UI", system-ui, -apple-system, sans-serif;
  padding-inline: 16px; padding-block: 28px 72px;
}
main { max-width: 1000px; margin: 0 auto; }
.page-head { margin-bottom: 1rem; }
.eyebrow { font-size: .78rem; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin: 0 0 .4rem; }
h1 { font-size: clamp(1.6rem, 4vw, 2.3rem); line-height: 1.18; margin: 0 0 .8rem; font-weight: 600; text-wrap: balance; }
.lede { font-size: 1.05rem; margin: 0 0 .8rem; }
.meta { color: var(--muted); font-size: .92rem; margin: 0 0 1rem; max-width: 90ch; }
.toc { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem 1.8rem;
  border-block: 1px solid var(--rule); padding-block: 1rem; font-size: .88rem; scroll-margin-top: 16px; }
.toc-head { margin: 0 0 .4rem; font-weight: 600; font-size: .95rem; line-height: 1.35; }
.toc-head a { color: var(--ink); text-decoration: none; }
.toc-head a:hover { text-decoration: underline; }
.num { font-family: "IBM Plex Mono", ui-monospace, Consolas, monospace; font-weight: 500; color: var(--muted);
  margin-right: .45rem; }
.toc ol { list-style: none; padding: 0; margin: 0; }
.toc li { margin: 0 0 .25rem; line-height: 1.4; max-width: none; }
.doc { margin-top: 3.6rem; }
.doc-head { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; flex-wrap: wrap;
  border-top: 3px solid var(--ink); padding-top: .7rem; }
.doc-label { margin: 0; font: 500 .78rem/1.4 "IBM Plex Mono", ui-monospace, Consolas, monospace; letter-spacing: .06em;
  text-transform: uppercase; color: var(--muted); }
.to-top { font-size: .85rem; }
h2.doc-title { font-size: clamp(1.45rem, 3.4vw, 1.9rem); line-height: 1.2; font-weight: 600; margin: .5rem 0 .6rem;
  text-wrap: balance; scroll-margin-top: 16px; }
h3 { font-size: 1.3rem; line-height: 1.3; font-weight: 600; margin: 2.6rem 0 .9rem; text-wrap: balance;
  scroll-margin-top: 16px; }
h4 { font-size: 1.06rem; font-weight: 600; margin: 1.9rem 0 .6rem; }
p, li { max-width: 72ch; }
li:has(.table-wrap) { max-width: none; }
ul, ol { padding-left: 1.2rem; }
li { margin-bottom: .45rem; }
a { color: var(--link); text-underline-offset: 2px; }
a:focus-visible { outline: 2px solid var(--link); outline-offset: 2px; border-radius: 2px; }
code { font-family: "IBM Plex Mono", ui-monospace, Consolas, monospace; font-size: .86em; background: var(--code);
  padding: .08em .34em; border-radius: 4px; overflow-wrap: anywhere; }
pre { background: var(--code); border: 1px solid var(--rule); border-radius: 8px; padding: 12px 14px;
  overflow-x: auto; font-size: .9rem; line-height: 1.5; }
pre code { background: none; padding: 0; font-size: 1em; }
td code, th code { white-space: nowrap; }
.table-wrap { overflow-x: auto; margin: 1rem 0 1.5rem; background: var(--surface); border: 1px solid var(--rule);
  border-radius: 8px; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; line-height: 1.45;
  font-variant-numeric: tabular-nums; }
th, td { text-align: left; vertical-align: top; padding: .5rem .75rem; border-bottom: 1px solid var(--rule); }
thead th { background: var(--soft); font-weight: 600; }
tbody tr:last-child td { border-bottom: none; }
th.p-free { box-shadow: inset 0 3px 0 var(--local); }
th.p-balanced { box-shadow: inset 0 3px 0 var(--mix); }
th.p-best { box-shadow: inset 0 3px 0 var(--llm); }
th.p-gen { box-shadow: inset 0 3px 0 var(--gen); }
table.profiles tbody td:first-child { color: var(--muted); }
figure.chart { margin: 1.2rem 0 1.8rem; background: #ffffff; border: 1px solid var(--rule); border-radius: 10px;
  padding: 10px 10px 4px; overflow-x: auto; }
figure.chart svg { display: block; max-width: 100%; min-width: 620px; height: auto; margin: 0 auto; }
figure.chart figcaption { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
strong { font-weight: 600; }
footer { margin-top: 3.6rem; border-top: 1px solid var(--rule); padding-top: .8rem; color: var(--muted);
  font-size: .85rem; }
</style>"""

main = f"""<main>
<header class="page-head">
<p class="eyebrow">Präsentation und Entscheidungsvorlage · Kompendium-Dienst SC26 · Release {version} · Stand {day}.{month}.{year}</p>
<h1>Kompendium-Dienst SC26: Vergleich, Methoden und Entscheidungen</h1>
<p class="lede">Drei Seiten der Entwicklungsdoku auf einer: was der alte und der neue Dienst in den drei Teilen des
Kompendiums liefern; je Schritt die gemessenen Methoden mit Güte, Zeit und Tokens und welches der vier Profile welche
nutzt; die Entscheidungsvorlage mit den Empfehlungen je Profil und den offenen Punkten.</p>
<p class="meta">Quelle: <a href="{GITHUB}README.md" target="_blank" rel="noopener">docs/entwicklung</a> im Repository
<code>compendius-textgenerator-sc26</code>, {commit} · Zahlen:
<a href="{GITHUB}05-messprotokoll.md" target="_blank" rel="noopener">Messprotokoll</a>, M1 bis M{last_measurement}</p>
<nav class="toc" id="inhalt" aria-label="Inhalt">
{toc}
</nav>
</header>
{docs}
<footer>Erzeugt mit <code>messung/mc_praesentation.py</code> aus <code>docs/entwicklung</code>, {commit}; Grafiken von
<code>messung/mc_grafiken.py</code>. Links auf weitere Seiten der Doku führen zu GitHub.</footer>
</main>"""

if fragment:
    page = f"{head}\n{main}\n"
else:
    page = (f'<!doctype html>\n<html lang="de">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n{head}\n</head>\n<body>\n{main}\n'
            f"</body>\n</html>\n")
out.write_text(page, encoding="utf-8", newline="\n")
total = sum(len(p["sections"]) for p in pages)
print(f"{out}: {len(page.encode('utf-8')):,} Bytes, {total} Abschnitte, {page.count('<figure')} Grafiken")
