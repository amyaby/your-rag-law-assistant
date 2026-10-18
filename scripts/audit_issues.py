"""Audit: which README issues are actually fixed, and is the code evidence there?"""
import re
from pathlib import Path

readme = Path("README.md").read_text(encoding="utf-8")
rows = []
for ln in readme.split("\n"):
    m = re.match(r"^\| ([A-G]\d) \| (.+?) \| (.+?) \| (.+?) \|$", ln)
    if m:
        rows.append((m.group(1), m.group(2), m.group(3), m.group(4)))

fixed = [r for r in rows if r[3].startswith("✅")]
open_ = [r for r in rows if r[3].startswith("⬜")]
part = [r for r in rows if r[3].startswith("🟡")]
skipped = [r for r in rows if r[3].startswith("🚫")]
print(f"total issues: {len(rows)}   fixed: {len(fixed)}   open: {len(open_)}   "
      f"partial: {len(part)}   dropped: {len(skipped)}\n")

print("=== STILL OPEN (not done) ===")
for k, d, s, st in open_:
    print(f"  {k:3} {st:34} {d[:62]}")
for k, d, s, st in part:
    print(f"  {k:3} {st:34} {d[:62]}")
for k, d, s, st in skipped:
    print(f"  {k:3} {st:34} {d[:62]}")

# ---- verify each claimed fix has real code evidence ----
print("\n=== CODE EVIDENCE FOR EACH 'FIXED' CLAIM ===")
EVIDENCE = {
    "A1": ("app/ingestion/chunker.py", r"def pdf_health_check"),
    "A2": ("app/retrieval/vector_store.py", r"ON CONFLICT \(law, article, md5\(content\)\)"),
    "A3": ("app/ingestion/chunker.py", r"\\s\*\(.*المادة"),
    "A4": ("app/main.py", r"law="),
    "A5": ("app/core/embed.py", r"passage: |query: "),
    "A6": ("app/core/embed.py", r"NFKC"),
    "B1": ("app/retrieval/search.py", r"def search"),
    "B2": ("app/retrieval/search.py", r"score\]\s*>=\s*threshold|\"score\"\] >= threshold"),
    "B3": ("app/retrieval/search.py", r"content_tokens"),
    "B4": ("app/retrieval/retriever.py", r"def retrieve"),
    "B5": ("app/retrieval/hybrid.py", r"1.0 / \(.*rrf_k|/ \(rrf_k \+"),
    "C1": ("app/core/llm.py", r"llm_fallback_models|llm_model_fallbacks"),
    "C2": ("app/core/llm.py", r"except Exception"),
    "C3": ("app/core/llm.py", r"_is_retryable|is_retryable"),
    "C4": ("app/core/llm.py", r"for m_i, model in enumerate\(_model_chain\(\)\)"),
    "C5": ("app/core/llm.py", r"google_genai\.models"),
    "D1": ("app/retrieval/web_search.py", r"def _is_allowed"),
    "D2": ("app/retrieval/scraper.py", r"def _search_terms"),
    "D3": ("app/retrieval/web_search.py", r"ThreadPoolExecutor"),
    "D5": ("app/retrieval/corrective.py", r"def _filter_relevant"),
    "F1": ("app/evaluation/evaluate.py", r"known_gap"),
    "F2": ("app/evaluation/evaluate.py", r"isinstance\(fact, \(list, tuple\)\)"),
    "F4": ("app/evaluation/evaluate.py", r"_is_failure|not cached"),
    "F5": ("app/main.py", r"def log\("),
    "G1": ("app/retrieval/vector_store.py", r"CREATE TABLE IF NOT EXISTS conversations"),
    "E2": ("app/main.py", r"reset"),
    "E3": ("README.md", r"PYTHONPATH|python -m"),
    "E4": ("app/ingestion/chunker.py", r"import pymupdf as fitz"),
}
missing = []
for k, d, s, st in fixed:
    path, pat = EVIDENCE.get(k, (None, None))
    if not path:
        print(f"  {k:3} (no evidence rule)  {d[:56]}")
        continue
    p = Path(path)
    if not p.exists():
        missing.append((k, path, "FILE MISSING"))
        print(f"  {k:3} !! {path} does not exist")
        continue
    hit = re.search(pat, p.read_text(encoding="utf-8"), re.S)
    print(f"  {k:3} {'OK  ' if hit else '!!  '} {path:38} {d[:40]}")
    if not hit:
        missing.append((k, path, pat))

print(f"\nverified: {len(fixed) - len(missing)}/{len(fixed)} fixed claims have code evidence")
if missing:
    print("UNVERIFIED:")
    for m in missing:
        print("   ", m)
