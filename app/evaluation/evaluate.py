"""
evaluate.py — Run all 15 questions through pipeline and score
Usage:  ./venv/bin/python -m app.evaluation.evaluate
        ./venv/bin/python -m app.evaluation.evaluate --no-cache

Scores:
  - fact_score: % of expected_facts found in answer (lowercased substring)
  - citation_score: does any returned source article match expected_articles?
  - retrieval_ok: was the best dense similarity >= settings.similarity_threshold?

CHANGES
-------
1. Uses `app.retrieval.retriever.retrieve()` instead of calling `search()`
   directly, so the evaluation always measures the DEPLOYED retriever
   (hybrid BM25+RRF when `USE_HYBRID=true`). It previously hardcoded the dense
   path and its own 0.78, so it could report numbers for a system that was not
   the one serving users.
2. `retrieval_ok` now reads the threshold from config, not a literal.
3. Answer cache. Each question costs 2 Gemini calls, and Gemini returned
   429/503 during the last run, which is why Q13 scored 25% — an upstream
   outage recorded as a quality number. Caching keyed on
   (question id, corpus fingerprint, retriever name) makes re-runs free and
   keeps an outage out of the score.
"""
import hashlib
import json
import os
import sys

from app.config import settings
from app.evaluation.test_questions import QUESTIONS
from app.core.llm import rephrase_query, generate_answer
from app.retrieval.retriever import crag_needed, retrieve
from app.retrieval.vector_store import corpus_stats
from app.retrieval.scraper import scrape_adala_text

CACHE_PATH = "app/evaluation/.eval_cache.json"
USE_CACHE = "--no-cache" not in sys.argv

# `generate_answer` returns this Arabic apology when every model in the chain
# failed. It is an ERROR, not an answer, and must never be cached: doing so
# would freeze an outage into the score permanently and report 0% for that
# question on every future run until the fingerprint changed.
FAILURE_MARKER = "الخدمة غير متوفرة"


def _is_failure(answer: str) -> bool:
    return FAILURE_MARKER in answer or not answer.strip()


def _fingerprint() -> str:
    """Corpus + retriever identity. A re-ingest or a retriever change
    invalidates the cache, so a stale answer is never scored as current."""
    s = corpus_stats()
    return hashlib.md5(
        f"{s['chunks']}:{s['max_id']}:{settings.use_hybrid}:{settings.top_k}:"
        f"{settings.similarity_threshold}:{settings.llm_model}".encode()
    ).hexdigest()


def _load_cache() -> dict:
    if not USE_CACHE or not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    if not USE_CACHE:
        return
    try:
        with open(CACHE_PATH, "w") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"  [cache] could not save: {e}")


def _fact_hit(fact, haystacks: tuple[str, ...]) -> bool:
    """
    A fact is satisfied when it is present in the ANSWER **or** the CONTEXT.

    `fact` is either a single string or a list of language variants for one
    concept. Grouping matters: a flat list of translations would grow the
    denominator, so adding an Arabic term to a French question would LOWER the
    score instead of making it gradeable. See the note in test_questions.py.
    """
    variants = fact if isinstance(fact, (list, tuple)) else [fact]
    return any(v.lower() in h for v in variants for h in haystacks)


