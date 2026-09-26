#!/usr/bin/env python3
"""Generate assets/data.js (and download item images) from the wiki pages in wiki-source/.

Save or copy a page from https://abioticfactor.wiki.gg into wiki-source/ (the file name
does not matter - pages are recognised by their title), then run:

    python tools/build_data.py                   parse pages, download missing images, write data.js
    python tools/build_data.py --no-download     parse pages only (already downloaded images are kept)
    python tools/build_data.py --refresh-images  download every image again

Item ids are "<category>:<slug of the name>", so saved progress survives a rebuild
as long as an item keeps its name.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import struct
import sys
import time
import unicodedata
import zlib
from pathlib import Path
from urllib.parse import quote, unquote, urljoin

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "wiki-source"
ASSETS_DIR = ROOT / "assets"
IMG_DIR = ASSETS_DIR / "img"
DATA_JS = ASSETS_DIR / "data.js"
MANIFEST_PATH = IMG_DIR / "_manifest.json"

WIKI = "https://abioticfactor.wiki.gg"
SCHEMA = 1

# Images whose original is at most this big (longest side, px) are downloaded as-is,
# larger ones as a wiki thumbnail with this long side.
MAX_ORIGINAL_SIDE = 512
THUMB_LONG_SIDE = 320
REQUEST_DELAY = 0.3  # seconds between image requests - be polite to the wiki

CATEGORIES = [
    dict(id="achievements", page="Achievements", title="Achievements", code="ACH",
         view="list", kind="achievement", doneLabel="UNLOCKED", expected=53,
         chips=[("hidden", "Hidden"), ("not-hidden", "Not hidden"),
                ("skippable", "Skippable"), ("unskippable", "Unskippable")]),
    dict(id="collectibles", page="Collectibles", title="Collectibles", code="COL",
         view="grid", kind="curio", doneLabel="COLLECTED", tileAspect="1 / 1", expected=38,
         links=[("Collectibles Guide", WIKI + "/wiki/Collectibles_Guide")]),
    dict(id="photo-frames", page="Photo Frames", title="Photo Frames", code="PHO",
         view="grid", kind="curio", doneLabel="COLLECTED", tileAspect="5 / 6", expected=23),
    dict(id="wall-decorations", page="Wall Decorations", title="Wall Decorations", code="WAL",
         view="grid", kind="curio", doneLabel="COLLECTED", tileAspect="1 / 1", expected=51,
         chips=[("wall-art", "Wall Art"), ("decorations", "Decorations")]),
    dict(id="television", page="Television", title="Television", code="TV",
         view="list", kind="tv", doneLabel="FOUND", expected=11),
    dict(id="armor-sets", page="Armor Sets", title="Armor Sets", code="ARM",
         view="list", kind="armor", doneLabel="OBTAINED", expected=31,
         chips=[("upgradable", "Upgradable"), ("non-upgradable", "Non-upgradable")]),
    dict(id="lab-masks", page="Lab Mask", title="Lab Masks", code="MSK",
         view="list", kind="mask", doneLabel="OBTAINED", expected=9,
         supplement="lab-masks-locations.txt",
         noteHtml=("Masks spawn by chance &ndash; if one is missing, wait for the world and the portal "
                   "world to reset. Locations: Abiotic Factor Wiki and a Reddit community guide "
                   "(rewritten in our own words).")),
    dict(id="trinkets", page="Armor and Gear", section="Trinket", title="Trinkets", code="TRK",
         view="list", kind="gear", doneLabel="OBTAINED", expected=25),
    dict(id="full-body-suits", page="Armor and Gear", section="Full Body Suit", title="Full Body Suits",
         code="SUI", view="list", kind="gear", doneLabel="OBTAINED", expected=9),
    dict(id="backpacks", page="Armor and Gear", section="Backpack", title="Backpacks", code="BAG",
         view="list", kind="gear", doneLabel="OBTAINED", expected=19),
    dict(id="wristwatches", page="Armor and Gear", section="Wristwatch", title="Wristwatches", code="WAT",
         view="list", kind="gear", doneLabel="OBTAINED", expected=7),
    # one entry for the page itself plus one per page linked under "See Also"
    # (fetch them with: python tools/fetch_wiki_pages.py Antelight --see-also --dir wiki-source/antelights)
    dict(id="antelights", page="Antelight", see_also=True, title="Antelights", code="ANT",
         view="list", kind="variant", doneLabel="OBTAINED", expected=8,
         chips=[("wild", "Found in the world"), ("seed-only", "Seed only")],
         noteHtml=("Antelights are glowing plants from the Anteverse, used as decoration. Grow them from "
                   "their seeds &ndash; a planted Antelight can be harvested only once.")),
    dict(id="rare-fish", page="Fishing", anchor="List_of_Fish", title="Rare Fish", code="FSH",
         view="list", kind="fish", doneLabel="CAUGHT", expected=17,
         chips=[("night", "Night"), ("dawn", "Dawn"), ("noon", "Noon"), ("dusk", "Dusk"), ("any-time", "Any time")],
         noteHtml=("Rare variants give double the resources when butchered at a Chef&rsquo;s Counter. "
                   "Times on the watch: Night 9 PM&ndash;6 AM &middot; Dawn 6&ndash;11 AM &middot; "
                   "Noon 11 AM&ndash;4 PM &middot; Dusk 4&ndash;9 PM.")),
]

# Colour name and swatch (any CSS background) per variant page.
VARIANT_COLORS = {
    "Antelight": ("Purple", "#9b5de5"),
    "Blue Antelight": ("Blue", "#4aa3e0"),
    "Green Antelight": ("Green", "#5bbf6a"),
    "Orange Antelight": ("Orange", "#ff8a3d"),
    "Pink Antelight": ("Pink", "#f28bbd"),
    "Radiant Antelight": ("Radiant", "linear-gradient(90deg, #ff4d4d, #ffb000, #f2dc4b, #5bbf6a, #4aa3e0, #9b5de5)"),
    "Red Antelight": ("Red", "#e5484d"),
    "Digital Space Antelight": ("Digital Space",
                                "radial-gradient(circle at 30% 35%, #8fe9ff 0 12%, transparent 14%), "
                                "linear-gradient(135deg, #0b1a4a, #4a1a7a)"),
}

# Lab Mask colours (as named on the wiki page) and the swatch colour shown in the app.
LAB_MASK_COLORS = {
    "clear": "#cfe3ea", "red": "#e5484d", "pink": "#f28bbd", "yellow": "#f2dc4b", "orange": "#ff8a3d",
    "green": "#5bbf6a", "blue": "#4aa3e0", "purple": "#9b5de5", "black": "#151515",
}
# The wiki's Lab_mask_variants.png is an in-game screenshot of all nine masks on pedestals.
# Left to right: colour and the horizontal centre of the mask, in pixels of the 1691 px wide
# original. Each mask is cut out as a square of crop_size px, starting crop_top px from the top
# (both scaled when a smaller copy of the image is used).
LAB_MASK_IMAGE = [
    ("clear", 142), ("orange", 312), ("pink", 490), ("red", 677), ("blue", 845),
    ("purple", 1022), ("green", 1198), ("yellow", 1364), ("black", 1540),
]
LAB_MASK_IMAGE_REF = {"width": 1691, "crop_size": 160, "crop_top": 16}

# (category id, item name) -> reason. Excluded items are listed in data.js but not tracked.
EXCLUDE = {
    ("achievements", "Pure Science"): "PS5-only platinum trophy - cannot be earned on PC",
}
# (category id, item name) -> slug, for names that do not slugify well.
ID_OVERRIDES = {
    ("television", "???"): "unknown",
}
# (category id, section title as on the wiki) -> title shown in the app.
SECTION_TITLES = {
    ("wall-decorations", "Wall Decorations"): "Decorations",
}

WARNINGS: list[str] = []


class BuildError(Exception):
    pass


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"  WARNING: {msg}")


# --------------------------------------------------------------------------- text helpers

WS_RE = re.compile(r"[\s\u200b\ufeff]+")  # \s already covers U+00A0 (&nbsp;) for str patterns


def collapse_ws(s: str) -> str:
    return WS_RE.sub(" ", s).strip()


def text(el) -> str:
    return collapse_ws(el.get_text()) if el is not None else ""


def classes(el) -> list[str]:
    if not isinstance(el, Tag):
        return []
    return el.get("class") or []


def slugify(name: str) -> str:
    s = re.sub(r"['\u2019.]", "", name).replace("&", " and ")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def abs_url(href: str) -> str:
    return urljoin(WIKI + "/", href.strip())


def wiki_page_url(title: str) -> str:
    return f"{WIKI}/wiki/{quote(title.replace(' ', '_'))}"


def to_number(s: str):
    m = re.search(r"-?\d+(?:\.\d+)?", s or "")
    if not m:
        return None
    v = float(m.group())
    return int(v) if v.is_integer() else v


# --------------------------------------------------------------------------- HTML sanitising

def sanitize_node(node) -> str:
    """Return safe inline HTML: text, <a> (absolute https, new tab), <i>, <b>, <br>."""
    if isinstance(node, Comment):
        return ""
    if isinstance(node, NavigableString):
        return html.escape(str(node), quote=False)
    if not isinstance(node, Tag):
        return ""
    name, cls = node.name, classes(node)
    if name in ("script", "style", "img"):
        return ""
    if name == "sup" and "reference" in cls:
        return ""
    if "mw-cite-backlink" in cls or "cite-bracket" in cls or "mw-editsection" in cls:
        return ""
    if name == "br":
        return "<br>"
    inner = "".join(sanitize_node(c) for c in node.children)
    if name in ("i", "em"):
        return f"<i>{inner}</i>"
    if name in ("b", "strong"):
        return f"<b>{inner}</b>"
    if name == "a":
        href = node.get("href") or ""
        if not inner.strip():
            return inner  # e.g. a link that only wrapped an icon
        if not href or href.startswith("#") or "new" in cls or "action=edit" in href:
            return inner
        url = abs_url(href)
        if not url.startswith("https://"):
            return inner
        return (f'<a href="{html.escape(url, quote=True)}" target="_blank" '
                f'rel="noopener noreferrer">{inner}</a>')
    return inner  # unknown tag: keep its content only


def sanitize(el) -> str:
    if el is None:
        return ""
    return collapse_ws("".join(sanitize_node(c) for c in el.children))


def split_on_br(cell) -> list[str]:
    """Split a cell at <br> into sanitized pieces, dropping leading bullet characters."""
    groups, cur = [], []
    for child in cell.children:
        if isinstance(child, Tag) and child.name == "br":
            groups.append(cur)
            cur = []
        else:
            cur.append(child)
    groups.append(cur)
    out = []
    for nodes in groups:
        s = collapse_ws("".join(sanitize_node(n) for n in nodes))
        s = re.sub(r"^[\u2022\u00b7\u2013*-]\s*", "", s).strip()
        if s:
            out.append(s)
    return out


# --------------------------------------------------------------------------- page structure

def page_title(soup) -> str | None:
    h1 = soup.select_one("#firstHeading")
    if h1 and text(h1):
        return text(h1)
    a = soup.select_one(".printfooter a[href]")
    if a:
        m = re.search(r"/wiki/([^?#]+)", a["href"])
        if m:
            return unquote(m.group(1)).replace("_", " ")
    if soup.title and text(soup.title):
        return re.split(r"\s+[-|]\s+", text(soup.title))[0]
    return None


def page_revid(soup) -> int | None:
    a = soup.select_one('.printfooter a[href*="oldid="]')
    if a:
        m = re.search(r"oldid=(\d+)", a["href"])
        if m:
            return int(m.group(1))
    return None


def load_sources() -> dict:
    pages = {}
    files = sorted(p for p in SOURCE_DIR.rglob("*") if p.suffix.lower() in (".html", ".htm"))
    if not files:
        raise BuildError(f"no .html files found in {SOURCE_DIR}")
    for path in files:
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
        title = page_title(soup) or path.stem
        revid = page_revid(soup)
        key = title.lower()
        if key in pages:
            old = pages[key]
            if (revid or 0) <= (old["revid"] or 0):
                warn(f"{path.name} is another copy of '{title}' (not newer than {old['path'].name}) - ignored")
                continue
            warn(f"{path.name} replaces {old['path'].name} for '{title}' (newer revision)")
        pages[key] = dict(path=path, soup=soup, title=title, revid=revid)
    return pages


def content_root(soup) -> Tag:
    for sel in ("main #mw-content-text > .mw-parser-output",
                "#mw-content-text > .mw-parser-output",
                ".mw-parser-output"):
        el = soup.select_one(sel)
        if el is not None:
            return el
    raise BuildError("no .mw-parser-output element found")


def prune(root: Tag) -> None:
    for el in root.select("table.navbox, .navbox, #toc, .toc, .mw-editsection, script, style"):
        el.decompose()
    for c in root.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()


HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def heading_info(el):
    """(level, title, anchor) for a section heading, old or new MediaWiki markup, else None."""
    if not isinstance(el, Tag):
        return None
    h = None
    if el.name in HEADINGS:
        h = el
    elif el.name == "div" and "mw-heading" in classes(el):
        h = el.find(HEADINGS)
    if h is None:
        return None
    hl = h.select_one(".mw-headline")
    if hl is not None:
        return int(h.name[1]), text(hl), hl.get("id")
    return int(h.name[1]), text(h), h.get("id")


def child_tags(root: Tag):
    return [c for c in root.children if isinstance(c, Tag)]


def intro_html(root: Tag) -> str:
    parts = []
    for el in child_tags(root):
        if heading_info(el):
            break
        if el.name == "p" and "mw-empty-elt" not in classes(el):
            s = sanitize(el)
            if s:
                parts.append(s)
    return " ".join(parts)


def find_tables(el: Tag) -> list[Tag]:
    if el.name == "table":
        return [el] if "wikitable" in classes(el) else []
    return el.select("table.wikitable")


def table_rows(table: Tag):
    """(headers, rows): headers from the first all-<th> row, rows = lists of <td>/<th> cells."""
    headers, rows = None, []
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue  # row of a nested table
        cells = tr.find_all(["td", "th"], recursive=False)
        if not cells:
            continue
        if headers is None and all(c.name == "th" for c in cells):
            headers = [text(c).lower() for c in cells]
        elif any(c.name == "td" for c in cells):
            rows.append(cells)
    return headers or [], rows


def table_grid(table: Tag):
    """Like table_rows(), but rowspan/colspan cells are repeated so every row has all columns."""
    def span(c, attr):
        digits = re.sub(r"\D", "", c.get(attr) or "")
        return max(1, int(digits)) if digits else 1

    headers, rows, pending = None, [], {}  # pending: column -> [cell, rows still to fill]
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        cells = tr.find_all(["td", "th"], recursive=False)
        if not cells:
            continue
        if headers is None and all(c.name == "th" for c in cells):
            headers = [text(c).lower() for c in cells]
            continue
        out, colno, queue = {}, 0, list(cells)
        while queue or any(k >= colno for k in pending):
            if colno in pending:
                c, left = pending[colno]
                out[colno] = c
                if left <= 1:
                    del pending[colno]
                else:
                    pending[colno] = [c, left - 1]
                colno += 1
                continue
            if not queue:
                break
            c = queue.pop(0)
            rs = span(c, "rowspan")
            for _ in range(span(c, "colspan")):
                out[colno] = c
                if rs > 1:
                    pending[colno] = [c, rs - 1]
                colno += 1
        rows.append([out[k] for k in sorted(out)])
    return headers or [], rows


def col(headers: list[str], prefix: str) -> int | None:
    for i, h in enumerate(headers):
        if h.startswith(prefix):
            return i
    return None


def cell(cells, index):
    return cells[index] if index is not None and index < len(cells) else None


# --------------------------------------------------------------------------- images

THUMB_RE = re.compile(r"^(?P<prefix>.*/images)/thumb/(?P<file>[^?]+?)/(?P<w>\d+)px-[^/?]+(?P<query>\?.*)?$")


def image_candidates(img: Tag | None) -> list[str]:
    """Absolute URLs to try for an <img>, best first."""
    if img is None:
        return []
    src = img.get("src") or ""
    if src.startswith("data:"):
        src = img.get("data-src") or ""
    try:
        fw = int(img.get("data-file-width") or 0)
        fh = int(img.get("data-file-height") or 0)
    except ValueError:
        fw = fh = 0
    cands = []
    original = None
    m = THUMB_RE.match(src)
    if m:
        original = f"{m['prefix']}/{m['file']}{m['query'] or ''}"
    elif "/images/" in src:
        original = src
    long_side = max(fw, fh)
    if original and long_side and long_side <= MAX_ORIGINAL_SIDE:
        cands.append(original)
    elif m and long_side:
        w = THUMB_LONG_SIDE if fw >= fh else max(1, round(THUMB_LONG_SIDE * fw / fh))
        fname = m["file"].rsplit("/", 1)[-1]
        cands.append(f"{m['prefix']}/thumb/{m['file']}/{w}px-{fname}{m['query'] or ''}")
    srcset = []
    for part in (img.get("srcset") or "").split(","):
        bits = part.split()
        if not bits:
            continue
        mult = 1.0
        if len(bits) > 1 and bits[1].endswith("x"):
            try:
                mult = float(bits[1][:-1])
            except ValueError:
                pass
        srcset.append((mult, bits[0]))
    cands += [u for _, u in sorted(srcset, key=lambda e: -e[0])]
    if src:
        cands.append(src)
    if original:
        cands.append(original)
    out = []
    for u in cands:
        au = abs_url(u)
        if au not in out:
            out.append(au)
    return out


def sniff_ext(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


class ImageFetcher:
    def __init__(self, enabled: bool, refresh: bool):
        self.enabled = enabled
        self.refresh = refresh
        self.session = None
        self.blocked_in_a_row = 0
        self.stats = {}
        try:
            self.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.manifest = {}

    def _session(self):
        if self.session is None:
            import requests
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            s = requests.Session()
            s.headers.update({
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/128.0 Safari/537.36 "
                               "AbioticChecklistBuilder/1.0 (personal offline checklist)"),
                "Accept": "image/png,image/jpeg,image/gif;q=0.9,*/*;q=0.5",
                "Referer": WIKI + "/",
            })
            retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
                          allowed_methods=["GET"], respect_retry_after_header=True)
            s.mount("https://", HTTPAdapter(max_retries=retry))
            self.session = s
        return self.session

    def _count(self, cat_id: str, what: str) -> None:
        self.stats.setdefault(cat_id, {}).setdefault(what, 0)
        self.stats[cat_id][what] += 1

    def get(self, cat_id: str, slug: str, candidates: list[str]) -> str | None:
        """Return the image path relative to index.html, or None."""
        key = f"{cat_id}/{slug}"
        entry = self.manifest.get(key)
        have = entry is not None and (IMG_DIR / entry["file"]).is_file()
        if not candidates:
            self._count(cat_id, "missing")
            return None
        if have and entry.get("url") == candidates[0] and not self.refresh:
            self._count(cat_id, "cached")
            return "assets/img/" + entry["file"]
        if not self.enabled or self.blocked_in_a_row >= 3:
            self._count(cat_id, "kept" if have else "skipped")
            return "assets/img/" + entry["file"] if have else None
        import requests
        for url in candidates:
            try:
                r = self._session().get(url, timeout=20)
            except requests.RequestException as e:
                print(f"    {key}: {type(e).__name__} for {url}")
                continue
            finally:
                time.sleep(REQUEST_DELAY)
            ctype = r.headers.get("content-type", "")
            ext = sniff_ext(r.content) if r.status_code == 200 else None
            if ext is None:
                blocked = r.status_code in (403, 503) or "cf-mitigated" in r.headers or "html" in ctype
                self.blocked_in_a_row = self.blocked_in_a_row + 1 if blocked else 0
                print(f"    {key}: HTTP {r.status_code} ({ctype or 'no content-type'}) for {url}")
                if self.blocked_in_a_row >= 3:
                    warn("the wiki keeps refusing image requests - stopped downloading. "
                         "The app will load missing images online; run the script again later.")
                    break
                continue
            self.blocked_in_a_row = 0
            rel = f"{cat_id}/{slug}.{ext}"
            dest = IMG_DIR / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            tmp.write_bytes(r.content)
            os.replace(tmp, dest)
            for other in dest.parent.glob(f"{slug}.*"):
                if other != dest and other.suffix.lower() in (".png", ".jpg", ".gif", ".webp"):
                    other.unlink()
            self.manifest[key] = {"url": candidates[0], "from": url, "file": rel, "bytes": len(r.content)}
            self._count(cat_id, "downloaded")
            return "assets/img/" + rel
        self._count(cat_id, "kept" if have else "failed")
        return "assets/img/" + entry["file"] if have else None

    def save_manifest(self) -> None:
        IMG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = MANIFEST_PATH.with_name(MANIFEST_PATH.name + ".part")
        tmp.write_text(json.dumps(self.manifest, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, MANIFEST_PATH)


# --------------------------------------------------------------------------- minimal PNG cropping
# Just enough PNG support (standard library only) to cut images out of a larger picture.

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_decode(data: bytes):
    """Decode an 8-bit, non-interlaced PNG. Returns (width, height, channels, rows) with RGB/RGBA rows."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG file")
    pos, idat, palette, trns, header = 8, [], None, None, None
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            header = struct.unpack(">IIBBBBB", chunk)
        elif ctype == b"PLTE":
            palette = chunk
        elif ctype == b"tRNS":
            trns = chunk
        elif ctype == b"IDAT":
            idat.append(chunk)
        elif ctype == b"IEND":
            break
    if header is None:
        raise ValueError("PNG without header")
    width, height, depth, color, _, _, interlace = header
    if depth != 8 or interlace or color not in (0, 2, 3, 4, 6):
        raise ValueError(f"unsupported PNG (bit depth {depth}, colour type {color}, interlace {interlace})")
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    stride = width * bpp
    raw = zlib.decompress(b"".join(idat))
    rows, prev, i = [], bytearray(stride), 0
    for _ in range(height):
        ftype = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        if ftype == 1:  # Sub
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 0xFF
        elif ftype == 2:  # Up
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif ftype == 3:  # Average
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
        elif ftype != 0:
            raise ValueError(f"invalid PNG filter type {ftype}")
        rows.append(line)
        prev = line
    if color in (2, 6):
        return width, height, bpp, rows
    if color == 3:
        if palette is None:
            raise ValueError("palette PNG without palette")
        channels = 4 if trns else 3
        out = []
        for line in rows:
            o = bytearray()
            for idx in line:
                o += palette[idx * 3:idx * 3 + 3]
                if trns:
                    o.append(trns[idx] if idx < len(trns) else 255)
            out.append(o)
        return width, height, channels, out
    channels = 4 if color == 4 else 3  # grey or grey + alpha
    out = []
    for line in rows:
        o = bytearray()
        for x in range(0, len(line), bpp):
            o += bytes((line[x], line[x], line[x]))
            if color == 4:
                o.append(line[x + 1])
        out.append(o)
    return width, height, channels, out


