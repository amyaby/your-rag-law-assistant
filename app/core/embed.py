from sentence_transformers import SentenceTransformer
import unicodedata

from app.config import settings

# Download once (~400MB), then works offline
# SAME model used for both ingestion and query (critical!)
# Read from config so there is a single source of truth for the model id.
model = SentenceTransformer(settings.embedding_model)


def normalize_arabic(text: str) -> str:
    """
    Fix garbled Arabic from PDF extraction.
    PDF fonts often produce presentation-form ligatures/isolated forms
    (e.g. ﺳﻮاء instead of سواء). NFKC maps them back to standard Arabic.
    """
    return unicodedata.normalize("NFKC", text)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Local embeddings — free, unlimited, no quota. For INGESTION.
    Prepends "passage: " (required by multilingual-e5-small, asymmetric model).
    """
    if not texts:
        return []
    # Normalize Arabic + add passage prefix for stored text
    prepared = ["passage: " + normalize_arabic(t) for t in texts]
    vectors = model.encode(prepared, normalize_embeddings=True)
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> list[float]:
    """
    Local embedding for a single QUERY string.
    Prepends "query: " (differs from "passage: " — required by e5 asymmetric model).
    """
    prepared = "query: " + normalize_arabic(text)
    vector = model.encode([prepared], normalize_embeddings=True)
    return vector[0].tolist()


# Keep embed_one as an alias for compatibility
def embed_one(text: str) -> list[float]:
    return embed_query(text)
