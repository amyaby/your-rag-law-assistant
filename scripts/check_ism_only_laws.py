"""
4 of the 10 laws are ISM-only (no local PDF): 3, 7, 9, 10.
Law 3 is worse — its local copy exists but yields ZERO articles.

Before claiming those 4 are covered, extract the ISM copy and apply the SAME
quality gate. If ISM's مدونة الشغل has the identical RTL problem, then labour
law is not actually answerable and the matrix above is misleading.
"""
import sys, os, re, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import pymupdf as fitz

from app.ingestion.chunker import article_chunks
from app.retrieval.ism_scraper import HEADERS, list_ism_pdfs

ART = re.compile(r"(?:المادة|مادة|الفصل|فصل)\s*\d{1,4}")

TARGETS = {
    3:  "مدونة الشغل",
    7:  "التبادل الإلكتروني",
    9:  "مدونة التجارة",
    10: "الملكية الصناعية",
}

pdfs = list_ism_pdfs()
picked = {}
for n, needle in TARGETS.items():
    for p in pdfs:
        if needle in p["title"]:
            picked[n] = p
            break

print("=" * 92)
print("ISM copies of the ISM-only laws — same gate as local ingestion")
print("=" * 92)
print(f"{'#':>2}  {'title':30} {'chars':>8} {'arts':>6} {'chunks':>7}  verdict")
print("-" * 92)
for n in sorted(picked):
    p = picked[n]
    try:
        r = requests.get(p["url"], headers=HEADERS, timeout=60)
        d = fitz.open(stream=r.content, filetype="pdf")
        text = "\n".join(pg.get_text() for pg in d)
        d.close()
    except Exception as e:
        print(f"{n:>2}  {p['title'][:29]:30} {'FETCH FAIL':>8}  {type(e).__name__}")
        time.sleep(1.5)
        continue
    arts = len(set(ART.findall(text)))
    chunks = article_chunks(text, law=p["title"], source=f"ism:{p['url']}")
    ar = sum(1 for c in text if "؀" <= c <= "ۿ")
    ratio = ar / max(1, len(text))
    ok = len(text) >= 20000 and len(chunks) >= 15 and ratio >= 0.30
    why = "" if ok else ("chars<20k" if len(text) < 20000
                         else "chunks<15 — article split failed" if len(chunks) < 15
                         else f"arabic {ratio:.0%}<30%")
    print(f"{n:>2}  {p['title'][:29]:30} {len(text):>8} {arts:>6} {len(chunks):>7}  "
          f"{'USABLE' if ok else 'UNUSABLE <- ' + why}")
    time.sleep(1.5)

print()
print("=" * 92)
print("Sanity: does the article regex find anything in the known-good penal code?")
print("=" * 92)
d = fitz.open("data/docs/code-penal-2024.pdf")
t = "\n".join(p.get_text() for p in d)
d.close()
print(f"   local code-penal-2024.pdf: {len(set(ART.findall(t)))} distinct article refs")
print("   -> if that is large and the labour code is 0, the labour PDF's text")
print("      layer is broken, not the regex.")
