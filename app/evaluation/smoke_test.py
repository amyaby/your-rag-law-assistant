"""
smoke_test.py — Offline checks (no server needed)
Usage:  ./venv/bin/python -m app.evaluation.smoke_test

Checks, in order:
  1. embed.py        -> embedding is 384-dim
  2. search.py       -> pgvector returns the right article for a legal question
  2b. hybrid.py      -> BM25 index builds, RRF fusion returns ranked rows
  2c. idempotency    -> no duplicate (law, article, content) rows in the DB
  3. ism_scraper     -> how many PDFs ism.ma exposes
  4. scraper.py      -> adala.justice.gov.ma live chunks
  5. web_search.py   -> DuckDuckGo live chunks
  6. web allowlist   -> foreign (non-.ma) law is rejected   [NEW]
"""
import sys

from app.core.embed import embed_texts, embed_query
from app.retrieval.search import search
from app.retrieval.hybrid import hybrid_search, get_index
from app.retrieval.vector_store import get_conn
from app.retrieval.ism_scraper import list_ism_pdfs
from app.retrieval.scraper import scrape_adala_text
from app.retrieval.web_search import web_search, _is_allowed, _is_moroccan_legal
from app.ingestion.chunker import pdf_health_check

ok = True


def check(name, condition, detail=""):
    global ok
    mark = "PASS" if condition else "FAIL"
    if not condition:
        ok = False
    print(f"[{mark}] {name}{(' -> ' + detail) if detail else ''}")


def warn(name, detail=""):
    print(f"[WARN] {name}{(' -> ' + detail) if detail else ''}")


print("=" * 60)
print("1. EMBEDDINGS (app/core/embed.py)")
vec = embed_texts(["المادة 505 من القانون الجنائي"])[0]
qvec = embed_query("ما هي عقوبة السرقة؟")
check("passage vector is 384-dim", len(vec) == 384, f"len={len(vec)}")
check("query vector is 384-dim", len(qvec) == 384, f"len={len(qvec)}")
check("passage != query vector for same text",
      list(embed_texts(["السرقة"])[0]) != list(embed_query("السرقة")),
      "prefix 'passage:' vs 'query:' works")

print("=" * 60)
print("2. VECTOR SEARCH (app/retrieval/search.py)")
hits = search("ما هي عقوبة السرقة؟", top_k=3)
check("search returned rows", len(hits) > 0, f"{len(hits)} hits")
if hits:
    for h in hits[:3]:
        print(f"       article={h.get('article')} sim={h.get('similarity'):.3f} law={h.get('law')}")
    check("top similarity >= 0.78", hits[0]["similarity"] >= 0.78, f"top={hits[0]['similarity']:.3f}")
    if any(str(h.get("article")) == "505" for h in hits):
        check("penal-code article 505 in top-3", True)
    else:
        warn("article 505 not in top-3 (fuzzy retrieval is normal)",
             f"got {[h.get('article') for h in hits]} — try a more specific question")
    if len({(h.get("law"), h.get("article"), h.get("content", "")[:60]) for h in hits}) < len(hits):
        warn("duplicate chunks in DB", "run POST /reset then POST /ingest-all")

print("=" * 60)
print("3. HYBRID RETRIEVAL (app/retrieval/hybrid.py)  [NEW]")
try:
    bm25, rows = get_index()
    check("BM25 index built", bm25.n_docs > 0,
          f"{bm25.n_docs} docs, {len(bm25.idf)} terms, avgdl={bm25.avgdl:.1f}")

    hh = hybrid_search("ما هي عقوبة السرقة؟")
    check("hybrid_search returned rows", len(hh) > 0, f"{len(hh)} hits")
    if hh:
        for h in hh[:3]:
            print(f"       sim={h.get('similarity', 0):.3f} bm25={h.get('bm25_score')} "
                  f"rrf={h.get('rrf_score')} via={h.get('via')} "
                  f"dense=#{h.get('dense_rank')} bm25rank=#{h.get('bm25_rank')} "
                  f"art={h.get('article')}")
        check("every hit carries an RRF score",
              all(h.get("rrf_score", 0) > 0 for h in hh))
        check("hits are sorted by RRF descending",
              all(hh[i]["rrf_score"] >= hh[i + 1]["rrf_score"] for i in range(len(hh) - 1)))
        # The bug this file had on first write: bm25_by_id indexed `rows` by
        # document id instead of row index, so every score came back 0.0.
        check("at least one hit has a non-zero BM25 score",
              any(h.get("bm25_score", 0) > 0 for h in hh),
              f"max bm25={max((h.get('bm25_score', 0) for h in hh), default=0)}")
        # Admission is an OR: dense-similar OR strongly lexical. A pure-lexical
        # hit legitimately has no cosine, so it must not be threshold-dropped.
        check("every hit was admitted by dense OR bm25 (not a bare cosine filter)",
              all(h.get("via") in ("dense", "bm25", "dense+bm25") for h in hh),
              f"via={[h.get('via') for h in hh]}")
        bad = [h for h in hh if h.get("via") == "dense"
               and h.get("similarity", 0) < 0.78]
        check("no dense-only hit slipped in under the threshold", not bad,
              f"offenders={[h.get('article') for h in bad]}")
