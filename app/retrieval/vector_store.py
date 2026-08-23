"""
vector_store.py — PostgreSQL Database Connection
Handles all database operations: creating the documents table,
and inserting chunks with their embeddings. Uses pgvector extension
for vector storage and similarity search.
"""

import json
from app.config import settings
import psycopg

def get_conn():
    return psycopg.connect(settings.database_url)


def create_table():
    with get_conn() as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                content TEXT,
                embedding vector(3072) NOT NULL,
                source TEXT
            );
        """)
        # Stores the original readable passage/text chunk (e.g., a paragraph from a PDF).
        conn.commit()


def insert_chunks(chunks: list[str], embeddings: list[list[float]], source: str = ""):
    data = [(chunk, json.dumps(emb), source) for chunk, emb in zip(chunks, embeddings)]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO documents (content, embedding, source) VALUES (%s, %s::vector, %s)",
                data,
            )
        conn.commit()