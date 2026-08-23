"""
config.py — Application Settings
Loads environment variables from .env file using pydantic-settings.
All other files import 'settings' from here to get API keys,
model names, database URL, and chunking parameters.
"""

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_config = {"env_file": ".env"}
    gemini_api_key: str = ""
    llm_model: str = "gemini-3.6-flash"
    embedding_model: str = "gemini-embedding-001"
    database_url: str = "postgresql://postgres:alx@localhost:5432/assistant"
    
    top_k: int = 5
    chunk_size: int = 500
    chunk_overlap: int = 100


settings = Settings()