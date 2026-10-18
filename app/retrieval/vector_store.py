"""
vector_store.py — PostgreSQL / pgvector access layer

Three responsibilities:
  1. Schema: `documents` (the vector index) + `conversations`/`messages` (memory)
  2. IDEMPOTENT ingestion  (bug A2: re-running ingest-all used to double the index)
  3. Memory helpers (turn / read conversation history)

IDEMPOTENCY — what changed and why
----------------------------------
BEFORE
    cur.executemany("INSERT INTO documents (...) VALUES (...)")
    ... a plain INSERT, no uniqueness anywhere. Running `/ingest-all` twice
    produced 10 452 rows for a 5 257-chunk corpus, and the duplicated chunks
    competed for the same top-k slots (the smoke test saw article 507 twice in
    the top 3, hiding article 505).

AFTER
    A unique index on (law, article, md5(content)) + ON CONFLICT ... DO UPDATE.
    Re-ingesting the same PDF now REPLACES the rows instead of duplicating them,
    so ingestion is idempotent and safe to re-run at any time.
"""

import hashlib
import json
import uuid

import psycopg

from app.config import settings


def get_conn():
    return psycopg.connect(settings.database_url)


# ------------------------------------------------------------------ schema ----
def create_table(strict: bool = True):
    """
    Create the schema. Idempotent — safe to call on every startup.

    `strict=False` is used by /reset: the table is empty at that point, so a
    duplicate-guaranteed index cannot fail, and we skip the duplicate probe that
    would otherwise abort startup.
    """
    with get_conn() as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                content TEXT,
                embedding vector(384),
                law TEXT,          -- e.g. "code-penal-2024.pdf"
                article TEXT,      -- e.g. "447-1"
                source TEXT,       -- e.g. "adala.justice.gov.ma"
                version TEXT       -- e.g. "2024-08"
            );
        """)

        # ------------------------------------------------------------------
        # NEW: identity index that makes ingestion idempotent.
        # md5(content) instead of content itself keeps the index small (a
        # 4 000-char chunk would be stored twice in the btree otherwise).
        #
        # NOTE: `md5(content)` is an EXPRESSION, so PostgreSQL requires the
        # identical expression on the left of ON CONFLICT for inference. That
        # is why insert_chunks repeats `md5(content)` verbatim.
        # ------------------------------------------------------------------
        if strict:
            try:
                conn.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS documents_identity
                    ON documents (law, article, md5(content));
                """)
            except psycopg.errors.UniqueViolation:
                # A pre-idempotency index still holds duplicates. Refuse to boot
                # rather than silently serving duplicated chunks.
                conn.rollback()
                raise RuntimeError(
                    "documents_identity: duplicate rows already exist. "
                    "Run POST /reset, then POST /ingest-all."
                ) from None
        else:
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS documents_identity
                ON documents (law, article, md5(content));
            """)

        # ------------------------------------------------------------------
        # NEW: conversation memory (server side, survives refresh + new device)
        # ------------------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'محادثة جديدة',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,               -- 'user' | 'assistant'
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS messages_conversation_idx "
            "ON messages (conversation_id, id);"
        )
        conn.commit()


# --------------------------------------------------------------- ingestion ----
def insert_chunks(chunks: list[dict], embeddings: list[list[float]]):
    """
    Upsert chunks. Same (law, article, content) -> update the embedding instead
    of inserting a second copy. Returns the number of rows written.
    """
    if not chunks:
        return 0

    data = [
        (
            c["content"],
            json.dumps(emb),
            c.get("law") or "",
            c.get("article") or "",
            c.get("source") or "",
            c.get("version") or "",
        )
        for c, emb in zip(chunks, embeddings)
    ]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO documents (content, embedding, law, article, source, version)
                VALUES (%s, %s::vector, %s, %s, %s, %s)
                ON CONFLICT (law, article, md5(content))
                DO UPDATE SET embedding = EXCLUDED.embedding, source = EXCLUDED.source
                """,
                data,
            )
        conn.commit()
    return len(data)


def corpus_stats() -> dict:
    """Cheap fingerprint of the corpus, used to invalidate the BM25 cache."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT count(*), coalesce(max(id), 0) FROM documents"
        ).fetchone()
    return {"chunks": row[0], "max_id": row[1]}


# ------------------------------------------------------------------- memory ----
def create_conversation(title: str = "محادثة جديدة", conv_id: str | None = None) -> str:
    """
    Create a conversation and return its id.

    `conv_id` is optional: when omitted a random hex id is generated. The
    parameter exists because the HTTP layer mints the id itself and needs to
    return it immediately, before any message exists. An earlier version had
    only `title`, and the endpoint passed an id where a title was expected — so
    the id was silently ignored, two different conversations were handed the
    same random id, and the requested title was never stored.
    """
    conv_id = conv_id or uuid.uuid4().hex[:12]
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (conv_id, title),
        )
        conn.commit()
    return conv_id


def conversation_exists(conv_id: str) -> bool:
    with get_conn() as conn:
        return conn.execute(
            "SELECT 1 FROM conversations WHERE id = %s", (conv_id,)
        ).fetchone() is not None


def get_messages(conv_id: str, limit: int) -> list[dict]:
    """The `limit` most recent messages, returned oldest-first for the prompt."""
    if not conv_id or limit <= 0:
        return []
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT role, content FROM (
                SELECT role, content, id FROM messages
                WHERE conversation_id = %s
                ORDER BY id DESC LIMIT %s
            ) t ORDER BY id ASC
            """,
            (conv_id, limit),
        ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in rows]


def add_message(conv_id: str, role: str, content: str) -> None:
    if not conv_id or not content:
        return
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
            (conv_id, role, content),
        )
        # Keep the conversation title useful without a second round-trip
        conn.execute(
            """
            UPDATE conversations SET title = %s
            WHERE id = %s AND title = 'محادثة جديدة'
            """,
            (content.strip().replace("\n", " ")[:48], conv_id),
        )
        conn.commit()


def list_conversations(limit: int = 30) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.title, c.created_at, count(m.id) AS messages
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.created_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [
        {"id": r[0], "title": r[1], "created_at": r[2].isoformat(), "messages": r[3]}
        for r in rows
    ]


def delete_conversation(conv_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = %s", (conv_id,))
        conn.execute("DELETE FROM conversations WHERE id = %s", (conv_id,))
        conn.commit()
