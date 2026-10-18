"""
Save the clean labour code into data/docs/ and run it through the real gate.

Source: marocdroit.com hosts the full text of loi 65-99 (589 articles) as
article-numbered HTML. The official PDF is unusable (corrupted glyph table) and
ISM publishes the same unusable file, so this is the readable copy.

Saved as .txt so ingestion indexes it through the same article-aware chunker.
"""
import sys, os, re, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from bs4 import BeautifulSoup

from app.ingestion.chunker import chunk_document, pdf_health_check

URL = ("https://www.marocdroit.com/%D9%85%D8%AF%D9%88%D9%86%D8%A9-%D8%A7%D9%84%D8%B4%D8%BA%D9%84-"
       "%D8%A7%D9%84%D9%85%D8%BA%D8%B1%D8%A8%D9%8A%D8%A9_a103.html")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
OUT = "data/docs/قانون 65.99 مدونة الشغل.txt"

# be a good citizen: one request, honest-ish UA, spaced
r = requests.get(URL, headers={"User-Agent": UA, "Accept-Language": "ar,fr;q=0.8"},
                 timeout=30)
print(f"HTTP {r.status_code}, {len(r.content)} bytes")
r.raise_for_status()

soup = BeautifulSoup(r.text, "html.parser")
for t in soup(["script", "style", "noscript", "nav", "header", "footer",
               "form", "aside"]):
    t.decompose()
text = re.sub(r"[ \t]+", " ", soup.get_text("\n", strip=True))

HEADER = (
    "المصدر: marocdroit.com — النص الكامل للقانون رقم 65.99 المتعلق بمدونة الشغل\n"
    "تنفيذه ظهير شريف رقم 1.03.194 بتاريخ 11 سبتمبر 2003، الجريدة الرسمية عدد 5167.\n"
    "ملاحظة: النسخة الرسمية PDF غير قابلة للاستخراج (جدول المحارف تالف)،\n"
    "وهذه نسخة نصية-clean من 589 مادة، وهي ما استُعملت في الفهرسة.\n"
    "HISTORY: fetched to replace مدونة الشغل.pdf, whose glyph table is corrupted\n"
    "(zero occurrences of الفصل/مادة in 316,280 chars). Source is a private\n"
    "site, so treat it as text-of-record for retrieval, not as legal advice.\n"
    + "=" * 70 + "\n\n"
)

os.makedirs("data/docs", exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(HEADER + text)
print(f"saved -> {OUT}  ({os.path.getsize(OUT)} bytes)")

print()
print("=" * 74)
print("THE REAL INGESTION GATE")
print("=" * 74)
ok, reason, stats = pdf_health_check(OUT, "مدونة الشغل (قانون 65.99)")
for k, v in stats.items():
    print(f"  {k:18} = {v}")
print(f"  ok                  = {ok}")
print(f"  reason              = {reason}")

print()
print("=" * 74)
print("DOES IT ACTUALLY CHOP INTO ARTICLES?")
print("=" * 74)
chunks = chunk_document(OUT, law="مدونة الشغل (قانون 65.99)")
labelled = [c for c in chunks if c.get("article")]
print(f"  chunks: {len(chunks)}, with an article label: {len(labelled)}")

Q = "ما هي مدة العطلة السنوية للعامل"
from app.retrieval.relevance import relevance, article_bonus
scored = sorted(((relevance(Q, c["content"]) + article_bonus(Q, str(c.get("article", "")),
                                                              c["content"]), c)
                for c in chunks), key=lambda t: -t[0])
print(f"\n  query: {Q}")
for s, c in scored[:4]:
    print(f"    {s:.3f}  art={str(c.get('article')):>6}  {c['content'][:74]!r}")

print()
print("VERDICT:", "USABLE — the labour code is now indexable"
      if ok and len(labelled) > 50 else "STILL NOT USABLE")