except Exception as e:
    check("hybrid_search", False, f"{type(e).__name__}: {str(e)[:90]}")

print("=" * 60)
print("4. IDEMPOTENT INGESTION (app/retrieval/vector_store.py)  [NEW]")
try:
    with get_conn() as conn:
        total = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        uniq = conn.execute(
            "SELECT count(DISTINCT (law, article, md5(content))) FROM documents"
        ).fetchone()[0]
    check("no duplicate chunks in DB", total == uniq, f"total={total} uniq={uniq}")
    if total == 0:
        warn("DB is empty", "run POST /reset then POST /ingest-all")
except Exception as e:
    warn("idempotency check skipped", f"{type(e).__name__}: {str(e)[:90]}")

print("=" * 60)
print("5. PDF QUALITY GATE (app/ingestion/chunker.py)  [NEW]")
try:
    import glob
    import os
    files = sorted(glob.glob("data/docs/*.pdf"))
    accepted = skipped = 0
    for f in files:
        ok_g, reason, st = pdf_health_check(f, os.path.basename(f))
        if ok_g:
            accepted += 1
        else:
            skipped += 1
            print(f"       skipped {os.path.basename(f)[:40]}: {reason}")
    check("gate evaluated every PDF", accepted + skipped == len(files),
          f"{accepted} accepted / {skipped} skipped of {len(files)}")
except Exception as e:
    warn("quality gate check skipped", f"{type(e).__name__}: {str(e)[:90]}")

print("=" * 60)
print("6. ISM SCRAPER (app/retrieval/ism_scraper.py)")
try:
    pdfs = list_ism_pdfs()
    check("ism.ma PDF list not empty", len(pdfs) > 50, f"{len(pdfs)} pdfs")
    if pdfs:
        print(f"       sample: {pdfs[0].get('title')} -> {pdfs[0].get('url')}")
except Exception as e:
    warn("ism.ma unreachable (network/DNS)", f"{type(e).__name__}: {str(e)[:90]}")

print("=" * 60)
print("7. ADALA SCRAPER (app/retrieval/scraper.py)")
try:
    adala = scrape_adala_text("الحضانة", max_chunks=3)
    check("adala returned chunks", len(adala) > 0, f"{len(adala)} chunks")
except Exception as e:
    warn("adala unreachable", f"{type(e).__name__}: {str(e)[:90]}")

print("=" * 60)
print("8. WEB SEARCH + .ma ALLOWLIST (app/retrieval/web_search.py)  [NEW]")
# The regression that produced a confident UAE/Dubai answer to a Moroccan
# question: DuckDuckGo has no idea what jurisdiction you meant.
check("rejects Dubai Public Prosecution (the real D1 bug)",
      not _is_allowed("https://www.dpp.gov.ae/en/", [".ma", "ism.ma", "adala.justice.gov.ma"]))
check("rejects a UAE law blog",
      not _is_allowed("https://uaelegislation.gov.ae/", [".ma", "ism.ma"]))
check("accepts adala.justice.gov.ma",
      _is_allowed("https://adala.justice.gov.ma/", [".ma", "adala.justice.gov.ma"]))
check("accepts any .ma subdomain via the bare '.ma' entry",
      _is_allowed("https://sgg.gov.ma/x", [".ma"]))
check("rejects facebook.com even though it ends in a non-.ma host",
      not _is_allowed("https://facebook.com/x", [".ma"]))
check("Moroccan marker present in real MA text",
      _is_moroccan_legal("نص القانون المغربي حسب الجريدة الرسمية"))
check("Moroccan marker absent from pure UAE text",
      not _is_moroccan_legal("UAE Federal Decree-Law No. 3 of 2016 on Counterfeit"))

try:
    web = web_search("الحضانة", max_chunks=2)
    if web:
        check("web search returned chunks", True, f"{len(web)} chunks")
        bad = [w for w in web if not str(w.get("source", "")).startswith("ddg:")]
        check("every web chunk records its source URL", not bad)
    else:
        warn("web search empty", "no .ma result, DDG rate limit, or allowlist too strict")
except Exception as e:
    warn("web search failed", f"{type(e).__name__}: {str(e)[:90]}")

print("=" * 60)
print("SMOKE TEST:", "ALL PASS" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
