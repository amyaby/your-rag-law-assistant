"""
retriever.py — the single entry point the API and the evaluation harness share

WHY THIS FILE EXISTS
--------------------
`main.py` and `app/evaluation/evaluate.py` both need "the project's retriever".
They previously each picked one themselves:

    main.py      search(query, top_k=10)  +  a hardcoded 0.78 threshold
    evaluate.py  search(query, top_k=10)  +  a hardcoded 0.78 threshold

A duplicate threshold is a duplicate BUG SURFACE: raising the threshold in one
place silently leaves the evaluation reporting numbers for a system that is no
longer deployed. Now both call `retrieve()` and both follow `settings`.

It lives in its own module rather than in `search.py` because `hybrid.py`
imports from `search.py`; putting `retrieve()` there would be a circular import.
"""

from app.config import settings
from app.retrieval.hybrid import hybrid_search
from app.retrieval.search import search


def retrieve(query: str, top_k: int | None = None,
             threshold: float | None = None) -> tuple[list[dict], str]:
    """
    Returns (results, retriever_name).

    retriever_name is echoed in the /ask response and in the evaluation log so
    a report always states WHICH system produced the numbers.
    """
    top_k = top_k or settings.top_k
    threshold = settings.similarity_threshold if threshold is None else threshold

    if settings.use_hybrid:
        return hybrid_search(query, top_k=top_k, threshold=threshold), "hybrid_bm25_rrf"
    return search(query, top_k=top_k, threshold=threshold), "dense_boost"


def crag_needed(results: list[dict], threshold: float | None = None) -> bool:
    """
    Should Corrective RAG fire?

    Uses the best DENSE cosine available, not the top RRF score. A chunk that
    only BM25 found has similarity 0.0 by definition, and treating that as
    "retrieval is fine" would skip CRAG on exactly the questions where the
    vector model failed and we need Adala/ISM the most.
    """
    threshold = settings.similarity_threshold if threshold is None else threshold
    best_dense = max((r.get("similarity", 0.0) for r in results), default=0.0)
    return not results or best_dense < threshold