def png_encode(width: int, height: int, channels: int, rows) -> bytes:
    """Encode RGB (3 channels) or RGBA (4 channels) rows as a PNG, using the Sub filter."""
    body = bytearray()
    for line in rows:
        body.append(1)
        sub = bytearray(line)
        for x in range(len(line) - 1, channels - 1, -1):
            sub[x] = (line[x] - line[x - channels]) & 0xFF
        body += sub

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6 if channels == 4 else 2, 0, 0, 0)
    return (PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(body), 9))
            + chunk(b"IEND", b""))


# --------------------------------------------------------------------------- extractors
# Each extractor returns (items, sections). Items are dicts with at least "name" and
# "_img" (the <img> tag, or None); ids, tags and image paths are added later.

def extract_achievements(root: Tag):
    notes = {}
    for li in root.select("ol.references > li[id]"):
        notes[li["id"]] = sanitize(li.select_one(".reference-text"))
    table = None
    for t in root.select("table.wikitable"):
        headers, rows = table_rows(t)
        if col(headers, "name") is not None and col(headers, "requirement") is not None:
            table = (headers, rows)
            break
    if table is None:
        raise BuildError("no table with 'Name' and 'Requirements' columns")
    headers, rows = table
    ci = {k: col(headers, k) for k in ("image", "name", "description", "requirement", "type", "gamerscore")}
    items = []
    for cells in rows:
        raw_name = text(cell(cells, ci["name"]))
        m = re.match(r"^(.*?)\s*\(\s*hidden\s*\)\s*$", raw_name, re.I)
        name = m.group(1) if m else raw_name
        type_cell = cell(cells, ci["type"])
        note_ids = []
        if type_cell is not None:
            note_ids = [a["href"][1:] for a in type_cell.select('sup.reference a[href^="#"]')]
            for sup in type_cell.select("sup.reference"):
                sup.decompose()
        score = text(cell(cells, ci["gamerscore"]))
        gs = re.search(r"(\d+)\s*g", score, re.I)
        trophy = re.search(r"bronze|silver|gold|platinum", score, re.I)
        req_html = sanitize(cell(cells, ci["requirement"]))
        img_cell = cell(cells, ci["image"])
        items.append(dict(
            name=name,
            _img=img_cell.find("img") if img_cell is not None else None,
            hidden=bool(m),
            descHtml=sanitize(cell(cells, ci["description"])),
            reqHtml=req_html,
            type=text(type_cell),
            gamerscore=int(gs.group(1)) if gs else None,
            trophy=trophy.group().capitalize() if trophy else None,
            notesHtml=[notes[n] for n in note_ids if notes.get(n)],
        ))
    return items, []


