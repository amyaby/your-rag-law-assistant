"""Verify the AFC chatter is gone on a real call, and capture token usage."""
import io
from contextlib import redirect_stderr, redirect_stdout

Q = "ما هي عقوبة السرقة في القانون المغربي؟"
CTX = ("المادة 505 من القانون الجنائي: من أخذ شيئا ليس له بقوة. "
       "يعاقب بالسجن من سنة إلى خمس سنوات وبغرامة.")

buf_out, buf_err = io.StringIO(), io.StringIO()

with redirect_stdout(buf_out), redirect_stderr(buf_err):
    from app.core.llm import _generate, generate_answer
    answer = generate_answer(Q, context=CTX)
    _text, model = _generate("ping", "reply with one word")

combined = buf_out.getvalue() + buf_err.getvalue()
afc = [ln for ln in combined.split("\n")
       if "AFC" in ln or "automatic function calling" in ln]

print("=" * 70)
print("AFC CHECK (real call through app.core.llm)")
print("=" * 70)
print(f"answer length : {len(answer)} chars")
print(f"answer        : {answer[:90]}")
print(f"model used    : {model}")
print(f"AFC lines     : {len(afc)}")
for ln in afc:
    print("   !", ln[:140])
print("VERDICT       :", "AFC suppressed" if not afc else "AFC STILL PRESENT")
print(f"captured app stdout: {combined.strip()[:160] or '(empty)'}")

print()
print("=" * 70)
print("TOKEN USAGE (closes the F5 logging gap)")
print("=" * 70)
from google import genai
from app.config import settings
c = genai.Client(api_key=settings.gemini_api_key)
r = c.models.generate_content(model=settings.llm_model, contents="قل: مرحبا")
um = r.usage_metadata
for f in ("prompt_token_count", "candidates_token_count", "total_token_count",
          "thoughts_token_count", "cached_content_token_count"):
    print(f"   {f:32} = {getattr(um, f, 'n/a')}")
