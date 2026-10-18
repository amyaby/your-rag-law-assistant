"""article_bonus: does naming an article surface that article?

The failure this fixes: for "عقوبة السرقة" the ISM scraper returned penal code
article 511 (a long article that happens to say "السرقة" and "سنة" repeatedly)
while the article that actually answers theft - 505 - scored LOWER, because 505
is only a couple of lines long. Ask for the article by number and it must win.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.retrieval.relevance import article_bonus, query_articles, relevance

print("=" * 74)
print("1) query_articles() — which numbers did the question name?")
print("=" * 74)
CASES = [
    ("ما هي عقوبة السرقة في القانون المغربي", set()),
    ("عقوبة الفصل 505", {"505"}),
    ("ما يقول الفصل 447-1 من القانون الجنائي", {"447-1"}),
    ("المادة 33 من دستور 2011", {"33"}),
    ("ما هي عقوبة instituted في سنة 2020", set()),   # a year is not an article
]
ok = True
for q, expect in CASES:
    got = query_articles(q)
    good = got == expect
    ok = ok and good
    print(f"   {'ok  ' if good else 'FAIL'} {q[:40]:42} -> {sorted(got)} (want {sorted(expect)})")

print()
print("=" * 74)
print("2) article_bonus() — additive, capped, no match when unasked")
print("=" * 74)
BONUS = [
    ("عقوبة الفصل 505", "505", 0.5,  "exact article match"),
    ("عقوبة الفصل 505", "511", 0.0,  "different article"),
    ("ما يقول الفصل 447-1", "447-1", 0.5, "sub-article exact"),
    ("ما يقول الفصل 447-1", "447-3", 0.2,  "same base number"),
    ("ما هي عقوبة السرقة", "505", 0.0,   "no article asked for"),
    ("ما هي عقوبة السرقة", "", 0.0,     "chunk has no article"),
]
for q, art, expect, why in BONUS:
    got = article_bonus(q, art)
    good = abs(got - expect) < 1e-9
    ok = ok and good
    print(f"   {'ok  ' if good else 'FAIL'} article={art!r:9} bonus={got:.2f} "
          f"(want {expect:.2f})  {why}")

print()
print("=" * 74)
print("2b) a citation to ANOTHER law must not earn this document's bonus")
print("=" * 74)
# Verbatim from the ISM penal-code PDF, which is what made article '511' win a
# theft query: it is article 511 of the COMMERCIAL code, not of this document.
XREF = [
    ("المادة511\n \n من القانون رقم37.97\n المتعلق بمدونة التجارة ال صادر "
     "بتنفيذه ظهير\nشريف \n رقم3."),
    ("الفصل505 من مدونة التجارة"),
    ("عاقب بموجب الفصل 447 من القانون رقم 73-2"),
]
for body in XREF:
    got = article_bonus("عقوبة الفصل 505", "505", body)
    good = got == 0.0
    ok = ok and good
    print(f"   {'ok  ' if good else 'FAIL'} bonus={got:.2f} (want 0.00)  {body[:56]!r}")

# ...but a clean in-document article must still be rewarded
CLEAN = ("الفصل505\n \n كل من سرق "
         "مالا غير مملوك له يعاقب بالحبس")
got = article_bonus("عقوبة الفصل 505", "505", CLEAN)
good = got == 0.5
ok = ok and good
print(f"   {'ok  ' if good else 'FAIL'} bonus={got:.2f} (want 0.50)  in-document article still rewarded")

print()
print("=" * 74)
print("3) the bonus must not outrank a genuinely topical passage on its own")
print("=" * 74)
Q = "ما هي عقوبة الفصل 505 من القانون الجنائي"
on_topic = "السرقة هي Taking/articles نص long ... خمس سنوات"
off_num  = "short article text about other matters entirely"
a = relevance(Q, on_topic) + article_bonus(Q, "505")
b = relevance(Q, off_num)  + article_bonus(Q, "999")
print(f"   topical body + matching number : {a:.3f}")
print(f"   unrelated body + wrong number  : {b:.3f}")
ok = ok and a > b
print(f"   {'ok  ' if a > b else 'FAIL'} the article match reinforces, it does not dominate")

print()
print("VERDICT:", "article_bonus behaves correctly" if ok else "article_bonus IS WRONG")
assert ok
print("VERDICT: ok")
