from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env"}
    gemini_api_key: str = ""
    llm_model: str = "gemini-2.0-flash"
    embedding_model: str = "gemini-embedding-001"
    database_url: str = "postgresql://postgres:postgres@localhost:5432/assistant"
    top_k: int = 5
    chunk_size: int = 500
    chunk_overlap: int = 100


settings = Settings()