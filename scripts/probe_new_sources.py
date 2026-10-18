"""
Probe the three candidate official portals before wiring any of them in.

For each: does the host resolve, does robots.txt permit us, and does the landing
page serve a real text layer (or is it a JS shell we would have to drive with a
browser)?

Read-only and polite: at most 2 requests per host, spaced, honest UA.
"""
import sys, os, re, socket, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (compatible; MoroccanLawRAG/1.0; educational project)"
H = {"User-Agent": UA, "Accept-Language": "fr,ar;q=0.8"}
GAP = 2.0

SITES = [
    ("sgg.gov.ma", "Secrétariat Général du Gouvernement — Bulletin Officiel"),
    ("cspj.ma", "Conseil Supérieur du Pouvoir Judiciaire — case law"),
    ("pmp.ma", "Présidence du Ministère Public — prosecution texts"),
]


def dns_ok(host):
    try:
        socket.getaddrinfo(host, 443)
        return True, socket.gethostbyname(host)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def probe(host, label):
    print("=" * 74)
    print(f"{host}  —  {label}")
    print("=" * 74)

    ok, info = dns_ok(host)
    print(f"  DNS          : {'resolves -> ' + info if ok else 'FAILS -> ' + info}")
    if not ok:
        print("  VERDICT      : unreachable from here; cannot scrape, cannot verify")
        print()
        return

    # 1) robots.txt
    rp_txt, rp_code, rp_len, rp_kind = None, None, 0, ""
    try:
        r = requests.get(f"https://{host}/robots.txt", headers=H, timeout=20)
        rp_code, rp_len = r.status_code, len(r.content)
        head = r.text[:200].lstrip().lower()
        rp_kind = ("HTML page, not robots" if head.startswith("<!doctype") or head.startswith("<html")
                   else "real robots.txt")
        if rp_code == 200 and rp_kind == "real robots.txt":
            rp_txt = r.text
    except Exception as e:
        rp_code = f"ERR {type(e).__name__}"
    time.sleep(GAP)

    print(f"  robots.txt   : HTTP {rp_code}, {rp_len} bytes, {rp_kind or 'n/a'}")
    if rp_txt:
        dis = [l.strip() for l in rp_txt.splitlines()
               if l.strip().lower().startswith("disallow")]
        print(f"                 Disallow lines: {dis if dis else 'none'}")
        crawl = [l.strip() for l in rp_txt.splitlines()
                 if l.strip().lower().startswith(("crawl-delay", "sitemap"))]
        for c in crawl[:3]:
            print(f"                 {c}")

    # 2) landing page text layer
    try:
        r = requests.get(f"https://{host}/", headers=H, timeout=25)
        code, raw = r.status_code, r.text
    except Exception as e:
        print(f"  homepage     : ERR {type(e).__name__}: {e}")
        print()
        return
    time.sleep(GAP)

    soup = BeautifulSoup(raw, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    scripts = raw.lower().count("<script")
    print(f"  homepage     : HTTP {code}, {len(raw)} bytes html, {scripts} <script> tags")
    print(f"  visible text : {len(text)} chars")
    print(f"  head         : {text[:150]!r}")

    if code != 200:
        print("  VERDICT      : not serving us a page")
    elif len(text) < 300:
        print("  VERDICT      : JS SHELL — no server-rendered text.")
        print("                 requests/BeautifulSoup cannot read it; would need")
        print("                 Playwright/Selenium, i.e. a browser per query.")
    else:
        print("  VERDICT      : server-rendered text available — plain requests can parse it")
    print()


for h, l in SITES:
    probe(h, l)