def extract_collectibles(root: Tag):
    items = []
    for entry in root.select(".af-item-grid > .af-item-grid__entry"):
        img = entry.select_one(".af-item-slot__image img") or entry.find("img")
        caption = None
        for a in entry.find_all("a", href=True):
            if a.find("img") is None:
                caption = a
        if caption is not None:
            name = text(caption)
        else:  # the alt text is double-escaped on the wiki ("Hasta Tria&amp;#39;s")
            name = collapse_ws(html.unescape(html.unescape(img.get("alt", "")))) if img else ""
        items.append(dict(name=name, _img=img, wiki=abs_url(caption["href"]) if caption else None))
    return items, []


def extract_gallery(root: Tag):
    """Photo Frames / Wall Decorations: <h2> sections, each followed by a ul.gallery."""
    items, sections, section = [], [], None
    for el in child_tags(root):
        hi = heading_info(el)
        if hi:
            if hi[0] == 2:
                section = re.sub(r"^list of\s+", "", hi[1], flags=re.I)
            continue
        galleries = [el] if el.name == "ul" and "gallery" in classes(el) else el.select("ul.gallery")
        for gal in galleries:
            if section is not None and section not in sections:
                sections.append(section)
            for li in gal.find_all("li", recursive=False):
                if "gallerybox" not in classes(li):
                    continue
                img = li.select_one(".thumb img") or li.find("img")
                cap = li.select_one(".gallerytext")
                name = text(cap) or (collapse_ws(html.unescape(img.get("alt", ""))) if img else "")
                a = cap.find("a", href=True) if cap is not None else None
                items.append(dict(name=name, _img=img, _section=section,
                                  wiki=abs_url(a["href"]) if a else None))
    return items, sections


