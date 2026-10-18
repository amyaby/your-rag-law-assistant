"""Verify the robots policy against the real sites, including the User-Agent
trap that makes the naive RobotFileParser.read() approach block maroc.ma."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from urllib.robotparser import RobotFileParser
from app.retrieval import robots

URLS = [
    "https://adala.justice.gov.ma/ar/search?term=%D8%A7%D9%84%D8%B3%D8%B1%D9%82%D8%A9",
    "https://adala.justice.gov.ma/api/uploads/2024/01/17/x.pdf",
    "https://ism.ma/pdf/ARABE/x.pdf",
    "https://www.maroc.ma/",
    "https://www.maroc.ma/fr/actualites",
]

print("=" * 74)
print("1) our robots.allowed() on the real hosts")
print("=" * 74)
for u in URLS:
    print(f"  [{'ALLOW ' if robots.allowed(u) else 'DENY  '}] {u[:66]}")

print()
print("=" * 74)
print("2) the trap: naive RobotFileParser.read() vs our fetch+parse()")
print("=" * 74)
for host in ("https://www.maroc.ma", "https://ism.ma", "https://adala.justice.gov.ma"):
    ru = f"{host}/robots.txt"
    naive = RobotFileParser()
    naive.set_url(ru)
    try:
        naive.read()
        n = naive.can_fetch("*", host + "/")
    except Exception as e:
        n = f"error {type(e).__name__}"

    ours = robots.allowed(host + "/")
    flag = "  <-- MISMATCH" if (n is not ours) else ""
    print(f"  {host:32} naive={str(n):8} ours={str(ours):8}{flag}")

print()
print("=" * 74)
print("3) cache works (2nd call must be instant and identical)")
print("=" * 74)
import time
t0 = time.perf_counter()
a = robots.allowed("https://ism.ma/pdf/ARABE/y.pdf")
t1 = time.perf_counter()
b = robots.allowed("https://ism.ma/pdf/ARABE/z.pdf")
t2 = time.perf_counter()
print(f"  first call {1000*(t1-t0):7.2f} ms  -> {a}")
print(f"  cached    {1000*(t2-t1):7.2f} ms  -> {b}  (no network)")
assert a == b
print("  OK: cached verdict matches, no second fetch")
