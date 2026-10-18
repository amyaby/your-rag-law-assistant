"""
Find a CLEAN copy of the Moroccan labour code (loi 65-99).

Candidate sources, tested the way ingestion tests them: can we get
article-level text out, i.e. does "المادة N" appear many times?

  A) marocdroit.com  — full text of loi 65-99 as HTML, article-numbered
  B) qanoun.net       — offers a PDF download of the labour code
  C) sgg.gov.ma       — Bulletin Officiel (already ruled out: catalogue page)

An HTML source is acceptable: the Adala scraper already produces chunks from
HTML, so a clean HTML page is as usable as a clean PDF and cannot have a
corrupted glyph table.
"""
import sys, os, re, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
H = {"User-Agent": UA, "Accept-Language": "ar,fr;q=0.8"}

ART = re.compile(r"(?:المادة|مادة|الفصل|فصل)\s*\d{1,4}")


def arabic_ratio(s):
    ar = sum(1 for c in s if "؀" <= c <= "ۿ")
    return ar / max(1, len(s))


def probe(url, label):
    print("=" * 88)
    print(f"{label}")
    print(f"  {url}")
    print("=" * 88)
    try:
        r = requests.get(url, headers=H, timeout=30)
    except Exception as e:
        print(f"  FETCH FAIL: {type(e).__name__}: {str(e)[:100]}")
        return None
    print(f"  HTTP {r.status_code}, {len(r.content)} bytes, encoding {r.encoding}")
    if r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        t.decompose()
    text = re.sub(r"[ \t]+", " ", soup.get_text("\n", strip=True))

    arts = len(set(ART.findall(text)))
    ratio = arabic_ratio(text)
    nums = sorted({int(x) for x in re.findall(r"المادة\s*(\d{1,4})", text)})

    print(f"  visible text : {len(text)} chars")
    print(f"  arabic ratio : {ratio:.1%}")
    print(f"  'مادة' count: {text.count('مادة')}")
    print(f"  article refs : {arts} distinct")
    if nums:
        print(f"  article nums : {len(nums)}  range {nums[0]}..{nums[-1]}")
        gaps = [n for n in range(1, 60) if n not in nums]
        print(f"  missing 1-59 : {gaps if gaps else 'none — dense numbering'}")

    # is the text real Arabic or scrambled?
    sample = text[3000:3300] if len(text) > 3300 else text[:300]
    print(f"  sample       : {sample[:200]!r}")

    good = arts >= 100 and ratio >= 0.5
    print(f"  VERDICT      : {'USABLE' if good else 'not usable'}")
    return {"url": url, "text": text, "arts": arts, "ratio": ratio,
            "nums": nums, "usable": good}


print()
best = probe("https://www.marocdroit.com/%D9%85%D8%AF%D9%88%D9%86%D8%A9-"
             "%D8%A7%D9%84%D8%B4%D8%BA%D9%84-%D8%A7%D9%84%D9%85%D8%BA%D8%B1%D8%A8%D9%8A"
             "%D8%A9_a103.html", "A) marocdroit.com — full text of loi 65-99")
time.sleep(2)

print()
lb = probe("https://qanoun.net/labor-law/", "B) qanoun.net — offers a PDF download")

print()
print("=" * 88)
print("SUMMARY")
print("=" * 88)
if best and best["usable"]:
    print(f"  marocdroit.com is USABLE: {best['arts']} articles, "
          f"{len(best['text'])} chars, arabic {best['ratio']:.0%}")
    print(f"  highest article found: {best['nums'][-1] if best['nums'] else '?'} "
          f"(the code has 589)")
else:
    print("  no clean source yet")
