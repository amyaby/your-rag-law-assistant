"""The new ISM selection is relevance-scored instead of substring-matched.
Check it still finds the documents it SHOULD, not just rejects the bad ones."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.retrieval.ism_scraper import list_ism_pdfs
from app.retrieval.relevance import relevance

pdfs = list_ism_pdfs()
print(f"listings: {len(pdfs)}")

# (query, should a listing be TITLED after this query?)
#
# Note what is NOT in this list: "الحضانة". It is the most common family-law
# question and it used to be asserted True here, which failed - correctly.
# No listing is titled "حضانة" (0 of 160), and none ever will be: the library
# lists codebooks, not topics. Custody is a CHAPTER inside "مدونة الأسرة", so
# the right expectation is a category-route, which test_ism_topics.py checks.
# Asserting a titled listing here would encode the bug.
CASES = [
    ("مدونة الأسرة", True),
    ("مدونة الشغل", True),
    ("القانون الجنائي", True),
    ("التجاري", True),
    ("التبادل الإلكتروني للمعطيات", True),
    ("ما هو الطقس غدا في الرباط", False),
    ("كيفاش نطبخ البسطيلة", False),
]

print()
print(f"{'query':42} {'expected':9} {'best':>7}  {'hits>=0.25':>10}  top title")
print("-" * 100)
ok = True
for q, expect in CASES:
    scored = sorted(
        ((relevance(q, f"{p['title']} {p['category']}"), p) for p in pdfs),
        key=lambda t: -t[0],
    )
    best, bp = scored[0]
    hits = [s for s, _ in scored if s >= 0.25]
    good = (len(hits) > 0) == expect
    ok = ok and good
    mark = "ok " if good else "FAIL"
    print(f"{mark} {q:39} {str(expect):9} {best:7.3f}  {len(hits):10}  {bp['title'][:34]}")

print()
print("VERDICT:", "selection behaves correctly" if ok else "SELECTION IS WRONG")
