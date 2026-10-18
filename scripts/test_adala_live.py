"""Live end-to-end: does the theft question now reach a real Adala document?"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.retrieval.scraper import scrape_adala_text

Q = "عقوبة السرقة في القانون المغربي"

print("=" * 70)
print(f"scrape_adala_text({Q!r})")
print("=" * 70)
chunks = scrape_adala_text(Q, max_chunks=3)
print(f"\nRESULT: {len(chunks)} chunk(s)")
for c in chunks:
    print(f"\n  law      : {c.get('law','')[:60]}")
    print(f"  article  : {c.get('article','')!r}")
    print(f"  relevance: {c.get('relevance')}")
    print(f"  source   : {str(c.get('source',''))[:80]}")
    print(f"  content  : {c.get('content','')[:220]}")
print()
