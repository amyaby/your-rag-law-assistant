"""
config.py — Application Settings
Loads environment variables from .env file using pydantic-settings.
All other files import 'settings' from here to get API keys,
model names, database URL, and chunking parameters.

Every tunable number of the project lives HERE and only here, so that
`app/retrieval/search.py` and `app/main.py` can never disagree about
top_k / threshold (see README issue B4).
"""

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_config = {"env_file": ".env"}
    gemini_api_key: str = ""
    llm_model: str = "gemini-3.1-flash-lite"
    embedding_model: str = "intfloat/multilingual-e5-small"
    database_url: str = "postgresql://postgres:alx@localhost:5432/assistant"

    top_k: int = 10
    chunk_size: int = 500
    chunk_overlap: int = 100

    # ---------------------------------------------------------------- retrieval
    similarity_threshold: float = 0.78
    keyword_boost_step: float = 0.02      # added per matching query word
    keyword_boost_cap: float = 0.05       # never boost more than this
    candidate_pool: int = 40              # dense candidates fetched before re-ranking
    bm25_k1: float = 1.5                  # BM25 term-frequency saturation
    bm25_b: float = 0.75                  # BM25 length normalisation (0=none, 1=full)
    rrf_k: int = 60                       # Reciprocal Rank Fusion constant
    bm25_weight: float = 0.35             # 0 = pure dense, 1 = pure lexical
    bm25_admit_ratio: float = 0.6         # a lexical-only hit must score >= this * best BM25

    # ---------------------------------------------------------------- ingestion quality gate
    min_pdf_chars: int = 20_000           # below => scanned PDF with no text layer
    min_pdf_chunks: int = 15              # below => article split failed (broken RTL layer)
    max_avg_chunk_chars: int = 2_500      # above => one blob swallowed the document
    max_article_chars: int = 4_000        # an article longer than this is windowed
    min_pdf_arabic_ratio: float = 0.30    # below => Latin OCR garbage, not Arabic text

    # ---------------------------------------------------------------- LLM resilience
    # VERIFIED 2026-09-27 with probe_models.py against this API key:
    #   OK   : gemini-3.1-flash-lite, gemini-3.5-flash-lite, gemini-3-flash-preview
    #   DEAD : gemini-2.5-flash, gemini-2.5-flash-lite, gemini-2.0-flash
    #          -> 404 "no longer available to new users"
    # The old chain was built from 2.x ids, so every fallback pointed at a model
    # this key cannot load and a transient 503 became a hard failure.
    llm_fallback_models: str = "gemini-3.5-flash-lite,gemini-3-flash-preview"
    llm_max_attempts: int = 3             # transient retries PER MODEL before switching
    llm_backoff_base: float = 1.6         # seconds; attempt n waits base**n

    # ---------------------------------------------------------------- memory
    memory_turns: int = 6                 # how many past messages go into the prompt

    # ---------------------------------------------------------------- Corrective RAG
    allowed_web_domains: str = ".ma,adala.justice.gov.ma,ism.ma,sgg.gov.ma,maroc.ma"
    web_timeout: int = 8
    crag_max_chunks: int = 3               # live chunks accepted from Adala/ISM/web
    # Fraction of the query's *specific* stems a scraped chunk must contain to be
    # trusted. The scrapers match on filenames, which is weak evidence: a live
    # probe of ISM answered a theft question with "التبادل الإلكتروني للمعطيات
    # القانونية" (electronic exchange of legal data). ism.ma is genuinely
    # Moroccan, so the .ma allowlist cannot catch that - only this can.
    # Measured separation on real text: on-topic 0.50, off-topic 0.00.
    crag_min_relevance: float = 0.25

    # ---------------------------------------------------------------- prompt budget
    context_max_chunks: int = 10           # merged DB + scraped chunks fed to the LLM

    # ---------------------------------------------------------------- hybrid
    use_hybrid: bool = True

    @property
    def fallback_models(self) -> list[str]:
        """Comma-separated env string -> list, without the primary model."""
        raw = [m.strip() for m in self.llm_fallback_models.split(",") if m.strip()]
        return [m for m in raw if m != self.llm_model]

    @property
    def allowed_domains(self) -> list[str]:
        return [d.strip().lower() for d in self.allowed_web_domains.split(",") if d.strip()]


settings = Settings()
