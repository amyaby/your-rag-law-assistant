"""
check_corpus.py — Run the ingestion quality gate over every PDF in data/docs/.

Usage:
    ./venv/bin/python scripts/check_corpus.py

Prints one line per file:  OK / SKIP + the measured signals + the reason.
Exits 1 if any file is skipped, so it can be used as a pre-ingestion CI check.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ingestion.chunker import pdf_health_check  # noqa: E402


def main() -> int:
    files = sorted(glob.glob("data/docs/*.pdf"))
    if not files:
        print("no PDFs in data/docs/")
        return 1

    print(f"{'':4} {'file':46} {'pages':>5} {'chars':>8} {'chunks':>6} {'max':>6}  reason")
    print("-" * 110)

    skipped = 0
    for path in files:
        law = os.path.basename(path)
        ok, reason, st = pdf_health_check(path, law)
        mark = "OK" if ok else "SKIP"
        if not ok:
            skipped += 1
        print(f"{mark:4} {law[:46]:46} {st['pages']:>5} {st['chars']:>8} "
              f"{st['chunks']:>6} {st['max_chunk_chars']:>6}  {reason}")

    print("-" * 110)
    total = len(files)
    print(f"{total - skipped}/{total} files accepted, {skipped} skipped")
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
