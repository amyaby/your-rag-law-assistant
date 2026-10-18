"""What do the real robots.txt files say, and do they permit the exact URL
shapes our scrapers fetch? This decides whether the RobotFileParser approach
in the downloaded script is usable at all."""
import requests
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

UA = "Mozilla/5.0 (X11; Linux x86_64)"

# (robots.txt URL, the exact paths each of our scrapers actually requests)
CASES = [
    ("https://adala.justice.gov.ma/robots.txt", [
        "https://adala.justice.gov.ma/ar/search?term=%D8%A7%D9%84%D8%B3%D8%B1%D9%82%D8%A9",
        "https://adala.justice.gov.ma/api/uploads/2024/01/17/x.pdf",
    ]),
    ("https://ism.ma/robots.txt", [
        "https://ism.ma/pdf/ARABE/x.pdf",
    ]),
    ("https://www.maroc.ma/robots.txt", [
        "https://www.maroc.ma/",
        "https://www.maroc.ma/fr/actualites",
    ]),
]

for robots_url, targets in CASES:
    host = urlparse(robots_url).netloc
    print("=" * 74)
    print(f"HOST {host}")
    try:
        r = requests.get(robots_url, headers={"User-Agent": UA}, timeout=15)
        print(f"  raw HTTP {r.status_code}, {len(r.content)} bytes, "
              f"content-type={r.headers.get('Content-Type', '?')}")
    except Exception as e:
        print(f"  raw fetch ERROR {type(e).__name__}: {e}")
        rp = RobotFileParser()
        rp.set_url(robots_url)
        try:
            rp.read()
        except Exception as e2:
            print(f"  parser read also failed: {type(e2).__name__}")
        else:
            print(f"  parser state: allow_all={rp.allow_all} disallow_all={rp.disallow_all}")
        for t in targets:
            print(f"    can_fetch(*, {urlparse(t).path[:38]:40}) = "
                  f"{rp.can_fetch('*', t)}")
        print()
        continue

    if r.status_code != 200:
        print("  -> no robots.txt. Note the body is an HTML error page, which is "
              "wasted bandwidth.")
    else:
        for ln in [l for l in r.text.splitlines() if l.strip()][:12]:
            print("   ", ln)

    rp = RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
    except Exception as e:
        print(f"  parser read error: {e}")
        continue

    print(f"  parser: allow_all={rp.allow_all} disallow_all={rp.disallow_all} "
          f"default_entry={rp.default_entry}")
    for t in targets:
        verdict = rp.can_fetch("*", t)
        flag = "OK  " if verdict else "BLOCKED"
        print(f"    [{flag}] {t[:70]}")
    print()
