"""Every keyword in the topic->section map must be real Arabic, and the map
must route topics to the ISM section that actually contains them."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.retrieval.ism_scraper import _TOPIC_SECTIONS, _categories_for
from app.retrieval.ism_scraper import list_ism_pdfs

AR = re.compile(r"[\u0600-\u06FF]")

print("=" * 74)
print("1) no stray Latin / mojibake in the map")
print("=" * 74)
bad = 0
for section, kws in _TOPIC_SECTIONS.items():
    for kw in kws:
        if not AR.search(kw) or re.search(r"[A-Za-z]", kw):
            print(f"   BAD keyword {kw!r} in {section}")
            bad += 1
print(f"   {bad} bad keyword(s)" if bad else "   all keywords are clean Arabic")

print()
print("=" * 74)
print("2) does each map key resolve to a REAL ISM category?")
print("   (exact match, or via the longest-shared-prefix resolver)")
print("=" * 74)
from app.retrieval.ism_scraper import _resolve_section
cats = sorted({p["category"] for p in list_ism_pdfs()})
print(f"   live categories: {cats}")
unresolved = 0
for key in _TOPIC_SECTIONS:
    exact = key in cats
    via = _resolve_section(key, cats)
    ok = exact or via is not None
    if not ok:
        unresolved += 1
    how = "exact" if exact else f"prefix -> {via!r}"
    print(f"   [{'ok  ' if ok else 'MISS'}] {key:32} {how}")

print()
print("=" * 74)
print("3) routing: does each question reach the right live section?")
print("=" * 74)
CASES = [
    ("ما هي عقوبة السرقة في القانون المغربي", "المادة الجنائية"),
    ("الحضانة", "المادة الأسرية"),
    ("ما هي حقوق العامل في الشغل", "المادة الاجتماعية"),
    ("شركة تجارية", "المادة التجارية"),
    ("عقد إيجار", "المادة العقارية"),
    ("حماية المعطيات الشخصية", "المادة المدنية"),
    ("ما هو الطقس غدا", None),
]
allok = unresolved == 0
for q, expect in CASES:
    got = _categories_for(q)
    if expect is None:
        allok = allok and not got
        print(f"   {'ok  ' if not got else 'FAIL'} {q[:36]:38} -> {got[:2]} (want none)")
    else:
        good = expect in got
        allok = allok and good
        print(f"   {'ok  ' if good else 'FAIL'} {q[:36]:38} -> {got[:2]}")

print()
print("VERDICT:", "topic map is correct" if allok else "TOPIC MAP IS WRONG")
assert allok
