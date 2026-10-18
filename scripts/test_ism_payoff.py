"""Does the ISM source now return the REAL penal code article for theft?
This is the payoff check for the category-parsing + topic-map work."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.retrieval.ism_scraper import scrape_ism_text
from app.retrieval.relevance import relevance

Q = os.environ.get("Q", "ما هي عقوبة السرقة في القانون المغربي؟")
print("=" * 74)
print(f"scrape_ism_text({Q!r})")
print("=" * 74)
chunks = scrape_ism_text(Q, max_chunks=5)
print(f"\n{len(chunks)} chunk(s)")
for c in chunks:
    body = c.get("content", "")
    print(f"\n  law       : {c.get('law')}")
    print(f"  article   : {c.get('article')!r}")
    print(f"  relevance : {c.get('relevance')}   (body re-scored: {relevance(Q, body):.3f})")
    print(f"  source    : {str(c.get('source'))[:70]}")
    print(f"  content   : {body[:260]}")

print()
print("=" * 74)
print("Does any returned chunk actually mention the theft article?")
print("=" * 74)
for c in chunks:
    body = c.get("content", "")
    hit505 = "505" in body
    words = [w for w in ("505", "السرقة", "اختلاس", "سنة", "خمس") if w in body]
    print(f"   mentions {words}  505={hit505}  article={c.get('article')!r}")
