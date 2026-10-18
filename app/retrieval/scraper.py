"""
scraper.py — Adala live fallback
When PDF search has no good hit, fetch text from Adala (Ministry of Justice
circulars / notes / publications) and return it as chunks shaped like DB chunks:
{law, article, content, source}.

Empty list = nothing on-topic found, or a network error. Callers (corrective.py)
must treat [] as "no source available" and never as "fall back to this anyway".

--------------------------------------------------------------------------
WHAT WAS ACTUALLY WRONG (diagnosed live, not guessed)
--------------------------------------------------------------------------
The old matcher was:

    if not any(w in obj for w in query.split() if len(w) > 2):
        continue

A live probe of https://adala.justice.gov.ma/ar/search?term=السرقة returned
exactly one result, and it was never used. That single line is the reason:

    query word   "السرقة"   (with the definite article)
    result title "سرقة ..." (without it)
    "السرقة" in "سرقة ..."  ->  False        # rejected

So Adala was never wrong; the scraper refused the one good hit. Four further
defects fell out of the same rewrite:

1. Substring matching is the wrong test for Arabic. The article "ال" is
   optional and must be stripped before comparing, which is what
   relevance.stem() does. It also made the test too LOOSE in the other
   direction: for "عقوبة السرقة في القانون المغربي" the words "القانون" and
   "المغربي" occur in nearly every legal title, so a document that matched
   nothing on-topic still passed the `any(...)` test. relevance() removes
   those generic words before scoring (see LEGAL_GENERIC).

2. Every Arabic query was sent to /fr/search. Arabic lives under /ar/.
   French queries against /ar/ (and vice versa) return total=0.

3. `if d.get("language") != "AR": continue` made Adala structurally dead for
   any French question. Language is now inferred from the query and used to
   pick the endpoint, not to throw results away.

4. Pages were joined with "".join(...) — no separator — which welded the last
   word of page 1 to the first word of page 2 and corrupted the text. Also
   `subprocess curl` for the download while `requests` was already imported.

Adala is a CIRCULARS/PUBLICATIONS library, not a code: "المادة 505" and English
queries return nothing by design. That is a source limitation, not a bug here,
and the relevance gate is what stops it from answering with an unrelated
Moroccan circular.
"""
import json
import re
import time
import unicodedata
import urllib.parse

import requests
from bs4 import BeautifulSoup

from app.config import settings
from app.ingestion.chunker import article_chunks
from app.retrieval.relevance import keywords, matched_stems, relevance
from app.retrieval.robots import allowed

BASE = "https://adala.justice.gov.ma"
# Honest, contactable UA (see app/retrieval/robots.py for why impersonating a
# browser is the wrong default). Robots rules are fetched with the same agent,
# so what we are permitted and what we ask for are the same thing.
HEADERS = {"User-Agent": "MoroccanLawRAG-StudentProject/1.0 (educational RAG research)"}
TIMEOUT = 10

_AR = re.compile(r"[\u0600-\u06FF]")
_NEXT_DATA = re.compile(r'"__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

# Adala is a small, public government site. Two requests per query with a gap,
# not a burst - being a good citizen of someone else's server is the point.
# This gap is enforced by the shared PoliteFetcher below, so it covers PDF
# downloads too, not just the two search calls.
_REQUEST_GAP = 2.0
_last_request = 0.0


def _throttle() -> None:
    """Block until _REQUEST_GAP has passed since the last request to this host."""
    global _last_request
    wait = _REQUEST_GAP - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def _is_arabic(text: str) -> bool:
    return bool(_AR.search(text))


def _lang(query: str) -> str:
    return "ar" if _is_arabic(query) else "fr"


def _search_terms(query: str) -> list[str]:
    """
    Adala's index matches on short real words, not whole questions.

    Probe evidence:
        /ar/search?term=السرقة                      -> total 1  (the good hit)
        /ar/search?term=عقوبة السرقة في القانون المغربي -> total 0
        /ar/search?term=قانون                       -> total 15 (pensions, census...)

    So: try the full query, then the most distinctive REAL token. Real, not
    stemmed - see relevance.keywords(). Max 2 requests, _REQUEST_GAP apart.
    """
    terms = [query.strip()]
    for t in keywords(query):
        if t and t not in terms:
            terms.append(t)
    return terms[:2]


def _get(url: str, **kw) -> requests.Response:
    """
    One HTTP path for every call to this host: robots check, throttle, fetch.

    Every request in this module goes through here, which is the only way the
    politeness and permission guarantees actually hold. A direct
    requests.get() elsewhere in the file would bypass both.
    """
    if not allowed(url):
        print(f"[scraper] robots.txt does not permit {url[:80]}")
        raise PermissionError(f"robots.txt disallows {url}")
    _throttle()
    return requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kw)


def _fetch_search_props(term: str, lang: str) -> dict:
    """Pull pageProps out of the Next.js payload Adala embeds in its HTML."""
    url = f"{BASE}/{lang}/search?term={urllib.parse.quote(term)}"
    html = _get(url).text
    m = _NEXT_DATA.search(html)
    if not m:
        return {}
    return json.loads(m.group(1)).get("props", {}).get("pageProps", {})


def _arabic_ratio(text: str) -> float:
    stripped = text.strip()
    if not stripped:
        return 0.0
    return len(_AR.findall(text)) / len(stripped)


