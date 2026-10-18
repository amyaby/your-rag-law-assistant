#!/usr/bin/env python
"""
Validate PGVECTOR_GUIDE.md.

Stronger than a lint pass: for every `file.py:N-M` reference we assert that the
*named function* actually appears inside the cited range, so a line number can
never silently drift again.
"""
import re, ast, pathlib, sys

root = pathlib.Path("/home/im_ane/ai-uni-assistant")
doc = root / "PGVECTOR_GUIDE.md"
text = doc.read_text(encoding="utf-8")
lines = text.splitlines()
fails = []

def hdr(n): print("\n" + "=" * 72 + f"\n{n}\n" + "=" * 72)

# ---------------------------------------------------------------- 1
hdr("1) residual corrupted sample data (CJK inside code, stray latin tokens)")
BAD_TOKENS = ("Congestion", "Urbano", "JoliotTuring", "uqaci", "AnnotatedAnnotations",
              "GeneticFamilyRelations", "placeholder removed below", "计算机")
bad = []
for i, l in enumerate(lines, 1):
    for t in BAD_TOKENS:
        # Appendix B deliberately names the corrupted strings inside backticks
        if t in l and "`" not in l:
            bad.append((i, t, l))
    if re.search(r"[\u4e00-\u9fff\u3040-\u30ff]", l) and "`" not in l:
        bad.append((i, "CJK", l))
for i, t, l in bad:
    print(f"   line {i} [{t}]: {l.strip()[:90]}")
if not bad: print("   clean")
else: fails.append(f"{len(bad)} corrupted line(s)")

# ---------------------------------------------------------------- 2
hdr("2) fence balance + language tags")
fences = [(i, l.strip().split()[0][3:] if l.strip().startswith("```") and len(l.strip()) > 3 else "")
          for i, l in enumerate(lines, 1) if l.strip().startswith("```")]
print(f"   {len(fences)} fence markers -> {'balanced' if len(fences)%2==0 else 'UNBALANCED'}")
if len(fences) % 2: fails.append("unbalanced fences")

# ---------------------------------------------------------------- 3
hdr("3) python blocks parse (ast.parse)")
blocks = re.findall(r"^```python\n(.*?)^```", text, re.S | re.M)
print(f"   {len(blocks)} python blocks")
nbad = 0
for n, b in enumerate(blocks, 1):
    try:
        ast.parse(b)
    except SyntaxError as e:
        nbad += 1
        bl = b.splitlines()
        print(f"   block {n}: line {e.lineno}: {e.msg}")
        if e.lineno and e.lineno <= len(bl):
            print(f"        >> {bl[e.lineno-1].strip()[:95]}")
print("   all parse" if nbad == 0 else f"   {nbad} failed")
if nbad: fails.append(f"{nbad} unparseable python block(s)")

# ---------------------------------------------------------------- 4
hdr("4) sql blocks: paren balance (comments stripped), reporting any imbalance")
sqls = re.findall(r"^```sql\n(.*?)^```", text, re.S | re.M)
print(f"   {len(sqls)} sql blocks")


def strip_sql_comments(s: str) -> str:
    """Drop `--` comments: a label like `-- A)` carries a paren that is not SQL."""
    return "\n".join(re.sub(r"--.*$", "", ln) for ln in s.splitlines())


nbad = 0
for n, s in enumerate(sqls, 1):
    bare = strip_sql_comments(s)
    if bare.count("(") != bare.count(")"):
        nbad += 1
        print(f"   block {n}: ( ={bare.count('(')}  ) ={bare.count(')')}")
        for bl in s.strip().splitlines():
            print(f"        {bl}")
if not nbad: print("   all balanced")
else: fails.append(f"{nbad} sql block(s) paren-imbalanced")

# ---------------------------------------------------------------- 5
hdr("5) TOC / inline anchors resolve (GitHub slug algorithm)")
def gh_slug(h):
    s = h.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.U)
    return s.replace(" ", "-")
heads = {}
for l in lines:
    m = re.match(r"^#{1,6} (.*)$", l)
    if m:
        t = m.group(1).strip().strip("*")
        heads.setdefault(gh_slug(t), t)
links = re.findall(r"\]\(#([^)]+)\)", text)
missing = sorted({a for a in links if a not in heads})
print(f"   {len(links)} anchor refs, {len(set(links))} unique, {len(missing)} unresolved")
for a in missing: print(f"   MISSING: #{a}")
if missing: fails.append(f"{len(missing)} broken anchor(s)")

