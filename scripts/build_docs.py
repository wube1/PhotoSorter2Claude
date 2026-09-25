#!/usr/bin/env python3
"""Build docs/PhotoSorter2Claude-Documentation.pdf from docs/DOCUMENTATION.md + CHANGELOG.md.

Requires: pip install markdown playwright  (and a Chromium; set CHROMIUM_PATH to use a system one)
"""

from __future__ import annotations

import base64
import datetime as dt
import os
import re
import sys
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = DOCS / "PhotoSorter2Claude-Documentation.pdf"

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
body { font: 10.5pt/1.5 -apple-system, "Segoe UI", Roboto, "DejaVu Sans", Arial, sans-serif; color: #1b1e24; }
h1 { font-size: 22pt; margin: 0 0 8pt; color: #1d4ed8; page-break-before: always; }
h1.first { page-break-before: avoid; }
h2 { font-size: 15pt; margin: 20pt 0 6pt; color: #1d4ed8; border-bottom: 1px solid #dbe2ef; padding-bottom: 3pt; page-break-after: avoid; }
h3 { font-size: 12pt; margin: 14pt 0 4pt; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
code { font: 9pt "DejaVu Sans Mono", Consolas, monospace; background: #f1f4f9; padding: 1px 4px; border-radius: 3px; }
pre { background: #0f172a; color: #e2e8f0; padding: 10pt 12pt; border-radius: 6px; font-size: 8.6pt; line-height: 1.45; white-space: pre-wrap; page-break-inside: avoid; }
pre code { background: none; color: inherit; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0 12pt; font-size: 9.3pt; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th { background: #eef3fc; text-align: left; }
th, td { border: 1px solid #d5dce8; padding: 5pt 7pt; vertical-align: top; }
blockquote { margin: 10pt 0; padding: 8pt 12pt; background: #fff7e0; border-left: 4px solid #f0b400; border-radius: 4px; }
img { max-width: 100%; border: 1px solid #d5dce8; border-radius: 6px; display: block; margin: 8pt auto 2pt; page-break-inside: avoid; }
p.caption { text-align: center; color: #5b6270; font-size: 9pt; margin-bottom: 14pt; }
.cover { height: 250mm; display: flex; flex-direction: column; justify-content: center; page-break-after: always; }
.cover .logo { width: 72px; height: 72px; border: none; margin: 0 0 20pt; }
.cover h1 { font-size: 34pt; page-break-before: avoid; margin: 0; }
.cover .sub { font-size: 14pt; color: #5b6270; margin: 8pt 0 30pt; }
.cover .meta { font-size: 10.5pt; color: #5b6270; }
.toc { page-break-after: always; }
.toc ul { list-style: none; padding-left: 0; }
.toc li { margin: 3pt 0; }
.toc ul ul { padding-left: 16pt; }
.toc a { color: #1b1e24; text-decoration: none; }
"""


def read_md(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    if text.startswith("---"):
        _, front, text = text.split("---", 2)
        for line in front.strip().splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta, text


def inline_images(html: str) -> str:
    """Embed local images as data URIs and add a caption from the alt text."""

    def repl(m: re.Match[str]) -> str:
        alt, src = m.group("alt"), m.group("src")
        path = (DOCS / src).resolve()
        if not path.is_file():
            return m.group(0)
        mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        data = base64.b64encode(path.read_bytes()).decode()
        return f'<img src="data:{mime};base64,{data}" alt="{alt}"><p class="caption">{alt}</p>'

    return re.sub(r'<p><img alt="(?P<alt>[^"]*)" src="(?P<src>[^"]+)" ?/?></p>', repl, html)


def main() -> int:
    version = (ROOT / "VERSION").read_text().strip()
    meta, body = read_md(DOCS / "DOCUMENTATION.md")
    _, changelog = read_md(ROOT / "CHANGELOG.md")
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"], extension_configs={"toc": {"toc_depth": "2-3"}})
    html_body = md.convert(body + "\n\n" + changelog)
    toc = md.toc  # type: ignore[attr-defined]
    html_body = inline_images(html_body)
    html_body = html_body.replace("<h1", '<h1 class="first"', 1)
    logo = base64.b64encode((ROOT / "frontend/public/favicon.svg").read_bytes()).decode()
    today = dt.date.today().isoformat()
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{meta.get('title', 'Documentation')}</title>
<style>{CSS}</style></head><body>
<section class="cover">
  <img class="logo" src="data:image/svg+xml;base64,{logo}" alt="">
  <h1>{meta.get('title', 'PhotoSorter2Claude')}</h1>
  <div class="sub">{meta.get('subtitle', '')}</div>
  <div class="meta">Version {version} · {today}<br>https://github.com/wube1/PhotoSorter2Claude</div>
</section>
<section class="toc"><h2>Contents</h2>{toc}</section>
{html_body}
</body></html>"""
    (DOCS / ".build.html").write_text(html, encoding="utf-8")
    footer = (
        '<div style="font-size:8px;width:100%;padding:0 16mm;color:#8a93a3;display:flex;justify-content:space-between">'
        f'<span>PhotoSorter2Claude {version}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>'
    )
    with sync_playwright() as p:
        kwargs = {}
        if os.environ.get("CHROMIUM_PATH"):
            kwargs["executable_path"] = os.environ["CHROMIUM_PATH"]
        browser = p.chromium.launch(**kwargs)
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        page.pdf(path=str(OUT), format="A4", print_background=True, display_header_footer=True,
                 header_template="<span></span>", footer_template=footer,
                 margin={"top": "18mm", "bottom": "20mm", "left": "16mm", "right": "16mm"})
        browser.close()
    (DOCS / ".build.html").unlink(missing_ok=True)
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
