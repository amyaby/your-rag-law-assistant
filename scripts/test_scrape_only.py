"""scripts/test_scrape_only.py — test Adala PDF scraping alone (no local PDFs)"""
import requests, re, json, urllib.parse, fitz, unicodedata, os, subprocess

BASE = "https://adala.justice.gov.ma"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}

# 1. Fetch Adala search page and get a PDF path
query = "08.25"  # a known recent law that exists as PDF
url = f"{BASE}/search?Text={urllib.parse.quote(query)}"
print(f"Fetching {url}")
html = requests.get(url, headers=HEADERS, timeout=10).text
m = re.search(r'"__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
props = json.loads(m.group(1))["props"]["pageProps"]
print(f"searchResult total={props['searchResult']['total']} data len={len(props['searchResult']['data'])}")

# 2. Take first PDF
pdf = props["searchResult"]["data"][0]
print(f"\nFirst PDF: {pdf['name'][:70]}")
print(f" path: {pdf['path']}")
# quote Arabic filename so curl can fetch it (keep /)
pdf_url = f"{BASE}/api/{urllib.parse.quote(pdf['path'], safe='/')}"

# 3. Download to /tmp and extract text
out = "/tmp/scrape_test.pdf"
subprocess.run(["curl","-sL","-A","Mozilla/5.0","-o",out,pdf_url], check=True)
print(f" downloaded {os.path.getsize(out)} bytes to {out}")

doc = fitz.open(out)
text = "".join(p.get_text() for p in doc)
norm = unicodedata.normalize("NFKC", text)
ratio = len(re.findall(r"[\u0600-\u06FF]", norm)) / max(len(norm.strip()),1)
print(f" pages={len(doc)} ratio={ratio:.2f} chars={len(norm.strip())}")
print(f" preview: {norm[:250].replace(chr(10),' | ')}")

if ratio >= 0.70:
    print("\nSCRAPE WORKS — PDF is clean, can be chunked as fallback")
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from app.ingestion.chunker import article_chunks
    chunks = article_chunks(norm, law=pdf["name"][:30])
    print(f" chunked into {len(chunks)} articles, first article={chunks[0]['article']}")
else:
    print("\nPDF is garbled — would need HTML fallback")
