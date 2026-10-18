"""
Do we actually need a NEW pdf for مدونة الشغل, or is our EXTRACTOR wrong?

PyMuPDF reports 0 "الفصل N" matches in a 316k-char labour code, while the same
regex finds 659 in the penal code. Two competing explanations:

  H_ext  the text layer is fine and PyMuPDF's default reading order destroys it
         (RTL glyphs stored in visual order) -> a different extractor fixes it
  H_pdf  the glyphs really are broken/scrambled  -> only a new file helps

This matters a lot: H_ext means no new PDF hunt, H_pdf means the user has to
find a publisher. Try the cheap fixes first.
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymupdf as fitz

ART = re.compile(r"(?:المادة|مادة|الفصل|فصل)\s*\d{1,4}")
PATH = "data/docs/مدونة الشغل.pdf"
CONTROL = "data/docs/code-penal-2024.pdf"


def score(name, text):
    arts = len(set(ART.findall(text)))
    ar = sum(1 for c in text if "؀" <= c <= "ۿ")
    ratio = ar / max(1, len(text))
    return f"{name:38} chars={len(text):>7}  arts={arts:>5}  arabic={ratio:5.1%}"


doc = fitz.open(PATH)
print(f"{PATH}  ({doc.page_count} pages)")
print("=" * 96)
print("EXTRACTION METHODS on the existing labour PDF")
print("=" * 96)

# 1) current default
print(score("1 pymupdf get_text()  [current]", "\n".join(p.get_text() for p in doc)))

# 2) sorted reading order - the classic fix for multi-column/RTL layout
print(score("2 pymupdf sort=True", "\n".join(p.get_text(sort=True) for p in doc)))

# 3) blocks mode
print(score("3 pymupdf get_text('blocks')",
            "\n".join(b[4] for p in doc for b in p.get_text("blocks") if len(b) > 4)))

# 4) rawdict -> rebuild from character positions, sorted by position ourselves
try:
    out = []
    for p in doc:
        d = p.get_text("rawdict")
        lines = []
        for blk in d.get("blocks", []):
            for ln in blk.get("lines", []):
                s = "".join(sp.get("c", "") for sp in ln.get("spans", []))
                if s.strip():
                    lines.append(s)
        out.append("\n".join(lines))
    print(score("4 pymupdf rawdict, rebuilt lines", "\n".join(out)))
except Exception as e:
    print(f"4 rawdict failed: {type(e).__name__}: {e}")

# 5) words mode, joined - often survives when line reconstruction fails
try:
    out = []
    for p in doc:
        ws = p.get_text("words")
        ws.sort(key=lambda w: (round(w[1], 1), w[0]))
        out.append(" ".join(w[4] for w in ws))
    print(score("5 pymupdf words, position-sorted", "\n".join(out)))
except Exception as e:
    print(f"5 words failed: {type(e).__name__}: {e}")
doc.close()

# 6) poppler, if installed
print()
try:
    import subprocess
    r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", PATH, "-"],
                       capture_output=True, timeout=180)
    if r.returncode == 0 and r.stdout:
        print(score("6 pdftotext -layout", r.stdout.decode("utf-8", "replace")))
    else:
        print(f"6 pdftotext -layout            FAILED rc={r.returncode} "
              f"{r.stderr[:80].decode('utf-8','replace')}")
except FileNotFoundError:
    print("6 pdftotext                     NOT INSTALLED")
except Exception as e:
    print(f"6 pdftotext                     {type(e).__name__}: {e}")

# 7) pdfplumber, if installed
print()
try:
    import pdfplumber
    with pdfplumber.open(PATH) as pdf:
        txt = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
    print(score("7 pdfplumber extract_text()", txt))
except ImportError:
    print("7 pdfplumber                    NOT INSTALLED")
except Exception as e:
    print(f"7 pdfplumber                    {type(e).__name__}: {e}")

# control: the same methods must also work on a known-good file
print()
print("=" * 96)
print("CONTROL — the known-good penal code, same default method")
print("=" * 96)
d2 = fitz.open(CONTROL)
print(score("1 pymupdf get_text()  [current]", "\n".join(p.get_text() for p in d2)))
d2.close()
