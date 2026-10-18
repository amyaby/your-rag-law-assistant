"""
Coverage matrix for the 10 laws the project is supposed to answer.

Two independent questions per law:
  LOCAL  — is a usable PDF in data/docs (i.e. does the vector index hold it)?
  ISM    — does the live library have it (i.e. can CRAG fetch it at query time)?

Article-level presence is checked, not just the filename: a PDF that opens but
whose text layer cannot yield "الفصل N" is not usable, which is exactly how
مدونة الشغل.pdf failed.

NOTE: PostgreSQL is down, so this measures MATERIAL AVAILABILITY, not live
retrieval. Whether the index actually returns the right chunk for a question is
still unverified.
"""
import sys, os, re, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymupdf as fitz

from app.ingestion.chunker import article_chunks

ART = re.compile(r"(?:المادة|مادة|الفصل|فصل)\s*\d{1,4}")

# (n, law, local filename or None, ISM listing title to look for, probe article)
LAWS = [
    (1,  "القانون الجنائي المغربي",        "code-penal-2024.pdf",            "مجموعة القانون الجنائي", "505"),
    (2,  "مدونة الأسرة",                  "code-famille-70-03.pdf",         "مدونة الأسرة",            None),
    (3,  "مدونة الشغل",                   "قانون 65.99 مدونة الشغل.txt",     "مدونة الشغل",             None),
    (4,  "قانون الالتزامات والعقود",       "obligations-contracts.pdf",       "قانون الالتزامات والعقود", None),
    (5,  "قانون الصحافة والنشر",           "قانون الصحافة والنشر 88.13.pdf", "قانون الصحافة",          None),
    (6,  "قانون 09.08 لحماية المعطيات",   "قانون 09.08 مرسوم تطبيقي.pdf",   "حماية المعطيات",         None),
    (7,  "قانون 53.05 التبادل الإلكتروني", None,                              "التبادل الإلكتروني",     None),
    (8,  "قانون حماية المستهلك 31.08",    "loi-31-08-consommation.pdf",      "حماية المستهلك",         None),
    (9,  "مدونة التجارة",                 None,                              "مدونة التجارة",           None),
    (10, "الملكية الصناعية 17.97",        None,                              "الملكية الصناعية",       None),
]

print("=" * 96)
print("LOCAL CORPUS  (data/docs)")
print("=" * 96)
print(f"{'#':>2}  {'law':34} {'file':32} {'chars':>8} {'arts':>6} {'chunks':>7}  usable")
print("-" * 96)
local_state = {}
for n, law, fn, _t, _a in LAWS:
    if fn is None:
        print(f"{n:>2}  {law:34} {'— NOT IN CORPUS —':32}")
        local_state[n] = ("absent", 0, 0, "")
        continue
    path = os.path.join("data/docs", fn)
    if not os.path.exists(path):
        print(f"{n:>2}  {law:34} {'— FILE MISSING —':32}")
        local_state[n] = ("missing", 0, 0, "")
        continue
    try:
        d = fitz.open(path)
        text = "\n".join(p.get_text() for p in d)
        d.close()
    except Exception as e:
        print(f"{n:>2}  {law:34} {fn[:31]:32} {'OPEN FAIL':>8}")
        local_state[n] = ("broken", 0, 0, "")
        continue
    arts = len(set(ART.findall(text)))
    chunks = article_chunks(text, law=law, source="local")
    # the quality gate the project actually uses
    ar = sum(1 for c in "".join(text) if "؀" <= c <= "ۿ")
    ratio = ar / max(1, len(text))
    usable = len(text) >= 20000 and len(chunks) >= 15 and ratio >= 0.30
    why = "" if usable else (f"chars<20k" if len(text) < 20000
                             else f"chunks<15" if len(chunks) < 15
                             else f"arabic {ratio:.0%}<30%")
    print(f"{n:>2}  {law:34} {fn[:31]:32} {len(text):>8} {arts:>6} {len(chunks):>7}  "
          f"{'YES' if usable else 'NO  <- ' + why}")
    local_state[n] = ("ok" if usable else "rejected", len(text), len(chunks), fn)

print()
print("=" * 96)
print("ISM LIVE LIBRARY (query-time fallback)")
print("=" * 96)
from app.retrieval.ism_scraper import list_ism_pdfs
pdfs = list_ism_pdfs()
print(f"{len(pdfs)} listings indexed\n")
print(f"{'#':>2}  {'law':34} {'in ISM?':9} matching listing")
print("-" * 96)
for n, law, _fn, title, _a in LAWS:
    hits = [p for p in pdfs if title in p["title"]]
    mark = "YES" if hits else "no"
    print(f"{n:>2}  {law:34} {mark:9} {hits[0]['title'][:44] if hits else '—'}")

print()
print("=" * 96)
print("COMBINED — can the bot answer this law at all?")
print("=" * 96)
print(f"{'#':>2}  {'law':34} {'local':22} {'live ISM':10} answerable")
print("-" * 96)
gaps = []
for n, law, fn, title, _a in LAWS:
    st = local_state[n][0]
    loc = {"ok": "YES (indexed)", "rejected": "NO (rejected)",
           "absent": "absent", "missing": "missing", "broken": "broken"}[st]
    ism = "YES" if any(title in p["title"] for p in pdfs) else "no"
    can = st == "ok" or ism == "YES"
    if not can:
        gaps.append(law)
    print(f"{n:>2}  {law:34} {loc:22} {ism:10} {'yes' if can else 'NO'}")
print()
if gaps:
    print("NOT ANSWERABLE:")
    for g in gaps:
        print(f"  - {g}")
else:
    print("Every law on the list is reachable from at least one source.")
