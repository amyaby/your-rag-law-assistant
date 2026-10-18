"""
inspect_pdf.py — Diagnose why a PDF produces too few chunks.

Usage:
    ./venv/bin/python scripts/inspect_pdf.py data/docs/code-penal-2024.pdf
    ./venv/bin/python scripts/inspect_pdf.py data/docs/            # inspect all

Prints, per file: pages, extracted characters, chunk count, chunk sizes,
and a preview of the first chunk (so you can see if the text is garbled,
empty, or the article regex failed).
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ingestion.chunker import chunk_pdf, load_pdf  # noqa: E402


def inspect(path: str) -> None:
    pages = load_pdf(path)          # load_pdf returns a LIST of page strings
    text = "\n".join(pages)         # so it must be joined before measuring
    chunks = chunk_pdf(path, law=os.path.basename(path))

    print("=" * 70)
    print(f"FILE      : {os.path.basename(path)}")
    print(f"size      : {os.path.getsize(path) / 1024:.0f} KB")
    print(f"pages     : {len(pages)}")
    print(f"chars     : {len(text)}")
    print(f"chunks    : {len(chunks)}")

    if not chunks:
        print("VERDICT   : FAIL - 0 chunks (no text extracted?)")
        return

    sizes = [len(c["content"]) for c in chunks]
    print(f"chunk size: min={min(sizes)} max={max(sizes)} avg={sum(sizes) // len(sizes)}")
    arts = [c.get("article") for c in chunks if c.get("article")]
    print(f"articles  : {len(arts)} chunks carry an article number")
    print(f"           first 8: {arts[:8]}")

    ratio = len(text) / max(len(chunks), 1)
    if len(text) < 20_000:
        verdict = f"FAIL - only {len(text)} chars: scanned/image PDF, needs OCR"
    elif len(chunks) == 1:
        verdict = "FAIL - single chunk: the article regex (المادة/الفصل) did not match"
    elif ratio > 4000:
        verdict = "FAIL - chunks are huge: chunker fell back to size-based splitting"
    elif len(arts) < len(chunks) * 0.5:
        verdict = "WARN - many chunks without an article number"
    else:
        verdict = "OK - one article per chunk"
    print(f"VERDICT   : {verdict}")

    print("--- raw text preview (first 200 chars) ---")
    print(repr(text[:200]))
    print("--- first chunk preview (first 300 chars) ---")
    print(chunks[0]["content"][:300])
    print()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "data/docs"
    files = sorted(glob.glob(os.path.join(target, "*.pdf"))) if os.path.isdir(target) else [target]
    if not files:
        print("no PDFs found")
    for f in files:
        try:
            inspect(f)
        except Exception as e:
            print("=" * 70)
            print(f"FILE      : {os.path.basename(f)}")
            print(f"ERROR     : {type(e).__name__}: {e}")