def extract_television(root: Tag, page_url: str):
    icon = root.select_one("aside.portable-infobox img")
    items, in_locations, cur = [], False, None
    for el in child_tags(root):
        hi = heading_info(el)
        if hi:
            level, title, anchor = hi
            if level == 2:
                in_locations = title.lower().startswith("location")
                cur = None
            elif level == 3 and in_locations:
                cur = dict(name=re.sub(r"^TV:\s*", "", title, count=1), _img=icon, _shared_img="_icon",
                           wiki=f"{page_url}#{quote(anchor, safe=':_.-!,()*')}" if anchor else page_url,
                           detailsHtml=[])
                items.append(cur)
            continue
        if in_locations and cur is not None and el.name == "p" and "mw-empty-elt" not in classes(el):
            s = sanitize(el)
            if s:
                cur["detailsHtml"].append(s)
    m = re.search(r"total of (\d+) different TVs", text(root), re.I)
    if m and int(m.group(1)) != len(items):
        warn(f"Television: page says {m.group(1)} TVs, found {len(items)}")
    return items, []


def extract_armor(root: Tag):
    items, sections = [], []
    group = family = None
    for el in child_tags(root):
        hi = heading_info(el)
        if hi:
            level, title, _ = hi
            if level == 3:
                group, family = title, None
            elif level == 4:
                family = title
            continue
        for t in find_tables(el):
            headers, rows = table_rows(t)
            ci = {k: col(headers, k) for k in ("armor set", "total armor", "total weight", "total bonus")}
            if ci["armor set"] is None:
                continue
            section = family or group or "Armor Sets"
            if section not in sections:
                sections.append(section)
            last_armor = None
            for i, cells in enumerate(rows, 1):
                name_cell = cell(cells, ci["armor set"])
                a = name_cell.find("a", href=True)
                img = name_cell.find("img")
                armor = to_number(text(cell(cells, ci["total armor"])))
                if family and last_armor is not None and armor is not None and armor <= last_armor:
                    warn(f"Armor Sets: '{text(a)}' does not have more armor than the previous tier "
                         f"of {family} - is the table sorted?")
                last_armor = armor
                bonus_cell = cell(cells, ci["total bonus"])
                items.append(dict(
                    name=text(a) if a else text(name_cell),
                    _img=img, _section=section,
                    _tag=slugify(group) if group else None,
                    wiki=abs_url(a["href"]) if a else None,
                    piece=collapse_ws(img.get("alt", "")) if img else None,
                    armor=armor,
                    weight=to_number(text(cell(cells, ci["total weight"]))),
                    tier=i if family else None,
                    tierCount=len(rows) if family else None,
                    bonusesHtml=split_on_br(bonus_cell) if bonus_cell is not None else [],
                ))
    return items, sections


