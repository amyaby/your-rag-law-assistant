import math
from google import genai
from app.config import settings#Imports Google’s modern, official Gemini SDK.

client = genai.Client(api_key=settings.gemini_api_key)

texts = ["hello world", "what is machine learning", "hello world"]

results = client.models.embed_content(
    model=settings.embedding_model,
    contents=texts,
)

v1 = results.embeddings[0].values
v2 = results.embeddings[1].values
v3 = results.embeddings[2].values

print(results.embeddings)

def cosine(a, b):#a and b are vectors
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b)


print(f"hello vs ML:    {cosine(v1, v2):.4f}")
print(f"hello vs hello: {cosine(v1, v3):.4f}")
