"""
hybrid.py — Hybrid retrieval: dense (pgvector) + sparse (BM25), fused with RRF

WHY
---
`search.py` is *dense retrieval with a lexical re-rank*, not a real hybrid
engine. The re-rank adds at most +0.05 to a cosine score, uses no IDF, and
matches substrings. That is enough to stop the pure-vector failure mode
("formal-looking question, key noun in the text") but it cannot rank a chunk
that is lexically *far* better while semantically close.

BM25 fixes exactly that: it rewards a chunk containing the query's rare terms and
penalises long chunks. For legal questions the article number, the offence name
and the specific noun are exactly those rare terms.

Reciprocal Rank Fusion (RRF) then merges the two ranked lists without needing the
two scores to be comparable — a vector cosine (0..1) and a BM25 score (0..30) are
not on the same scale, but RANKS are:

    RRF(d) = Σ_r  1 / (k + rank_r(d))          k = 60 (config: rrf_k)

This is the standard formulation from Cormack et al. 2009 and it is what
production search stacks use to merge Elasticsearch + a vector index.

IMPLEMENTATION NOTES
--------------------
* BM25 is implemented here in ~35 lines instead of adding `rank_bm25`: one less
  dependency, and the scoring function becomes explainable in a report.
* The index covers the whole corpus (5 274 chunks, ~2 MB of text), so it is built
  once and cached in-process, invalidated by a `(chunk_count, max_id)` fingerprint.
  Query time is then just a sparse dot product — no DB hit for the lexical half.
* The **threshold still applies to the dense cosine similarity**, because that is
  the number Corrective RAG has always reasoned about. RRF only decides ORDER.
  This keeps CRAG triggering exactly where it used to, so evaluation results stay
  comparable before/after this change.
"""

import math
import threading
from collections import Counter

from app.config import settings
from app.retrieval.tokenize import tokenize
from app.retrieval.search import _keyword_boost, dense_candidates
from app.retrieval.vector_store import corpus_stats, get_conn


# ============================================================== BM25 core ====
class BM25:
    """
    Okapi BM25.

        score(D,Q) = Σ_{t∈Q} IDF(t) · f(t,D)(k1+1)
                                    ─────────────────────────────
                                    f(t,D) + k1·(1 - b + b·|D|/avgdl)

        IDF(t) = ln( 1 + (N - df(t) + 0.5) / (df(t) + 0.5) )

    k1 -> how fast term-frequency gains saturate (1.2-2.0)
    b  -> how strongly long chunks are penalised (0 = none, 1 = full)
    """

    def __init__(self, corpus_tokens: list[list[str]], k1: float, b: float):
        self.k1, self.b = k1, b
        self.n_docs = len(corpus_tokens)
        self.doc_len = [len(d) for d in corpus_tokens]
        self.avgdl = (sum(self.doc_len) / self.n_docs) if self.n_docs else 0.0

        self.tf: list[Counter] = [Counter(d) for d in corpus_tokens]
        df: Counter = Counter()
        for d in self.tf:
            df.update(d.keys())
        # A term in every document carries no information -> negative IDF
        self.idf = {
            t: math.log(1 + (self.n_docs - n + 0.5) / (n + 0.5)) for t, n in df.items()
        }

    def scores(self, query_tokens: list[str]) -> list[float]:
        out = [0.0] * self.n_docs
        for t in set(query_tokens):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(t, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.doc_len[i] / (self.avgdl or 1))
                out[i] += idf * f * (self.k1 + 1) / denom
        return out


# ====================================================== cached corpus index ==
_lock = threading.Lock()
_cache: dict = {"stamp": None, "bm25": None, "rows": None}


def _load_corpus() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, content, source, law, article FROM documents ORDER BY id"
        ).fetchall()
    return [
        {"id": r[0], "content": r[1], "source": r[2], "law": r[3], "article": r[4]}
        for r in rows
    ]


def get_index() -> tuple[BM25, list[dict]]:
    """Build the BM25 index once; rebuild only when the corpus changed."""
    stats = corpus_stats()
    stamp = (stats["chunks"], stats["max_id"])
    if _cache["stamp"] == stamp and _cache["bm25"] is not None:
        return _cache["bm25"], _cache["rows"]

    with _lock:
        if _cache["stamp"] == stamp and _cache["bm25"] is not None:
            return _cache["bm25"], _cache["rows"]
        rows = _load_corpus()
        bm25 = BM25([tokenize(r["content"]) for r in rows], settings.bm25_k1, settings.bm25_b)
        _cache.update(stamp=stamp, bm25=bm25, rows=rows)
        return bm25, rows


def invalidate_cache() -> None:
    with _lock:
        _cache.update(stamp=None, bm25=None, rows=None)


# ==================================================================== fusion ==
def _rrf(rank: int, k: int) -> float:
    return 1.0 / (k + rank)