def extract_item_table(root: Tag, section: str):
    """Items of one table under a section heading (e.g. h3 "Backpack" on the Armor and Gear page).

    Columns are mapped by their header: Image, Name and Description are special; every other
    column (Weight, Slots, Cold Resist, ...) becomes a stat shown with the item.
    """
    table, in_section = None, False
    for el in child_tags(root):
        hi = heading_info(el)
        if hi:
            if in_section:
                break
            in_section = hi[1].lower() == section.lower()
            continue
        if in_section:
            found = [el] if el.name == "table" else el.select("table")
            if found:
                table = found[0]
                break
    if table is None:
        raise BuildError(f"no table found under the heading '{section}'")
    headers, rows = table_rows(table)
    ci = {k: col(headers, k) for k in ("image", "name", "description")}
    if ci["name"] is None:
        raise BuildError(f"the table under '{section}' has no 'Name' column")
    stat_cols = [(i, h.title()) for i, h in enumerate(headers) if i not in ci.values()]
    items = []
    for cells in rows:
        name_cell = cell(cells, ci["name"])
        link = name_cell.find("a", href=True) if name_cell is not None else None
        img_cell = cell(cells, ci["image"])
        stats = []
        for i, label in stat_cols:
            value = text(cell(cells, i))
            if value:
                stats.append({"label": label, "value": value})
        items.append(dict(
            name=text(name_cell),
            _img=img_cell.find("img") if img_cell is not None else None,
            wiki=abs_url(link["href"]) if link else None,
            stats=stats,
            descHtml=sanitize(cell(cells, ci["description"])),
        ))
    return items, []


FISH_TIMES = ("night", "dawn", "noon", "dusk")


def extract_fish(root: Tag):
    """Rare fish from the "List of Fish" table: Common | Rare | Location(s) | Best Time(s) | Products."""
    table = None
    for t in root.select("table"):
        headers, rows = table_grid(t)
        if col(headers, "rare") is not None and col(headers, "common") is not None:
            table = (headers, rows)
            break
    if table is None:
        raise BuildError("no table with 'Common' and 'Rare' columns")
    headers, rows = table
    ci = {k: col(headers, k) for k in ("common", "rare", "location", "best time", "products")}
    items = []
    for cells in rows:
        rare = cell(cells, ci["rare"])
        link = next((a for a in rare.find_all("a", href=True) if text(a)), None) if rare is not None else None
        if link is None:
            continue  # "N/A": this fish has no rare variant
        common = cell(cells, ci["common"])
        common_link = next((a for a in common.find_all("a", href=True) if text(a)), None) if common is not None else None
        time_text = text(cell(cells, ci["best time"]))
        times = [t for t in FISH_TIMES if re.search(rf"\b{t}\b", time_text, re.I)]
        lines = []
        if common_link is not None:
            lines.append({"label": "Rare variant of", "html": collapse_ws(sanitize_node(common_link))})
        for label, key in (("Where", "location"), ("Yields", "products")):
            c = cell(cells, ci[key])
            if c is not None and text(c).upper() not in ("", "N/A"):
                lines.append({"label": label, "html": sanitize(c)})
        items.append(dict(
            name=text(link),
            _img=rare.find("img"),
            _tag=times or ["any-time"],
            wiki=abs_url(link["href"]),
            stats=[{"label": "Best Time", "value": time_text}] if times else [],
            lines=lines,
        ))
    return items, []


