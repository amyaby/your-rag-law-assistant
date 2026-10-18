"""
Could marocdroit.com be a real source, not just a one-off PDF rescue?

It gave us a clean 589-article labour code. Before treating it as a source we
need three things:
  1. does robots.txt permit scraping?  (not yet checked)
  2. what else does it host, and is the text article-numbered there too?
  3. is the structure regular enough to automate?

Polite: a handful of spaced requests, honest UA.

VERDICT (recorded after running it, so nobody re-litigates this)
-----------------------------------------------------------
  robots.txt ALLOWS law pages  -> scraping is permitted, no blocker there.
  BUT it is NOT a code library, so it is NOT usable as a source:

    * index-sitemap.xml lists only 65 URLs. A Moroccan legal library has
      thousands. This is a legal-newspaper site.
    * Every homepage link is news or opinion ("قرار المحكمة الدستورية",
      "قانون المحاماة", 2026 dates). Opinion pieces are exactly the material
      the DDG filters exist to keep out.
    * There is no laws section to enumerate: /codes /textes /textes-de-loi
      /lois /droit /sommaire all return 404, and so does /recherche.
      With no index and no search, discovering which law texts it hosts means
      guessing URLs, which does not scale and cannot be maintained.

  Its value was therefore ONE-OFF: it rescued the labour code (589 articles,
  clean, readable) at the exact moment the official PDF was unusable. That
  rescue is now indexed locally, so the remaining gaps (#7, #9, #10) have
  nothing to gain here — those are all covered by ISM today.
"""
import sys, os, re, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (compatible; MoroccanLawRAG/1.0; educational project)")
H = {"User-Agent": UA, "Accept-Language": "fr,ar;q=0.8"}
BASE = "https://www.marocdroit.com"
ART = re.compile(r"(?:المادة|مادة|الفصل|فصل)\s*\d{1,4}")


def get(url):
    return requests.get(url, headers=H, timeout=30)


print("=" * 88)
print("1) robots.txt — THE decisive question")
print("=" * 88)
try:
    r = get(f"{BASE}/robots.txt")
    print(f"  HTTP {r.status_code}, {len(r.content)} bytes")
    body = r.text.lstrip()
    if body.lower().startswith("<!doctype") or body.lower().startswith("<html"):
        print("  HTML page, not a robots file -> no rules published -> allowed by default")
    else:
        print("  " + "-" * 70)
        for line in r.text.splitlines():
            if line.strip():
                print("  " + line.rstrip())
        print("  " + "-" * 70)
except Exception as e:
    print(f"  ERR {type(e).__name__}: {e}")
time.sleep(2)

print()
print("=" * 88)
print("2) what does the site host?")
print("=" * 88)
r = get(f"{BASE}/")
print(f"  HTTP {r.status_code}, {len(r.content)} bytes")
soup = BeautifulSoup(r.text, "html.parser")
print(f"  title: {soup.title.get_text(strip=True) if soup.title else 'n/a'}")

# collect internal links that look like law pages
law_links = {}
for a in soup.find_all("a", href=True):
    href = a["href"]
    txt = a.get_text(" ", strip=True)
    if not txt or len(txt) < 4:
        continue
    if re.search(r"_a\d+\.html$", href) or "/code" in href or "/loi" in href:
        law_links.setdefault(href, txt)
print(f"  law-like links on homepage: {len(law_links)}")
for href, txt in list(law_links.items())[:30]:
    print(f"    {txt[:58]:60} {href[:34]}")

# sitemap is the honest way to enumerate
for sm in ("/sitemap.xml", "/sitemap_index.xml"):
    try:
        rs = get(BASE + sm)
        if rs.status_code == 200 and "<urlset" in rs.text[:400] or "<sitemapindex" in rs.text[:400]:
            n = len(re.findall(r"<loc>", rs.text))
            print(f"\n  {sm}: HTTP 200, {n} urls")
            if n:
                locs = re.findall(r"<loc>(.*?)</loc>", rs.text)[:15]
                for l in locs:
                    print(f"    {l}")
            break
    except Exception:
        pass
    time.sleep(1.5)