def hybrid_search(query: str, top_k: int | None = None,
                  threshold: float | None = None) -> list[dict]:
    """
    Dense + BM25, fused with RRF, then the usual lexical boost and threshold.

    Returns the same dict shape as `search()` plus:
        bm25_score, dense_rank, bm25_rank, rrf_score
    """
    top_k = top_k or settings.top_k
    threshold = settings.similarity_threshold if threshold is None else threshold
    q_tokens = tokenize(query)

    # ---- stage 1: dense candidates
    dense = dense_candidates(query, n=max(settings.candidate_pool, top_k * 4))
    dense_by_id = {r["id"]: dict(r) for r in dense}
    dense_rank = {r["id"]: i + 1 for i, r in enumerate(dense)}

    # ---- stage 2: sparse scores over the full corpus
    bm25, rows = get_index()
    bm25_scores = bm25.scores(q_tokens) if q_tokens else []
    lexical_top = sorted(
        (i for i, s in enumerate(bm25_scores) if s > 0),
        key=lambda i: bm25_scores[i],
        reverse=True,
    )[: settings.candidate_pool]
    # NOTE: `lexical_top` holds ROW INDICES, `bm25_rank` holds DOCUMENT IDS.
    # Mixing the two silently returns 0.0 for every bm25_score.
    bm25_rank = {rows[i]["id"]: n + 1 for n, i in enumerate(lexical_top)}
    bm25_by_id = {rows[i]["id"]: bm25_scores[i] for i in lexical_top}

    # ---- stage 3: fuse. w_dense keeps dense dominant (b_m25 is the tie-breaker
    #              weight) so we never regress on legal paraphrase matching.
    w_dense = 1.0
    w_sparse = settings.bm25_weight
    fused: dict[int, float] = {}
    for rid, rank in dense_rank.items():
        fused[rid] = fused.get(rid, 0.0) + w_dense * _rrf(rank, settings.rrf_k)
    for rid, rank in bm25_rank.items():
        fused[rid] = fused.get(rid, 0.0) + w_sparse * _rrf(rank, settings.rrf_k)

    # Every result must carry content/law/article: lexical-only hits need the row
    from_db = {r["id"]: r for r in rows} if any(
        rid not in dense_by_id for rid in fused
    ) else {}

    results = []
    for rid, rrf in fused.items():
        row = dense_by_id.get(rid) or from_db.get(rid)
        if row is None:
            continue
        item = dict(row)
        # A lexical-only hit was never seen by pgvector, so it has no cosine.
        # Treating "not scored by the dense stage" as 0.0 is what lets the
        # threshold in stage 4 drop it — CRAG then takes over for that question.
        item["similarity"] = float(row.get("similarity", 0.0))
        item["bm25_score"] = round(bm25_by_id.get(rid, 0.0), 3)
        item["dense_rank"] = dense_rank.get(rid)
        item["bm25_rank"] = bm25_rank.get(rid)
        item["rrf_score"] = round(rrf, 6)
        # Same lexical boost as `search.py`, kept for tie-breaking + transparency.
        hits = _keyword_boost(q_tokens, item.get("content", ""))
        item["keyword_hits"] = hits
        item["score"] = item["similarity"] + min(hits * settings.keyword_boost_step,
                                                 settings.keyword_boost_cap)
        results.append(item)

    # ---- stage 4: admission, ordering, cut.
    #
    # ADMISSION IS AN OR, NOT A FILTER. This is the whole point of hybrid
    # retrieval, and getting it wrong is easy: a chunk BM25 loves but the dense
    # stage never returned has NO cosine similarity, so `similarity >= 0.78`
    # would discard it. BM25 would then only ever *reorder* the dense list —
    # which is what `search.py` already did, i.e. no hybrid at all.
    # So a chunk is admitted when EITHER retriever likes it:
    #     similarity >= threshold                (dense liked it)
    #  OR bm25_score >= ratio * best_bm25        (sparse liked it strongly)
    # `bm25_admit_ratio` is RELATIVE to the best lexical hit for this query, so
    # it adapts to the corpus instead of needing an absolute BM25 cut-off.
    best_bm25 = max(bm25_scores, default=0.0)
    admit_floor = best_bm25 * settings.bm25_admit_ratio

    admitted = []
    for r in results:
        if r["similarity"] >= threshold or r["bm25_score"] >= admit_floor:
            r["via"] = ("dense+bm25" if r["dense_rank"] and r["bm25_rank"]
                        else "bm25" if r["bm25_rank"] else "dense")
            admitted.append(r)

    # BUG FOUND BY THE NEW SMOKE TEST: this used to call `rerank_dense()`,
    # which re-sorts by the boosted cosine `score` and therefore threw the RRF
    # ordering away — the fusion decided the candidate set but not the ranking,
    # and a chunk BM25 loved could still be pushed below a pure-vector neighbour.
    # RRF is the ranker here, so it must be the primary sort key; the keyword
    # boost is only a tie-breaker between chunks RRF scored identically.
    admitted.sort(key=lambda x: (x["rrf_score"], x["score"]), reverse=True)
    for r in admitted[:top_k]:
        r.pop("score", None)
    return admitted[:top_k]
