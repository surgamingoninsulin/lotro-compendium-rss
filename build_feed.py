#!/usr/bin/env python3
"""
build_feed.py - Turn the LoTROInterface Plugin Compendium API into RSS 2.0 feeds.

Source : https://api.lotrointerface.com/fav/plugincompendium.xml
Output : <out>/feed.xml                 - every plugin, newest update first
         <out>/latest.xml               - the 100 most recently updated plugins
         <out>/categories/<slug>.xml    - one feed per category
         <out>/index.html               - overview page with all feed links

Uses only the Python standard library (no pip install needed).

Usage:
    python build_feed.py --out docs --base-url https://USER.github.io/REPO/
    python build_feed.py --input sample.xml --out test-output   (offline test)
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import formatdate
from pathlib import Path

SOURCE_URL = "https://api.lotrointerface.com/fav/plugincompendium.xml"
SITE_URL = "https://www.lotrointerface.com/downloads/index.php"
INFO_URL = "https://www.lotrointerface.com/downloads/fileinfo.php?id={uid}"

# A plain browser-like User-Agent; the API has returned 403s to some clients.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 lotro-plugin-feed/1.0"
)

# Refuse to publish if the source suddenly returns far fewer plugins than
# normal (outage, error page, truncated download). The old feed stays live.
MIN_EXPECTED_PLUGINS = 50
LATEST_COUNT = 100
FETCH_RETRIES = 4
FETCH_TIMEOUT = 60

# Characters that are illegal in XML 1.0 (control chars except tab/LF/CR).
_INVALID_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass(frozen=True)
class Plugin:
    uid: str
    name: str
    author: str
    version: str
    updated: int          # unix timestamp
    downloads: int
    category: str
    description: str
    file_name: str
    size: int
    file_url: str


# --------------------------------------------------------------------------- #
# Fetching and parsing
# --------------------------------------------------------------------------- #
def fetch_source(url: str) -> bytes:
    """Download the compendium XML with retries and exponential backoff."""
    last_error: Exception | None = None
    for attempt in range(1, FETCH_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
                data = resp.read()
            if not data.strip():
                raise ValueError("empty response body")
            return data
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last_error = exc
            wait = 2 ** attempt
            print(f"[fetch] attempt {attempt}/{FETCH_RETRIES} failed: {exc}; "
                  f"retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"could not download {url}: {last_error}")


def deep_unescape(text: str) -> str:
    """The API double-escapes entities inside CDATA (e.g. '&amp;amp;')."""
    for _ in range(3):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    return text


def _text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_plugins(raw: bytes) -> list[Plugin]:
    """Parse the <Favorites><Ui>...</Ui></Favorites> document."""
    text = raw.decode("utf-8", errors="replace")
    text = _INVALID_XML_CHARS.sub("", text)
    root = ET.fromstring(text)

    plugins: list[Plugin] = []
    for ui in root.iter("Ui"):
        uid = _text(ui, "UID")
        name = deep_unescape(_text(ui, "UIName"))
        if not uid or not name:
            continue  # skip malformed entries rather than failing the build
        plugins.append(Plugin(
            uid=uid,
            name=name,
            author=deep_unescape(_text(ui, "UIAuthorName")),
            version=deep_unescape(_text(ui, "UIVersion")),
            updated=_int(_text(ui, "UIUpdated")),
            downloads=_int(_text(ui, "UIDownloads")),
            category=deep_unescape(_text(ui, "UICategory")) or "Uncategorized",
            description=deep_unescape(_text(ui, "UIDescription")),
            file_name=_text(ui, "UIFile"),
            size=_int(_text(ui, "UISize")),
            file_url=_text(ui, "UIFileURL").replace("http://", "https://", 1),
        ))

    plugins.sort(key=lambda p: p.updated, reverse=True)
    return plugins


# --------------------------------------------------------------------------- #
# RSS generation
# --------------------------------------------------------------------------- #
def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "uncategorized"


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


def item_html(p: Plugin) -> str:
    """HTML body shown in Feeder. ElementTree escapes it on write."""
    desc = html.escape(p.description).replace("\n", "<br>")
    updated = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(p.updated))
    return (
        f"<p><b>Version:</b> {html.escape(p.version)}<br>"
        f"<b>Author:</b> {html.escape(p.author)}<br>"
        f"<b>Category:</b> {html.escape(p.category)}<br>"
        f"<b>Updated:</b> {updated}<br>"
        f"<b>Downloads:</b> {p.downloads:,}<br>"
        f"<b>File:</b> <a href=\"{html.escape(p.file_url)}\">"
        f"{html.escape(p.file_name)}</a> ({human_size(p.size)})</p>"
        f"<p>{desc}</p>"
    )


def build_rss(title: str, description: str, plugins: list[Plugin],
              self_url: str | None) -> bytes:
    ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = SITE_URL
    ET.SubElement(channel, "description").text = description
    ET.SubElement(channel, "language").text = "en"
    ET.SubElement(channel, "lastBuildDate").text = formatdate(usegmt=True)
    ET.SubElement(channel, "ttl").text = "180"
    if self_url:
        ET.SubElement(channel, "{http://www.w3.org/2005/Atom}link", {
            "href": self_url, "rel": "self", "type": "application/rss+xml",
        })

    for p in plugins:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"{p.name} ({p.version})"
        ET.SubElement(item, "link").text = INFO_URL.format(uid=p.uid)
        ET.SubElement(item, "description").text = item_html(p)
        ET.SubElement(item, "author").text = f"noreply@lotrointerface.com ({p.author})"
        ET.SubElement(item, "category").text = p.category
        # GUID includes version + timestamp, so every new release shows up
        # in Feeder as a new unread item instead of being treated as seen.
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = (
            f"lotrointerface-{p.uid}-{slugify(p.version)}-{p.updated}"
        )
        if p.updated:
            ET.SubElement(item, "pubDate").text = formatdate(p.updated, usegmt=True)

    ET.indent(rss)
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def build_index(feeds: list[tuple[str, str, int]], base_url: str) -> str:
    rows = "\n".join(
        f'<li><a href="{html.escape(path)}">{html.escape(label)}</a> '
        f'<span>{count} plugins</span><br>'
        f'<code>{html.escape(base_url + path)}</code></li>'
        for label, path, count in feeds
    )
    built = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LOTRO Plugin Feeds</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 16px;line-height:1.5}}
li{{margin:.6rem 0}} span{{color:#777;font-size:.9em}}
code{{font-size:.85em;word-break:break-all;background:#f2f2f2;padding:1px 4px}}
</style></head><body>
<h1>LOTRO Plugin Feeds</h1>
<p>RSS feeds generated from the LoTROInterface Plugin Compendium API.
Copy a link into Feeder. Last built: {built}.</p>
<ul>
{rows}
</ul></body></html>
"""


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="docs", help="output directory")
    parser.add_argument("--base-url", default="",
                        help="public URL of the output dir, e.g. https://user.github.io/repo/")
    parser.add_argument("--input", help="read a local XML file instead of the API")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/") + "/" if args.base_url else ""
    out = Path(args.out)

    try:
        raw = Path(args.input).read_bytes() if args.input else fetch_source(SOURCE_URL)
        plugins = parse_plugins(raw)
    except (RuntimeError, ET.ParseError, OSError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    if not args.input and len(plugins) < MIN_EXPECTED_PLUGINS:
        print(f"[error] only {len(plugins)} plugins parsed (expected "
              f">= {MIN_EXPECTED_PLUGINS}); keeping the previous feed.", file=sys.stderr)
        return 1

    (out / "categories").mkdir(parents=True, exist_ok=True)

    def write(rel_path: str, title: str, desc: str, items: list[Plugin]) -> None:
        self_url = base_url + rel_path if base_url else None
        (out / rel_path).write_bytes(build_rss(title, desc, items, self_url))

    feeds: list[tuple[str, str, int]] = []

    write("feed.xml", "LOTRO Plugins - All",
          "Every plugin in the LoTROInterface Plugin Compendium, newest update first.",
          plugins)
    feeds.append(("All plugins", "feed.xml", len(plugins)))

    latest = plugins[:LATEST_COUNT]
    write("latest.xml", f"LOTRO Plugins - Latest {LATEST_COUNT}",
          f"The {LATEST_COUNT} most recently updated LOTRO plugins.", latest)
    feeds.append((f"Latest {LATEST_COUNT} updates", "latest.xml", len(latest)))

    by_category: dict[str, list[Plugin]] = {}
    for p in plugins:
        by_category.setdefault(p.category, []).append(p)

    # Remove feeds for categories that no longer exist.
    wanted = {f"{slugify(c)}.xml" for c in by_category}
    for old in (out / "categories").glob("*.xml"):
        if old.name not in wanted:
            old.unlink()

    for category in sorted(by_category, key=str.lower):
        rel = f"categories/{slugify(category)}.xml"
        write(rel, f"LOTRO Plugins - {category}",
              f"LOTRO plugins in the '{category}' category.", by_category[category])
        feeds.append((category, rel, len(by_category[category])))

    (out / "index.html").write_text(build_index(feeds, base_url), encoding="utf-8")
    (out / ".nojekyll").touch()

    print(f"[ok] {len(plugins)} plugins, {len(by_category)} categories -> {out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