def see_also_titles(root: Tag) -> list[str]:
    """Titles of the wiki pages linked in a page's "See Also" section."""
    titles, in_section = [], False
    for el in child_tags(root):
        hi = heading_info(el)
        if hi:
            in_section = hi[1].lower() == "see also"
            continue
        if not in_section:
            continue
        for a in el.find_all("a", href=True):
            m = re.match(r"^(?:https?://abioticfactor\.wiki\.gg)?/wiki/([^?#]+)$", a["href"])
            if m and ":" not in m.group(1):
                title = unquote(m.group(1)).replace("_", " ")
                if title not in titles:
                    titles.append(title)
    return titles


def variant_item(page: dict) -> dict:
    """One checklist entry from a single item page (infobox, Sources, Locations)."""
    root = content_root(page["soup"])
    prune(root)
    info = root.select_one("aside.portable-infobox")
    desc = info.select_one('[data-source="description"] .pi-data-value') if info else None
    sources, locations = [], []
    section = area = None
    for el in child_tags(root):
        hi = heading_info(el)
        if hi:
            if hi[0] == 2:
                section, area = hi[1].lower(), None
            elif hi[0] == 3:
                area = sanitize(el.select_one(".mw-headline") or el)
            continue
        if section == "sources" and el.name == "p":
            s = sanitize(el)
            if s:
                sources.append(s)
        elif section == "locations" and el.name in ("ul", "ol"):
            for li in el.find_all("li", recursive=False):
                s = sanitize(li)
                if s:
                    locations.append(f"<b>{area}:</b> {s}" if area else s)
    title = page["title"]
    color, swatch = VARIANT_COLORS.get(title, (None, None))
    if color is None:
        warn(f"{title}: no colour in VARIANT_COLORS - add one for its swatch")
        color = re.sub(r"\s*Antelight$", "", title) or title
    seed_only = bool(re.search(r"can only be obtained through planting", " ".join(sources), re.I))
    return dict(
        name=title,
        _img=info.select_one("img") if info else None,
        _tag="seed-only" if seed_only else "wild",
        wiki=wiki_page_url(title),
        color=color,
        swatch=swatch,
        descHtml=sanitize(desc),
        detailsHtml=sources,
        locationsHtml=locations,
    )


def extract_variant_pages(root: Tag, base: dict, pages: dict):
    """The base page plus every page it lists under "See Also" (e.g. all Antelight colours)."""
    items, used = [variant_item(base)], []
    for title in see_also_titles(root):
        page = pages.get(title.lower())
        if page is None:
            warn(f"'{title}' is listed under See Also but not in wiki-source - fetch it with: "
                 f'python tools/fetch_wiki_pages.py "{title}" --dir wiki-source/antelights')
            continue
        items.append(variant_item(page))
        used.append(page)
    return items, [], used


MASK_LINE_RE = re.compile(r"^([A-Za-z]+)\s*[-\u2013\u2014:]\s*(.+)$")


def parse_mask_supplement(path: Path) -> dict | None:
    """Read a community guide like wiki-source/labmask_reddit.txt.

    Format: an area line (short, e.g. "Reactors/ Dusk Reactor") followed by lines
    "<Colour>- <where to find it>". Longer paragraphs (intro, outro) are ignored.
    """
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return None
    result = {"order": [], "area": {}, "text": {}}
    area = None
    for line in lines:
        s = collapse_ws(line)
        if not s:
            continue
        m = MASK_LINE_RE.match(s)
        if m and m.group(1).lower() in LAB_MASK_COLORS:
            color = m.group(1).lower()
            if color in result["text"]:
                warn(f"{path.name}: '{m.group(1)}' is listed twice - keeping the first entry")
                continue
            result["order"].append(color)
            result["text"][color] = m.group(2)
            if area:
                result["area"][color] = area
        elif len(s) <= 60:
            area = re.sub(r"\s*/\s*", " / ", s)
    return result


