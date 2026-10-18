"""End-to-end: the real question is whether CRAG refuses a bad source and
falls through to a good one, instead of returning the first nonempty answer."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.retrieval.corrective import corrective_search

Q = "عقوبة السرقة في القانون المغربي"
print("=" * 70)
print(f"corrective_search({Q!r})")
print("=" * 70)
chunks = corrective_search(Q, max_chunks=3)
print(f"\nFINAL: {len(chunks)} chunk(s)")
for c in chunks:
    print(f"\n  source    : {str(c.get('source',''))[:78]}")
    print(f"  law       : {str(c.get('law',''))[:60]}")
    print(f"  relevance : {c.get('relevance')}")
    print(f"  content   : {c.get('content','')[:200]}")