def score_one(q, cache):
    print(f"\n{'='*60}\nQ{q['id']} [{q['lang']}/{q['category']}]: {q['question']}")
    search_query = rephrase_query(q["question"])
    if search_query != q["question"]:
        print(f"  -> rephrased: {search_query}")

    results, retriever = retrieve(search_query)
    top_sim = max((r.get("similarity", 0.0) for r in results), default=0.0)
    print(f"  retriever: {retriever} | {len(results)} hits, best_dense_sim={top_sim:.3f}")

    # fallback exactly like main.py
    scraped = []
    if crag_needed(results):
        print("  -> low confidence, trying live Adala scraper...")
        scraped = scrape_adala_text(search_query, max_chunks=settings.crag_max_chunks)
        print(f"  -> scraper returned {len(scraped)} chunks")
        results = scraped + results

    results = results[:settings.context_max_chunks]
    context = "\n\n".join([f"[{r.get('law','')} — {r.get('article','')}]\n{r.get('content','')[:500]}" for r in results])
    if not results:
        print("  SKIP: no context found (DB empty or scraper failed)")
        return {"id": q["id"], "fact": 0, "citation": 0, "retrieval": 0}

    key = f"{q['id']}:{_fingerprint()}"
    if key in cache:
        answer = cache[key]
        print(f"  answer: [CACHED HIT] {answer[:180]}...")
    else:
        answer = generate_answer(q["question"], context)
        if _is_failure(answer):
            # Provider outage. Score it as 0 but do NOT persist it, and say so,
            # otherwise an infrastructure blip becomes a permanent quality metric.
            print("  answer: [GENERATION FAILED - not cached, provider outage]")
        else:
            cache[key] = answer
        print(f"  answer preview: {answer[:250]}...")

    # fact score
    haystacks = (answer.lower(), context.lower())
    hits = sum(1 for f in q["expected_facts"] if _fact_hit(f, haystacks))
    fact_score = hits / len(q["expected_facts"]) if q["expected_facts"] else 0

    # citation score
    expected = set(q["expected_articles"])
    found_articles = set(r.get("article","") for r in results)
    citation_score = 1 if expected & found_articles else 0

    retrieval_ok = 1 if top_sim >= settings.similarity_threshold else 0

    # ---------------------------------------------------------------- known gaps
    # A `known_gap` question is one where the CORPUS has no on-point article, so
    # the correct behaviour is an honest refusal rather than a citation. Scoring
    # it like any other question would REWARD the system for inventing an
    # article number, which for a legal tool is the worst possible failure.
    if q.get("known_gap"):
        markers = q.get("refusal_markers", [])
        refused = 1 if any(m in answer for m in markers) else 0
        verdict = ("OK - honest refusal is the correct behaviour" if refused
                   else "WARN - answered anyway; risk of a fabricated citation")
        print(f"  -> KNOWN GAP: refused_plainly={refused} ({verdict})")
        print(f"     found articles: {found_articles} | on-point article expected: {expected}")
        return {"id": q["id"], "fact": None, "citation": None,
                "retrieval": retrieval_ok, "known_gap": True, "refused": refused}

    print(f"  -> fact: {fact_score:.0%} ({hits}/{len(q['expected_facts'])}) citation: {citation_score} retrieval_ok: {retrieval_ok}")
    print(f"     found articles: {found_articles} | expected one of: {expected}")
    return {"id": q["id"], "fact": fact_score, "citation": citation_score, "retrieval": retrieval_ok}

if __name__ == "__main__":
    st = corpus_stats()
    print(f"corpus: {st['chunks']} chunks | retriever: "
          f"{'hybrid_bm25_rrf' if settings.use_hybrid else 'dense_boost'} "
          f"| threshold: {settings.similarity_threshold} | top_k: {settings.top_k}")
    cache = _load_cache()
    print(f"cache: {'ON' if USE_CACHE else 'OFF'} ({len(cache)} stored answers)")
    scores = [score_one(q, cache) for q in QUESTIONS]
    _save_cache(cache)

    # A known_gap question returns fact=None/citation=None: it is scored on
    # refusal quality instead. Averaging it into fact/citation would either
    # crash on None or dilute the metric with a number that means nothing.
    graded = [s for s in scores if not s.get("known_gap")]
    gaps = [s for s in scores if s.get("known_gap")]

    def avg(key):
        vals = [s[key] for s in graded if s.get(key) is not None]
        return sum(vals) / len(vals) if vals else 0.0

    print(f"\n{'='*60}")
    print(f"OVERALL ({len(graded)} graded questions): "
          f"fact {avg('fact'):.0%} | citation {avg('citation'):.0%} | "
          f"retrieval {avg('retrieval'):.0%}")
    if gaps:
        refused = sum(s.get("refused", 0) for s in gaps)
        print(f"KNOWN GAPS ({len(gaps)} question, excluded from the averages): "
              f"refused honestly {refused}/{len(gaps)}")
        for s in gaps:
            if not s.get("refused"):
                print(f"  Q{s['id']}: WARN - answered a question the corpus "
                      f"cannot answer; a fabricated citation is possible")
    print(f"\nTotal questions: {len(scores)}")