def law_label(d: dict) -> str:
    """Best available human label for a result."""
    return str(d.get("name") or d.get("title") or "")[:40]


def _meta_text(d: dict) -> str:
    """All the searchable metadata Adala gives us for one result, as one string."""
    meta = d.get("fileMeta") or {}
    return " ".join(str(x) for x in (
        d.get("name"),
        d.get("title"),
        d.get("object"),
        meta.get("object"),
        meta.get("theme"),
        d.get("theme"),
    ) if x)


def _candidate_chunks(d: dict, query: str) -> list[dict]:
    """
    Download one result's PDF and return its article chunks, or [].

    The PDF URL is /api/{path}. Verified live: /api/... -> 200 with a %PDF body,
    while both /{path} and /adala/new_fr_pdf/{path} return 404.
    """
    path = d.get("path")
    if not path:
        return []

    pdf_url = f"{BASE}/api/{urllib.parse.quote(path, safe='/')}"
    try:
        resp = _get(pdf_url)
        resp.raise_for_status()
        if b"%PDF" not in resp.content[:1024]:
            print(f"[scraper] {pdf_url[:70]} is not a PDF")
            return []

        import pymupdf as fitz
        doc = fitz.open(stream=resp.content, filetype="pdf")
        # "\n" matters: joining with "" welds page boundaries into garbage.
        text = "\n".join(p.get_text() for p in doc)
        doc.close()
    except Exception as e:
        print(f"[scraper] PDF {str(d.get('name', ''))[:30]} failed: "
              f"{type(e).__name__}: {e}")
        return []

    text = unicodedata.normalize("NFKC", text)
    # Reuse the ingestion health gate instead of a local magic number: below
    # min_pdf_chars the PDF is a scan with no text layer, so there is nothing
    # to answer with. Verified live - the one theft hit Adala has,
    # "حول ظاهرة سرقة بعض المحاصيل الزراعية" (a genuine 1.0 match on the
    # query), is exactly this: 187 KB of valid PDF that yields 4 characters.
    # Returning [] here is CORRECT; doing it silently is not.
    if len(text.strip()) < settings.min_pdf_chars:
        print(f"[scraper] {law_label(d)[:34]!r} is a scan with no text layer "
              f"({len(text.strip())} chars < {settings.min_pdf_chars}) - "
              f"nothing to extract")
        return []
        if _arabic_ratio(text) < settings.min_pdf_arabic_ratio:
            print(f"[scraper] {law_label(d)[:34]!r} is not Arabic text "
                  f"(ratio {_arabic_ratio(text):.2f} < "
                  f"{settings.min_pdf_arabic_ratio:.2f})")
            return []

    return article_chunks(text, law=law_label(d), source=f"adala:pdf:{pdf_url}")


def _html_chunks(r: dict, query: str) -> list[dict]:
    """Adala's HTML page for a result, when it has real body text."""
    rid = r.get("id")
    if not rid:
        return []
    try:
        page = _get(f"{BASE}/ar/resources/{rid}").text
        soup = BeautifulSoup(page, "html.parser")
        article = soup.find("article") or soup.find("main")
        if not article:
            return []
        lines = [
            l.strip() for l in article.get_text(separator="\n").splitlines()
            if len(l.strip()) > 20 and _AR.search(l)
        ]
    except Exception:
        return []

    if not lines:
        return []
    law = str(r.get("lawNumber") or r.get("title") or "")[:40]
    return article_chunks("\n".join(lines[:60]), law=law, source=f"adala:html:{rid}")


def scrape_adala_text(query: str, max_chunks: int = 3) -> list[dict]:
    """
    Query Adala live and return up to max_chunks RELEVANT chunks:
    {law, article, content, source, relevance}

    Chunks below settings.crag_min_relevance are dropped here as well as in
    corrective.py, because the same chunks can be reached from other paths.
    """
    lang = _lang(query)
    threshold = settings.crag_min_relevance
    collected: list[dict] = []

    for term in _search_terms(query):
        try:
            props = _fetch_search_props(term, lang)
        except Exception as e:
            print(f"[scraper] search fetch failed for {term!r}: "
                  f"{type(e).__name__}: {e}")
            return collected          # keep whatever an earlier term found

        results = props.get("searchResult", {}).get("data", []) or []
        if not results:
            print(f"[scraper] no results for {term!r} ({lang})")
            continue

        print(f"[scraper] {len(results)} result(s) for {term!r} ({lang})")

        for d in results:
            meta = _meta_text(d)
            score = relevance(query, meta)
            if score < threshold:
                # Exactly the bug this file had: a title that IS about the query
                # was rejected because of the leading "ال".
                print(f"[scraper] skip {str(d.get('name',''))[:34]!r} "
                      f"relevance={score:.3f} matched="
                      f"{matched_stems(query, meta)[:3]}")
                continue

            chunks = _candidate_chunks(d, query) or _html_chunks(d, query)
            for c in chunks:
                body = relevance(query, c.get("content", ""))
                if body < threshold:
                    continue
                c["relevance"] = round(max(score, body), 3)
                collected.append(c)
            if len(collected) >= max_chunks:
                return collected[:max_chunks]

    return collected[:max_chunks]