# ---------------------------------------------------------------- 6
hdr("6) file:line refs — cited range must CONTAIN the named function")
REFS = [
    ("search.py",        57, 81,  "dense_candidates"),
    ("vector_store.py",  48, 58,  "CREATE TABLE IF NOT EXISTS documents"),
    ("vector_store.py",  65, 67,  "md5(content)` is an EXPRESSION"),
    ("vector_store.py",  69, 87,  "if strict:"),
    ("vector_store.py",  71, 74,  "documents_identity"),
    ("vector_store.py",  75, 82,  "UniqueViolation"),
    ("vector_store.py",  92, 111, "CREATE TABLE IF NOT EXISTS conversations"),
    ("vector_store.py", 136, 148, "executemany"),
    ("vector_store.py", 151, 157, "def corpus_stats"),
]
CAND = {
    "search.py":       ["app/retrieval/search.py"],
    "vector_store.py": ["app/retrieval/vector_store.py"],
    "embed.py":        ["app/core/embed.py"],
    "hybrid.py":       ["app/retrieval/hybrid.py"],
}
nbad = 0
for fname, a, b, needle in REFS:
    fp = root / CAND[fname][0]
    src = fp.read_text(encoding="utf-8").splitlines()
    seg = "\n".join(src[a - 1:b])
    ok = needle in seg
    print(f"   {'OK ' if ok else 'BAD'} {fname}:{a}-{b}  contains {needle!r}"
          f"{'' if ok else '   <-- DRIFT'}")
    if not ok:
        nbad += 1
        print(f"        actual {a}-{b}: {src[a-1].strip()[:70]!r}")
if not nbad: print("   all references land on the right code")
else: fails.append(f"{nbad} drifted line reference(s)")

# ---------------------------------------------------------------- 7
hdr("7) single-line refs in prose are in range")
for m in re.finditer(r"`(?:app/)?(?:retrieval/|core/)?(\w+\.py):(\d+)(?:-(\d+))?`", text):
    f, a, b = m.group(1), int(m.group(2)), m.group(3)
    cands = CAND.get(f) or [f"app/{f}", f"app/retrieval/{f}", f"app/core/{f}"]
    fp = next((root / c for c in cands if (root / c).exists()), None)
    if not fp:
        print(f"   UNRESOLVED {f}:{a}"); fails.append("unresolved ref"); continue
    n = len(fp.read_text(encoding="utf-8").splitlines())
    hi = int(b or a)
    if hi > n:
        print(f"   OUT OF RANGE {f}:{a}{'-'+b if b else ''} (file has {n})")
        fails.append("out-of-range ref")
print("   checked")

# ---------------------------------------------------------------- 8
hdr("8) paths referenced exist")
paths = sorted(set(re.findall(r"`((?:app|scripts|data)/[\w/\.\u0600-\u06FF-]+\.(?:py|sql|md|txt|pdf))`", text)))
miss = 0
for p in paths:
    if "*" in p: continue
    if not (root / p).exists():
        print(f"   MISSING {p}"); miss += 1
print(f"   {len(paths)} referenced paths, {miss} missing")
if miss: fails.append(f"{miss} missing path(s)")

# ---------------------------------------------------------------- 9
hdr("9) the three corrected claims must be stated correctly")
CHECKS = [
    ("float8 not Decimal", "unpack_float8(data)[0]"),
    ("lists has NO default", "no default"),
    ("lists heuristic rows/1000", "rows / 1000"),
    ("ANN failure is SILENT", "silently fewer rows"),
    ("probes=lists gives exact", "exact"),
    ("zero vectors excluded", "Zero vectors invisible to cosine"),
    ("10k is OUR rule of thumb", "our project rule of thumb, not a pgvector constant"),
    ("ivfflat.iterative_scan", "ivfflat.iterative_scan"),
]
for label, needle in CHECKS:
    ok = needle in text
    print(f"   {'OK ' if ok else 'BAD'} {label}")
    if not ok: fails.append(f"missing correction: {label}")

# ---------------------------------------------------------------- done
print("\n" + "=" * 72)
if fails:
    print("RESULT: FAIL")
    for f in fails: print("  -", f)
    sys.exit(1)
print("RESULT: ALL CHECKS PASS")
