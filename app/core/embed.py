"""
embed.py — Text to Vector Conversion
Wraps the Gemini embedding API. Takes text (strings) and converts
them to vectors (lists of 3072 numbers). Used in two places:
1. Ingestion: convert PDF chunks before storing in PostgreSQL
2. Search: convert user question to find similar chunks
"""

from google import genai
from app.config import settings

client = genai.Client(api_key=settings.gemini_api_key)

def embed_texts(texts: list[str]) -> list[list[float]]:
    results = client.models.embed_content(
        model=settings.embedding_model,
        contents=texts,
    )
    return [e.values for e in results.embeddings]
#when you only need to embed a single sentence.
def embed_one(text: str) -> list[float]:
    return embed_texts([text])[0]
"""
embed.py — Text to Vector Conversion
Wraps the Gemini embedding API. Takes text (strings) and converts
them to vectors (lists of 3072 numbers). Used in two places:
1. Ingestion: convert PDF chunks before storing in PostgreSQL
2. Search: convert user question to find similar chunks
"""