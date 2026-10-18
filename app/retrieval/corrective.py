"""
corrective.py — Orchestrator for Corrective RAG
Tries 3 scrapers in order: adala (official circulars) -> ism (140 PDFs)
-> DDG (general web, .ma allowlisted).
Called from app/main.py when the pgvector top score is below the threshold.

THE RELEVANCE GATE (and why it exists here)
-------------------------------------------
An earlier version was:

    for fn in [scrape_adala_text, scrape_ism_text, web_search]:
        chunks = fn(query, max_chunks=max_chunks)
        if chunks:
            return chunks          # first non-empty answer wins

`if chunks` is not a quality check. A live probe showed the real damage:

    scrape_ism_text("عقوبة السرقة في القانون المغربي")
      -> 3 chunks from "عام - التبادل الإلكتروني للمعطيات القانونية"
         (general law on the electronic exchange of legal data)

ISM matches on PDF *filenames*. A filename match is weak evidence, so a theft
question landed on a data-exchange circular - and because the scraper returned
*something*, CRAG stopped there and never tried the web search that would have
answered correctly.

Note this could not be caught by the domain allowlist (README issue D1).
ism.ma genuinely is Moroccan, so those chunks pass every provenance check we
have. "Is it the right jurisdiction?" and "is it the right subject?" are
different questions, and only the second one is answered here.

So each candidate chunk is now scored against the query before it is allowed to
reach the LLM, and a scraper whose chunks all fail does not end the search:

    for fn in [...]:
        kept = [c for c in fn(query) if relevance(query, c) >= threshold]
        if kept:
            return kept
    return []          # genuinely nothing on-topic -> caller says "no source"

Returning an empty list is a CORRECT outcome. It lets the caller report that no
source was found instead of generating a confident answer from an unrelated
Moroccan document.
"""
import time

from app.config import settings
from app.retrieval.relevance import matched_stems, relevance
from app.retrieval.scraper import scrape_adala_text
from app.retrieval.ism_scraper import scrape_ism_text
from app.retrieval.web_search import web_search

# Order is deliberate: official ministry circulars first, then the ISM
# document library, then the open web. Cost and authority both increase down
# the list, so the cheap-but-authoritative sources get first refusal.
SCRAPERS = (
    ("adala", scrape_adala_text),
    ("ism", scrape_ism_text),
    ("ddg", web_search),
)


def _filter_relevant(query: str, chunks: list[dict], source: str) -> list[dict]:
    """Keep only chunks that are actually about the query. Logs every drop."""
    threshold = settings.crag_min_relevance
    kept: list[dict] = []
    for c in chunks:
        content = c.get("content", "")
        score = relevance(query, content)
        if score >= threshold:
            c["relevance"] = round(score, 3)
            kept.append(c)
        else:
            # Logged, not silent: an unexplained empty CRAG result is
            # indistinguishable from a network failure.
            print(f"[CRAG] dropped off-topic chunk from {source} "
                  f"relevance={score:.3f} < {threshold:.2f} "
                  f"matched={matched_stems(query, content)[:4]} "
                  f"law={str(c.get('law', ''))[:40]!r}")
    return kept


def corrective_search(query: str, max_chunks: int = 3) -> list[dict]:
    """
    Try each scraper in order; return the first scraper's RELEVANT chunks.

    Returns [] when nothing on-topic was found, which callers must treat as
    "no source available" and not as an error.
    """
    for name, fn in SCRAPERS:
        try:
            t0 = time.perf_counter()
            chunks = fn(query, max_chunks=max_chunks)
            fetch_ms = int((time.perf_counter() - t0) * 1000)

            if not chunks:
                print(f"[CRAG] {name} -> 0 chunks ({fetch_ms}ms)")
                continue

            kept = _filter_relevant(query, chunks, name)
            if not kept:
                print(f"[CRAG] {name} -> {len(chunks)} chunks but none relevant "
                      f"({fetch_ms}ms); trying the next source")
                continue

            best = max(c.get("relevance", 0.0) for c in kept)
            print(f"[CRAG] {name} -> kept {len(kept)}/{len(chunks)} relevant "
                  f"chunks best={best:.3f} ({fetch_ms}ms) for: {query[:40]}")
            return kept

        except Exception as e:
            # One dead source must not kill the fallback chain.
            print(f"[CRAG] {name} error: {type(e).__name__}: {e}")
            continue

    print("[CRAG] no on-topic source found - refusing to answer from "
          "an unrelated document")
    return []
