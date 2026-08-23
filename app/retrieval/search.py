"""
search.py — Similarity Search
Converts a user question to a vector, then queries PostgreSQL
to find the 5 most similar text chunks using cosine distance.
Returns the chunks with their similarity scores.
"""

import json
from app.retrieval.vector_store import get_conn
from app.core.embed import embed_one
from app.config import settings

def search(query: str, top_k: int = 5) -> list[dict]:
    query_vec = embed_one(query)
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT content, source,
               1 - (embedding <=> %s::vector) AS similarity
        FROM documents
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (json.dumps(query_vec), json.dumps(query_vec), top_k),
    ).fetchall()
    conn.close()
    return [{"content": r[0], "source": r[1], "similarity": r[2]} for r in rows]