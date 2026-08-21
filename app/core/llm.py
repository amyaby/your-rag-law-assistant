import google.generativeai as genai
from app.config import Settings

settings = Settings()
genai.configure(api_key=settings.gemini_api_key)


def chat(messages: list[dict], tools: list = None) -> dict:
    model = genai.GenerativeModel(settings.llm_model)
    chat = model.start_chat(history=[])
    for msg in messages:
        if msg["role"] == "user":
            chat.send_message(msg["content"])
    return {"content": chat.last.text}


def embed_text(text: str) -> list[float]:
    result = genai.embed_content(
        model=f"models/{settings.embedding_model}", content=text
    )
    return result["embedding"]