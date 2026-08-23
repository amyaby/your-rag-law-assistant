"""
llm.py — LLM Answer Generation
Wraps the Gemini chat API. Takes a user question + relevant context
(chunks from the database) and generates a human-readable answer.
The prompt instructs Gemini to only answer based on the provided context.
"""

from google import genai
from app.config import settings

client = genai.Client(api_key=settings.gemini_api_key)


def generate_answer(question: str, context: str) -> str:
    prompt = f"""You are a helpful university assistant.
Answer the question ONLY based on the context below.
If the context doesn't contain the answer, say "I don't have information about that."

Context:
{context}

Question: {question}
Answer:"""

    response = client.models.generate_content(
        model=settings.llm_model,
        contents=prompt,
    )
    return response.text