def lab_mask_images(cid: str, root: Tag, fetcher: ImageFetcher) -> dict:
    """Cut the nine masks out of the wiki's group screenshot. Returns {colour: image path}."""
    source = None
    for img in root.select("ul.gallery img"):
        if "variants" in (img.get("src") or "").lower() or "colors" in (img.get("alt") or "").lower():
            source = img
            break
    if source is None:
        warn("Lab Masks: the picture with all mask colours was not found on the page")
        return {}
    # prefer the largest copy offered by the page (not a synthesized small thumbnail)
    cands = [u for u in image_candidates(source) if f"/{THUMB_LONG_SIDE}px-" not in u]
    path = fetcher.get(cid, "_variants", cands)
    if not path:
        warn("Lab Masks: could not download the picture with all mask colours")
        return {}
    files = {color: f"{cid}/{color}-lab-mask.png" for color, _ in LAB_MASK_IMAGE}
    signature = json.loads(json.dumps({
        "source": fetcher.manifest.get(f"{cid}/_variants", {}).get("from"),
        "bytes": (ROOT / path).stat().st_size,
        "layout": LAB_MASK_IMAGE,
        "ref": LAB_MASK_IMAGE_REF,
    }))
    key = f"{cid}/_crops"
    entry = fetcher.manifest.get(key)
    if (entry and entry.get("signature") == signature and not fetcher.refresh
            and all((IMG_DIR / f).is_file() for f in files.values())):
        for _ in files:
            fetcher._count(cid, "cached")
        return {c: "assets/img/" + f for c, f in files.items()}
    try:
        width, height, channels, rows = png_decode((ROOT / path).read_bytes())
    except (ValueError, zlib.error, struct.error) as e:
        warn(f"Lab Masks: cannot cut the mask pictures ({e}) - using the normal Lab Mask icon")
        return {}
    scale = width / LAB_MASK_IMAGE_REF["width"]
    size = min(round(LAB_MASK_IMAGE_REF["crop_size"] * scale), width, height)
    top = max(0, min(height - size, round(LAB_MASK_IMAGE_REF["crop_top"] * scale)))
    for color, cx in LAB_MASK_IMAGE:
        x0 = max(0, min(width - size, round(cx * scale) - size // 2))
        crop = [rows[y][x0 * channels:(x0 + size) * channels] for y in range(top, top + size)]
        dest = IMG_DIR / files[color]
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(png_encode(size, size, channels, crop))
        os.replace(tmp, dest)
        fetcher._count(cid, "cropped")
    fetcher.manifest[key] = {"signature": signature, "files": files}
    print(f"    {cid}: cut {len(files)} mask pictures ({size}x{size} px) - check that each colour matches its name")
    return {c: "assets/img/" + f for c, f in files.items()}


def extract_lab_masks(root: Tag, page_url: str, cfg: dict, fetcher: ImageFetcher):
    """One entry per Lab Mask colour: wiki locations + optional community guide + cut-out pictures."""
    cid = cfg["id"]
    colors = list(LAB_MASK_COLORS)

    m = re.search(r"colou?rs are (.+?)\.", text(root), re.I)
    if m:
        named = [c.strip().lower() for c in re.split(r",|\band\b", m.group(1)) if c.strip()]
        if sorted(named) != sorted(colors):
            warn(f"Lab Masks: the wiki lists the colours {', '.join(named)} - update LAB_MASK_COLORS")
    else:
        warn("Lab Masks: the sentence listing the mask colours was not found")

    # "Locations": h3 per area, list items; "A unique <colour> Lab Mask ..." belongs to that colour.
    wiki = {c: [] for c in colors}
    common_areas = []
    in_locations, area_html = False, None
    for el in child_tags(root):
        hi = heading_info(el)
        if hi:
            if hi[0] == 2:
                in_locations, area_html = hi[1].lower().startswith("location"), None
            elif hi[0] == 3 and in_locations:
                area_html = sanitize(el.select_one(".mw-headline") or el)
            continue
        if not in_locations or el.name not in ("ul", "ol"):
            continue
        for li in el.find_all("li", recursive=False):
            unique = re.search(r"\bunique\s+(\w+)\s+lab\s+mask", text(li), re.I)
            if unique and unique.group(1).lower() in wiki:
                wiki[unique.group(1).lower()].append(sanitize(li))
            elif area_html and area_html not in common_areas:
                common_areas.append(area_html)
    if common_areas:
        listed = ", ".join(common_areas[:-1]) + (" and " if len(common_areas) > 1 else "") + common_areas[-1]
        wiki["clear"].append(f"The common clear mask is also found in {listed}.")

    guide = parse_mask_supplement(SOURCE_DIR / cfg["supplement"]) if cfg.get("supplement") else None
    if guide is None:
        if cfg.get("supplement"):
            warn(f"Lab Masks: {cfg['supplement']} not found in wiki-source - only wiki locations are shown")
        guide = {"order": [], "area": {}, "text": {}}
    order = guide["order"] + [c for c in colors if c not in guide["order"]]

    pictures = lab_mask_images(cid, root, fetcher)
    icon = root.select_one("aside.portable-infobox img")
    icon_cands = image_candidates(icon)
    if not pictures:
        icon_path = fetcher.get(cid, "_icon", icon_cands)
        pictures = {c: icon_path for c in colors}

    items, sections = [], []
    for color in order:
        area = guide["area"].get(color)
        if area and area not in sections:
            sections.append(area)
        details = wiki[color]
        community = [html.escape(guide["text"][color], quote=False)] if color in guide["text"] else []
        if not details and not community:
            warn(f"Lab Masks: no location known for the {color} mask")
        items.append(dict(
            name=f"{color.capitalize()} Lab Mask",
            _section=area,
            _tag="common" if color == "clear" else "unique",
            _img_path=pictures.get(color),
            _img_remote=icon_cands[0] if icon_cands else None,
            wiki=f"{page_url}#Locations",
            color=color.capitalize(),
            swatch=LAB_MASK_COLORS[color],
            area=area,
            detailsHtml=details,
            communityHtml=community,
        ))
    return items, sections


# --------------------------------------------------------------------------- build

def check_slugify() -> None:
    cases = {
        "Office: Managed": "office-managed",
        "One Down, One Million To Go": "one-down-one-million-to-go",
        "Je Suis Perdu!": "je-suis-perdu",
        "We Don't Talk About That Place": "we-dont-talk-about-that-place",
        "Hasta Tria's Left Boot": "hasta-trias-left-boot",
        "F.O.R.G.E. Armor Set": "forge-armor-set",
        "Dog Photo Frame #2": "dog-photo-frame-2",
        "IS-0023 Figurine": "is-0023-figurine",
        "Trams, Trams, Trams!": "trams-trams-trams",
    }
    for name, expected in cases.items():
        got = slugify(name)
        if got != expected:
            raise BuildError(f"slugify({name!r}) = {got!r}, expected {expected!r}")


def build_category(cfg: dict, page: dict, fetcher: ImageFetcher, pages: dict) -> tuple[dict, list, list]:
    """Returns (category, excluded items, further wiki pages used besides `page`)."""
    cid = cfg["id"]
    soup = page["soup"]
    root = content_root(soup)
    prune(root)
    page_url = wiki_page_url(page["title"])
    kind = cfg["kind"]
    extra_pages = []
    if kind == "variant":
        raw, sections, extra_pages = extract_variant_pages(root, page, pages)
    elif kind == "achievement":
        raw, sections = extract_achievements(root)
    elif kind == "tv":
        raw, sections = extract_television(root, page_url)
    elif kind == "armor":
        raw, sections = extract_armor(root)
    elif kind == "mask":
        raw, sections = extract_lab_masks(root, page_url, cfg, fetcher)
    elif kind == "gear":
        raw, sections = extract_item_table(root, cfg["section"])
    elif kind == "fish":
        raw, sections = extract_fish(root)
    elif cid == "collectibles":
        raw, sections = extract_collectibles(root)
    else:
        raw, sections = extract_gallery(root)

    if len(sections) <= 1:
        sections = []  # a single section adds nothing
    section_ids = {s: slugify(SECTION_TITLES.get((cid, s), s)) for s in sections}

    items, excluded, seen = [], [], {}
    for r in raw:
        name = r["name"]
        if not name:
            warn(f"{cfg['title']}: skipped an entry without a name")
            continue
        reason = EXCLUDE.get((cid, name))
        slug = ID_OVERRIDES.get((cid, name)) or slugify(name)
        if not slug:
            slug = "x" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
            warn(f"{cfg['title']}: '{name}' has no letters or digits - using id {slug}; "
                 f"add it to ID_OVERRIDES for a readable id")
        item_id = f"{cid}:{slug}"
        if reason:
            excluded.append(dict(id=item_id, category=cid, name=name, reason=reason))
            continue
        if item_id in seen:
            raise BuildError(f"{cfg['title']}: '{name}' and '{seen[item_id]}' both get the id {item_id} - "
                             f"add one of them to ID_OVERRIDES")
        seen[item_id] = name

        if "_img_path" in r:  # picture prepared by the extractor (e.g. cut out of a larger one)
            img, img_remote = r["_img_path"], r.get("_img_remote")
        else:
            cands = image_candidates(r.get("_img"))
            img = fetcher.get(cid, r.get("_shared_img") or slug, cands)
            img_remote = cands[0] if cands else None
        item = dict(
            id=item_id,
            name=name,
            img=img,
            imgRemote=img_remote,
            wiki=r.get("wiki"),
            section=section_ids.get(r.get("_section")) if sections else None,
            tags=[],
        )
        if kind == "achievement":
            item["tags"] = ["hidden" if r["hidden"] else "not-hidden"]
            if r["type"].lower() in ("skippable", "unskippable"):
                item["tags"].append(r["type"].lower())
            if re.search(r"\b(PS5|PlayStation|Xbox)\s+only\b", r["reqHtml"], re.I):
                warn(f"Achievements: '{name}' looks console-only - consider adding it to EXCLUDE")
        elif r.get("_tag"):
            item["tags"] = list(r["_tag"]) if isinstance(r["_tag"], list) else [r["_tag"]]
        elif item["section"]:
            item["tags"] = [item["section"]]
        for k, v in r.items():
            if not k.startswith("_") and k not in item and k != "wiki":
                item[k] = v
        items.append(item)

    if len(items) != cfg["expected"]:
        warn(f"{cfg['title']}: found {len(items)} items, expected {cfg['expected']} "
             f"(fine if the wiki changed - update 'expected' in CATEGORIES)")

    category = dict(
        id=cid,
        title=cfg["title"],
        code=cfg["code"],
        view=cfg["view"],
        kind=kind,
        doneLabel=cfg["doneLabel"],
        tileAspect=cfg.get("tileAspect"),
        # one section of a larger page: link its anchor, skip the page's general intro
        wikiUrl=(f"{page_url}#{quote(cfg.get('anchor') or cfg['section'].replace(' ', '_'))}"
                 if cfg.get("anchor") or cfg.get("section") else page_url),
        introHtml="" if cfg.get("section") or cfg.get("see_also") else intro_html(root),
        noteHtml=cfg.get("noteHtml"),
        links=[dict(label=l, url=u) for l, u in cfg.get("links", [])],
        sections=[dict(id=section_ids[s], title=SECTION_TITLES.get((cid, s), s)) for s in sections],
        chips=[dict(tag=t, label=l) for t, l in cfg.get("chips", [])],
        items=items,
    )
    return category, excluded, extra_pages


def validate(categories: list[dict]) -> None:
    for cat in categories:
        known_tags = {c["tag"] for c in cat["chips"]}
        for it in cat["items"]:
            for key, val in it.items():
                if key.endswith("Html"):
                    for s in (val if isinstance(val, list) else [val]):
                        if 'href="/' in s or "<img" in s or "cite_note" in s:
                            warn(f"{it['id']}: suspicious HTML left in {key}: {s[:80]}")
            if cat["view"] == "grid" and not it.get("wiki"):
                warn(f"{it['id']}: no wiki link")
            if cat["chips"] and not set(it["tags"]) & known_tags:
                warn(f"{it['id']}: matches none of the filter chips")


def write_data_js(payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=True, indent=1)
    js = (f"/* Generated by tools/build_data.py on {payload['generatedAt']} - do not edit by hand.\n"
          f"   Text adapted from the Abiotic Factor Wiki ({WIKI}) by its contributors,\n"
          f"   licensed under CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/).\n"
          f"   Game images are (c) Deep Field Games. See CREDITS.md. */\n"
          f"window.AF_DATA = {body};\n")
    tmp = DATA_JS.with_name(DATA_JS.name + ".part")
    tmp.write_text(js, encoding="utf-8", newline="\n")
    os.replace(tmp, DATA_JS)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-download", action="store_true", help="do not download images")
    ap.add_argument("--refresh-images", action="store_true", help="download all images again")
    args = ap.parse_args()

    try:
        check_slugify()
        print(f"Reading wiki pages from {SOURCE_DIR}")
        pages = load_sources()
        fetcher = ImageFetcher(enabled=not args.no_download, refresh=args.refresh_images)
        categories, excluded, sources, used_extra = [], [], {}, set()
        for cfg in CATEGORIES:
            page = pages.get(cfg["page"].lower())
            if page is None:
                raise BuildError(f"page '{cfg['page']}' not found in {SOURCE_DIR} "
                                 f"(found: {', '.join(p['title'] for p in pages.values())})")
            print(f"- {cfg['title']}  ({page['path'].name}, revision {page['revid']})")
            try:
                cat, exc, extra = build_category(cfg, page, fetcher, pages)
            except BuildError as e:
                raise BuildError(f"{cfg['title']}: {e}") from None
            categories.append(cat)
            excluded += exc
            sources[cfg["id"]] = dict(page=page["title"], file=page["path"].name,
                                      revid=page["revid"], url=wiki_page_url(page["title"]))
            if extra:
                sources[cfg["id"]]["also"] = [dict(page=p["title"], file=p["path"].name, revid=p["revid"],
                                                   url=wiki_page_url(p["title"])) for p in extra]
                used_extra.update(p["title"].lower() for p in extra)
        known = {c["page"].lower() for c in CATEGORIES} | used_extra
        for key, page in pages.items():
            if key not in known:
                warn(f"{page['path'].name} ('{page['title']}') is not used - add it to CATEGORIES to show it")
        fetcher.save_manifest()
        validate(categories)
    except BuildError as e:
        print(f"\nERROR: {e}")
        return 1

    payload = dict(
        schema=SCHEMA,
        generatedAt=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        wikiBase=WIKI,
        sources=sources,
        excluded=excluded,
        categories=categories,
    )
    write_data_js(payload)

    print("\nCategory            Items  Expected  Images (local/online-only)")
    total = 0
    for cfg, cat in zip(CATEGORIES, categories):
        n = len(cat["items"])
        total += n
        local = sum(1 for it in cat["items"] if it["img"])
        st = fetcher.stats.get(cat["id"], {})
        detail = ", ".join(f"{k} {v}" for k, v in sorted(st.items()))
        print(f"{cat['title']:<19} {n:>5}  {cfg['expected']:>8}  {local}/{n - local}   ({detail})")
    print(f"{'Total':<19} {total:>5}")
    if excluded:
        print("Excluded: " + "; ".join(f"{e['name']} ({e['reason']})" for e in excluded))
    size = sum(p.stat().st_size for p in IMG_DIR.rglob("*") if p.is_file() and p.suffix != ".json")
    print(f"Images on disk: {size / 1024 / 1024:.1f} MB")
    print(f"Wrote {DATA_JS.relative_to(ROOT)} ({DATA_JS.stat().st_size / 1024:.0f} KB)"
          + (f" with {len(WARNINGS)} warning(s)" if WARNINGS else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
