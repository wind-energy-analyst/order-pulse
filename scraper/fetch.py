"""Fetch press releases from the Nordex News Archive.

Primary source: the WordPress REST API behind https://www.nordex-online.com/en/news-media/blog/
Fallback:       the HTML archive pages (/en/news-media/blog/page/N/) if the API is blocked.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Iterator

import requests
from bs4 import BeautifulSoup

BASE = "https://www.nordex-online.com/en"
API = f"{BASE}/wp-json/wp/v2/posts"
ARCHIVE = f"{BASE}/news-media/blog/"
HEADERS = {"User-Agent": "nordex-deals-tracker/1.0 (+personal research; GitHub Actions)"}
PAUSE_S = 1.0  # be polite

# Boilerplate starts here; everything after is dropped before the LLM sees it.
# "About ..." sections are cut on purpose: a customer's HQ country (e.g. VERBUND, Austria)
# must not be confused with the project country (Albania).
CUT_MARKERS = [
    r"^\s*About the Nordex Group",
    r"^\s*About [A-Z]",
    r"^\s*The Nordex Group\s*[–-]\s*a profile",
    r"^\s*Contact person for press",
    r"^\s*Contact for investor",
    r"Dissemination of a",
    r"^\s*End of News",
]
_cut_re = re.compile("|".join(CUT_MARKERS), re.MULTILINE)

ORDER_TITLE_RE = re.compile(
    r"\border(s|ed)?\b|\bintake\b|\b\d[\d.,]*\s*(MW|GW)\b|\bcontract(s)?\b|\bturbines? for\b|\bsecures?\b|\bwins?\b",
    re.IGNORECASE,
)
NOT_ORDER_TITLE_RE = re.compile(r"voting rights|BlackRock|Article 40|WpHG|Directors' Dealings|managers' transactions", re.IGNORECASE)


def clean_html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "img"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text("\n")
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines()]
    text = "\n".join(ln for ln in lines if ln)
    m = _cut_re.search(text)
    if m and m.start() > 200:  # never cut the lead paragraph
        text = text[: m.start()]
    # Drop the EQS header noise but keep the keyword line
    text = re.sub(r"The issuer is solely responsible for the content of this announcement\.\n?", "", text)
    return text.strip()[:8000]


def keyword_line(text: str) -> str | None:
    m = re.search(r"Key word\(s\):\s*([^\n]+)", text)
    return m.group(1).strip() if m else None


def is_order_candidate(title: str, text: str) -> bool:
    kw = (keyword_line(text) or "").lower()
    if "incoming order" in kw or "order intake" in kw:
        return True
    if NOT_ORDER_TITLE_RE.search(title):
        return False
    return bool(ORDER_TITLE_RE.search(title))


def _normalize(post_id: int | str, date: str, link: str, title: str, html: str) -> dict:
    title = BeautifulSoup(title, "html.parser").get_text().strip()
    text = clean_html_to_text(html)
    return {
        "id": str(post_id),
        "date": date[:19],  # local site time (Europe/Berlin), ISO
        "link": link,
        "title": title,
        "keyword": keyword_line(text),
        "text": text,
        "is_candidate": is_order_candidate(title, text),
    }


# ---------------------------------------------------------------- REST API

def iter_api(after: str | None = None, max_pages: int = 200) -> Iterator[dict]:
    """Yield posts newest-first. `after` is an ISO date; only posts after it are returned."""
    params = {"per_page": 100, "orderby": "date", "order": "desc",
              "_fields": "id,date,link,title,content"}
    if after:
        params["after"] = after
    page, total = 1, 1
    while page <= min(total, max_pages):
        params["page"] = page
        r = requests.get(API, params=params, headers=HEADERS, timeout=60)
        if r.status_code == 400 and page > 1:  # past the last page
            break
        r.raise_for_status()
        total = int(r.headers.get("X-WP-TotalPages", "1"))
        for p in r.json():
            yield _normalize(p["id"], p["date"], p["link"], p["title"]["rendered"], p["content"]["rendered"])
        page += 1
        time.sleep(PAUSE_S)


# ---------------------------------------------------------------- HTML fallback

ARTICLE_LINK_RE = re.compile(r"^https://www\.nordex-online\.com/en/\d{4}/\d{2}/[^/]+/?$")


def _parse_article(url: str) -> dict:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    title = (soup.find("h1").get_text(strip=True) if soup.find("h1") else url)
    meta = soup.find("meta", {"property": "article:published_time"})
    date = meta["content"] if meta else datetime.utcnow().isoformat()
    body = soup.find("article") or soup.find("main") or soup.body
    shortlink = soup.find("link", {"rel": "shortlink"})
    pid = re.search(r"p=(\d+)", shortlink["href"]).group(1) if shortlink else url.rstrip("/").split("/")[-1]
    return _normalize(pid, date, url, title, str(body))


def iter_html(after: str | None = None, max_pages: int = 200) -> Iterator[dict]:
    for n in range(1, max_pages + 1):
        url = ARCHIVE if n == 1 else f"{ARCHIVE}page/{n}/"
        r = requests.get(url, headers=HEADERS, timeout=60)
        if r.status_code == 404:
            break
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            if ARTICLE_LINK_RE.match(a["href"]) and a["href"] not in links:
                links.append(a["href"])
        if not links:
            break
        stop = False
        for link in links:
            post = _parse_article(link)
            time.sleep(PAUSE_S)
            if after and post["date"] <= after:
                stop = True
                break
            yield post
        if stop:
            break
        time.sleep(PAUSE_S)


def iter_posts(after: str | None = None, max_pages: int = 200) -> Iterator[dict]:
    try:
        yield from iter_api(after, max_pages)
    except requests.RequestException as e:
        print(f"[fetch] REST API failed ({e}); falling back to HTML archive")
        yield from iter_html(after, max_pages)
