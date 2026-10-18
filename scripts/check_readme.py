"""Validate README structure: code fences, tables, anchors."""
import re
from collections import Counter
from pathlib import Path

lines = Path("README.md").read_text(encoding="utf-8").split("\n")
problems = []

# ------------------------------------------------------- 1. code fences ----
fences = [i for i, ln in enumerate(lines, 1) if ln.lstrip().startswith("```")]
if len(fences) % 2:
    problems.append(f"UNBALANCED code fences: {len(fences)} markers (odd)")
    for a, b in zip(fences[::2], fences[1::2]):
        if b - a > 400:
            problems.append(f"  suspiciously long fence block: line {a} -> {b}")
else:
    print(f"code fences    : {len(fences)} markers = {len(fences)//2} blocks, balanced")

# ---------------------------------------------------------- 2. tables -----
# must ignore pipe characters inside fenced code blocks (ASCII diagrams)
in_fence = False
masked = []
for ln in lines:
    if ln.lstrip().startswith("```"):
        in_fence = not in_fence
        masked.append("")
        continue
    masked.append("" if in_fence else ln)

bad_tables = 0
tables = 0
i = 0


def npipes(ln):
    # a "\|" inside a code span is a literal pipe, not a cell separator
    return ln.replace("\\|", "").count("|")


while i < len(masked):
    if masked[i].startswith("|") and i + 1 < len(masked) and re.match(r"^\|[\s:|-]+\|$", masked[i + 1]):
        tables += 1
        ncol = npipes(masked[i])
        j = i + 2
        while j < len(masked) and masked[j].startswith("|"):
            if npipes(masked[j]) != ncol:
                problems.append(f"line {j+1}: table row has {npipes(masked[j])} pipes, header has {ncol}")
                problems.append(f"    {masked[j][:100]}")
                bad_tables += 1
            j += 1
        i = j
    else:
        i += 1
print(f"tables         : {tables} found, {bad_tables} malformed rows")

# ------------------------------------------------- 3. internal anchors ----
def slug(h):
    # GitHub's algorithm: lowercase, drop everything that is not a word
    # character / space / hyphen, then turn each space into a hyphen.
    # Note: an emoji heading keeps its leading hyphen -- that is expected.
    s = h.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    return s.replace(" ", "-")

headings = {slug(ln.lstrip("#").strip()) for ln in lines if re.match(r"^#{1,6} ", ln)}
links = re.findall(r"\]\(#([^)]+)\)", "\n".join(lines))
broken = sorted({l for l in links if l not in headings})
print(f"internal links : {len(links)} found, {len(set(links))} unique")
if broken:
    for b in broken:
        near = [h for h in headings if b.split("-")[0] in h][:3]
        problems.append(f"broken anchor: #{b}   (candidates: {near})")

# ------------------------------------------------------ 4. stale markers --
stale = [f"line {i+1}: {ln[:90]}"
         for i, ln in enumerate(lines)
         if "✅ fixed ✅" in ln or "⬜ open ⬜" in ln or ln.rstrip() != ln.rstrip(" |") and ln.startswith("| ") and not ln.endswith("|")]
if stale:
    for s in stale:
        problems.append("malformed table row -> " + s)

# --------------------------------------------- 5. fix-count consistency ---
print(f"lines          : {len(lines)}")
# Change sections are `## Change N — ...` (h2) and `### 🔎 Change N — ...` (h3).
_change = re.compile(r"^#{2,3} (?:🔎 )?Change \d+ ")
print(f"'Change N —'   : {sum(1 for ln in lines if _change.match(ln))} change sections")

print()
if problems:
    print(f"PROBLEMS ({len(problems)}):")
    for p in problems:
        print("  -", p)
else:
    print("README STRUCTURE: OK — no problems found")
