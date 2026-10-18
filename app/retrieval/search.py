"""
search.py — Dense retrieval + lexical re-rank over pgvector

Pipeline for one question
-------------------------
    embed(query)                                   app/core/embed.py
        │
        ▼
    pgvector cosine search  (40 candidates)        <- DENSE stage
        │   ORDER BY embedding <=> query
        ▼
    keyword boost (word-boundary aware)            <- RE-RANK stage
        │   score = similarity + min(0.02*hits, 0.05)
        ▼
    keep top_k, drop anything under the threshold   <- threshold applies to `score`

WHAT CHANGED IN THIS FILE (and why)
------------------------------------
B2  The threshold used to be applied to `similarity` while the ordering used the
    boosted `score`. A chunk promoted by the boost was then discarded anyway, so
    the re-rank was half-cancelled. Now `score` is carried through and filtered.

B3  `w in content` was a substring test: "فولان" matched inside "فلانة", and
    one-letter function words counted. Now it is a word-boundary regex over
    content words of length >= 3, with Arabic stop-words removed.

B4  The defaults were `top_k=5, threshold=0.80` here but `10 / 0.78` in the
    caller. Any call that forgot the override silently got different numbers than
    the docs claimed. Now both come from `app/config.py`.

Nothing here filters on similarity *before* the boost, so a strong lexical match
can still surface a chunk that pure cosine ranked low.
"""

import json

from app.config import settings
from app.core.embed import embed_one
from app.retrieval.tokenize import tokenize
from app.retrieval.vector_store import get_conn



def _keyword_boost(query_tokens: list[str], content: str) -> int:
    """
    How many DISTINCT query tokens appear as whole words in the chunk.

    BEFORE:  hits = sum(1 for w in words if len(w) >= 3 and w in content)   # substring
    AFTER :  word-boundary regex against a pre-tokenised, stop-worded content
    """
    if not query_tokens:
        return 0
    content_tokens = set(tokenize(content))
    return sum(1 for w in set(query_tokens) if w in content_tokens)


def dense_candidates(query: str, n: int | None = None) -> list[dict]:
    """Raw pgvector results, no threshold, no top_k cut — the fusion input."""
    n = n or settings.candidate_pool
    query_vec = embed_one(query)          # applies the "query:" E5 prefix
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, content, source, law, article,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM documents
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (json.dumps(query_vec), json.dumps(query_vec), n),
        ).fetchall()

    return [
        {
            "id": r[0], "content": r[1], "source": r[2],
            "law": r[3], "article": r[4], "similarity": float(r[5]),
        }
        for r in rows
    ]


def rerank_dense(query_tokens: list[str], rows: list[dict],
                 top_k: int | None = None, threshold: float | None = None) -> list[dict]:
    """Apply the lexical boost, re-sort, cut to top_k, filter on the boosted score."""
    top_k = top_k or settings.top_k
    threshold = settings.similarity_threshold if threshold is None else threshold

    for r in rows:
        hits = _keyword_boost(query_tokens, r["content"])
        r["keyword_hits"] = hits
        r["score"] = r["similarity"] + min(hits * settings.keyword_boost_step,
                                           settings.keyword_boost_cap)

    ranked = sorted(rows, key=lambda x: x["score"], reverse=True)[:top_k]
    # B2 FIX: filter on the score we just ranked by, not the pre-boost similarity
    return [r for r in ranked if r["score"] >= threshold]


def search(query: str, top_k: int | None = None, threshold: float | None = None) -> list[dict]:
    """
    Dense search + lexical re-rank. This is the original entry point, kept so the
    smoke test and the evaluation harness keep working unchanged.
    """
    rows = dense_candidates(query)
    results = rerank_dense(tokenize(query), rows, top_k, threshold)
    for r in results:
        r.pop("score", None)      # keep the API response shape stable
    return results
