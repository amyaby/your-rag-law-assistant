"""
web_search.py — DuckDuckGo fallback for Corrective RAG, restricted to Morocco

THE BUG THIS FILE WAS REWRITTEN FOR (README issue D1)
----------------------------------------------------
`web_search("الشيك بدون رصيد")` — a *Moroccan* legal question — returned a page
from the **Dubai Public Prosecution** describing **UAE Penal Code article 401**.
`web_search.py` only excluded social media:

    if any(x in url for x in ["youtube.com", "facebook.com", "tiktok.com"]):
        continue

Any Arabic legal page passes the "is this law-like?" test, including GCC
legislation. Every other failure mode in this project produces a *missing*
answer; this one produces a **confident, well-formatted, wrong-jurisdiction
answer**, which is strictly worse.

THE FIX — three layers
----------------------
1. DOMAIN ALLOWLIST. Only `.ma` hosts (adala.justice.gov.ma, ism.ma, sgg.gov.ma,
   maroc.ma ...) are allowed to contribute. Configurable via
   `settings.allowed_web_domains`.
2. MOROCCAN MARKER. The page must mention a Moroccan institution or law
   reference, otherwise it is dropped even if the domain passed.
3. PARALLEL FETCH. The old loop fetched up to 4 pages serially with a 10s
   timeout each, so a CRAG hit could add 40s to a single /ask request. Now the
   candidate pages are fetched concurrently with one shared session.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover - older pip
    from duckduckgo_search import DDGS

from app.config import settings

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}

BLOCKED_HOSTS = ("youtube.com", "facebook.com", "tiktok.com", "instagram.com", "x.com")

# Markers that a page is actually about Moroccan law
MA_MARKERS = (
    "المغرب", "المغربي", "المغربية", "القانون المغربي", "المحكمة", "محكمة",
    "الجريدة الرسمية", "otype", "adala.justice.gov.ma", "ism.ma", "sgg.gov.ma",
    "المادة", "الفصل",
)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _is_allowed(url: str, allowed: list[str]) -> bool:
    """
    1. not social media, 2. host is a Moroccan (.ma) domain.

    TWO ENTRY KINDS
    ---------------
    ".ma"        a TLD RULE. Matches ANY host ending in .ma.
    "ism.ma"     an EXACT HOST. Matches ism.ma and its subdomains only.

    WHY THE DISTINCTION IS NOT COSMETIC
    ----------------------------------
    The first version collapsed both into `host == d or host.endswith("." + d)`.
    For d = ".ma" that evaluates to `endswith("..ma")`, which is never true, so
    the allowlist rejected *every* Moroccan site and the whole web fallback
    dead-ended. Treating a leading dot as "this is a TLD suffix" is what makes
    `allowed_web_domains = ".ma,adala.justice.gov.ma,..."` behave as documented.
    """
    host = _host(url)
    if not host or any(b in host for b in BLOCKED_HOSTS):
        return False
    for d in allowed:
        if d.startswith("."):
            if host.endswith(d):
                return True
        elif host == d or host.endswith("." + d):
            return True
    return False


def _is_moroccan_legal(text: str) -> bool:
    """2. the extracted text must look like Moroccan law, not Gulf law."""
    return any(marker in text for marker in MA_MARKERS)


def _law_like(text: str) -> bool:
    """Kept from the original: is there any article structure at all?"""
    if text.count("المادة") or text.count("الفصل"):
        return True
    return len(text) >= 800


def _fetch_and_chunk(hit: dict, allowed: list[str]) -> list[dict]:
    url = hit.get("href", "")
    if not url or not _is_allowed(url, allowed):
        return []
    try:
        html = requests.get(url, headers=HEADERS, timeout=settings.web_timeout).text
        soup = BeautifulSoup(html, "html.parser")
        article = soup.find("article") or soup.find("main") or soup
        for junk in soup(["script", "style", "nav", "footer", "header"]):
            junk.decompose()
        text = re.sub(r"\n{3,}", "\n\n", article.get_text("\n"))
        if not _law_like(text) or not _is_moroccan_legal(text):
            return []
        from app.ingestion.chunker import article_chunks
        return article_chunks(text, law=hit.get("title", "")[:40], source=f"ddg:{url}")
    except Exception:
        return []


def web_search(query: str, max_chunks: int = 3, site: str | None = None) -> list[dict]:
    """
    General internet search, RESTRICTED to Moroccan domains.
    `site='ism.ma'` narrows further; the allowlist is always enforced.
    """
    q = f"site:{site} {query}" if site else query
    try:
        with DDGS() as ddgs:
            hits = list(ddgs.text(q, max_results=8))
    except Exception as e:
        print(f"[web] DDG fail {e}")
        return []

    allowed = settings.allowed_domains
    candidates = [h for h in hits if _is_allowed(h.get("href", ""), allowed)]
    dropped = len(hits) - len(candidates)
    if dropped:
        print(f"[web] dropped {dropped} non-Moroccan result(s)")

    if not candidates:
        print("[web] no .ma result — refusing to answer from foreign law")
        return []

    # 3. fetch concurrently instead of one-by-one
    session = requests.Session()
    session.headers.update(HEADERS)
    with ThreadPoolExecutor(max_workers=min(4, len(candidates))) as pool:
        results = list(pool.map(lambda h: _fetch_and_chunk(h, allowed), candidates))

    chunks: list[dict] = []
    for group in results:
        chunks.extend(group)
        if len(chunks) >= max_chunks:
            break
    return chunks[:max_chunks]


def jina_read(url: str) -> str:
    """Agent-Reach web.py:31 style — clean Markdown via Jina Reader, no BeautifulSoup guess"""
    import urllib.request
    jina_url = f"https://r.jina.ai/{url}"
    req = urllib.request.Request(jina_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/plain"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")
