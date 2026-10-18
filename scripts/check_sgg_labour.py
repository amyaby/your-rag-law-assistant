"""
The official Bulletin Officiel labour code:
  https://www.sgg.gov.ma/Portals/1/publications/PDFs/127.pdf
  "Code du Travail, Édition 2025, 589 articles"

Test it exactly the way ingestion will: can the article regex find articles?
If yes, this replaces the broken local file and we do NOT need OCR.
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import pymupdf as fitz

from app.ingestion.chunker import article_chunks

URL = "https://www.sgg.gov.ma/Portals/1/publications/PDFs/127.pdf"
ART = re.compile(r"(?:المادة|مادة|الفصل|فصل)\s*\d{1,4}")

# robots: be a good citizen before downloading a 200 KB file
try:
    rr = requests.get("https://www.sgg.gov.ma/robots.txt",
                      headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    body = rr.text[:300].lstrip()
    is_html = body.lower().startswith("<!doctype") or body.lower().startswith("<html")
    print(f"robots.txt: HTTP {rr.status_code} — "
          f"{'HTML, no rules' if is_html else 'real robots.txt'}")
    if not is_html:
        for line in rr.text.splitlines():
            if line.strip():
                print("   ", line.strip())
except Exception as e:
    print(f"robots.txt: ERR {type(e).__name__}")

print()
r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
print(f"download: HTTP {r.status_code}, {len(r.content)} bytes, magic {r.content[:5]}")

d = fitz.open(stream=r.content, filetype="pdf")
print(f"pages: {d.page_count}")
text = "\n".join(p.get_text() for p in d)
d.close()

ar = sum(1 for c in text if "؀" <= c <= "ۿ")
ratio = ar / max(1, len(text))
arts = len(set(ART.findall(text)))
print()
print("=" * 70)
print("INGESTION GATE")
print("=" * 70)
print(f"  chars            : {len(text):>8}   (need >= 20,000)")
print(f"  arabic ratio     : {ratio:>8.1%}   (need >= 30%)")
print(f"  article refs     : {arts:>8}   <-- the one that failed before")
print(f"  'مادة' count    : {text.count('مادة'):>8}")
print(f"  'الفصل' count   : {text.count('الفصل'):>8}")

chunks = article_chunks(text, law="Code du travail 2025", source="sgg:127.pdf")
print(f"  chunks           : {len(chunks):>8}   (need >= 15)")

ok = len(text) >= 20000 and len(chunks) >= 15 and ratio >= 0.30
print()
print(f"  VERDICT: {'USABLE — replaces the broken local file' if ok else 'still unusable'}")

if ok:
    labelled = [c for c in chunks if c.get("article")]
    print(f"  chunks with an article label: {len(labelled)}/{len(chunks)}")
    print()
    print("  sample of extracted text:")
    print("  " + repr(text[3000:3400]))
    nums = sorted({int(x) for x in re.findall(r"(?:المادة|الفصل)\s*(\d{1,4})", text)})
    print()
    print(f"  article numbers found: {len(nums)}, range {nums[:5]}..{nums[-5:]}")
    print(f"  589-article code plausible? {'yes' if len(nums) > 200 else 'NO — suspiciously few'}")
