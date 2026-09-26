#!/usr/bin/env python3
"""Download pages from the Abiotic Factor Wiki into wiki-source/ for tools/build_data.py.

Instead of copying a page's HTML by hand, run for example:

    python tools/fetch_wiki_pages.py "Lab Mask"
    python tools/fetch_wiki_pages.py Antelight --see-also --dir wiki-source/antelights

--see-also also downloads every page linked in the "See Also" section of the given pages.
Pages come from the wiki's official API (action=parse) and are saved in the same layout as a
page copied from the browser, including the revision id, so build_data.py reads them as usual.
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent.parent
WIKI = "https://abioticfactor.wiki.gg"
API = WIKI + "/api.php"
DELAY = 0.5  # seconds between requests - be polite to the wiki


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = ("AbioticChecklistBuilder/1.0 (unofficial fan checklist; "
                               "https://github.com/VibeCodeScientist/abiotic-factor-checklist)")
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"], respect_retry_after_header=True)
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def fetch(s: requests.Session, title: str) -> dict:
    r = s.get(API, timeout=30, params={
        "action": "parse", "page": title, "prop": "text|revid|displaytitle",
        "format": "json", "formatversion": 2, "redirects": 1, "disableeditsection": 1,
    })
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("info", "unknown API error"))
    return data["parse"]


def see_also_titles(page_html: str) -> list[str]:
    """Titles of the wiki pages linked in the "See Also" section."""
    soup = BeautifulSoup(page_html, "html.parser")
    for h in soup.find_all(["h2", "h3"]):
        if h.get_text(" ", strip=True).lower() != "see also":
            continue
        start = h.parent if h.parent.name == "div" and "mw-heading" in (h.parent.get("class") or []) else h
        titles = []
        for sib in start.find_next_siblings():
            if sib.name in ("h2", "h3") or (sib.name == "div" and "mw-heading" in (sib.get("class") or [])):
                break
            if sib.name == "table":  # navigation boxes follow the section
                break
            for a in sib.find_all("a", href=True):
                m = re.match(r"^/wiki/([^?#]+)$", a["href"])
                if m and ":" not in m.group(1):
                    t = unquote(m.group(1)).replace("_", " ")
                    if t not in titles:
                        titles.append(t)
        return titles
    return []


def wrap(parsed: dict) -> str:
    """Put the API's HTML into the page layout that build_data.py expects."""
    title = parsed["title"]
    url = f"{WIKI}/wiki/{quote(title.replace(' ', '_'))}?oldid={parsed['revid']}"
    return (
        "<main>\n"
        f'<h1 id="firstHeading" class="firstHeading mw-first-heading">{html.escape(title)}</h1>\n'
        '<div id="bodyContent">\n<div id="mw-content-text" class="mw-body-content">\n'
        f"{parsed['text']}\n"
        "</div>\n"
        f'<div class="printfooter">Retrieved from "<a dir="ltr" href="{html.escape(url)}">{html.escape(url)}</a>"</div>\n'
        "</div>\n</main>\n"
    )


def safe_filename(title: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", title).strip() + ".html"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pages", nargs="+", help="wiki page titles, e.g. \"Lab Mask\"")
    ap.add_argument("--see-also", action="store_true", help="also fetch pages linked under 'See Also'")
    ap.add_argument("--dir", default="wiki-source", help="target folder (default: wiki-source)")
    args = ap.parse_args()

    target = (ROOT / args.dir) if not os.path.isabs(args.dir) else Path(args.dir)
    target.mkdir(parents=True, exist_ok=True)
    s = session()
    queue, done, failed = list(args.pages), set(), []
    while queue:
        title = queue.pop(0)
        if title.lower() in done:
            continue
        done.add(title.lower())
        try:
            parsed = fetch(s, title)
        except (requests.RequestException, RuntimeError, ValueError, KeyError) as e:
            print(f"  FAILED {title}: {e}")
            failed.append(title)
            continue
        finally:
            time.sleep(DELAY)
        dest = target / safe_filename(parsed["title"])
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_text(wrap(parsed), encoding="utf-8", newline="\n")
        os.replace(tmp, dest)
        print(f"  {parsed['title']} (revision {parsed['revid']}) -> {dest.relative_to(ROOT)}")
        if args.see_also and title in args.pages:
            linked = see_also_titles(parsed["text"])
            print(f"    See Also: {', '.join(linked) if linked else '(none)'}")
            queue.extend(linked)
    print(f"Done: {len(done) - len(failed)} page(s) saved" + (f", {len(failed)} failed" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
