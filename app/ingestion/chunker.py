import pymupdf as fitz
#re module is built into the standard library for Regular Expressions.
import re 
import unicodedata
from app.config import settings
"""
chunker.py — PDF Loading and Legal-Aware Chunking
Extracts text from PDF pages using PyMuPDF, then splits into chunks.
For legal documents, it detects article boundaries (المادة / مادة / Article)
so that EACH ARTICLE = ONE CHUNK (never split mid-article).
Returns a list of dicts with metadata: {law, article, content}.
If no article markers are found, falls back to word-based chunks.
"""

# Handles: المادة 508, مادة508, مادة 508, الفصل 508, فصل508
#AR_ARTICLE = re.compile(r'(?:المادة|مادة|الفصل|فصل)\s*([\d\-\.]+)', re.MULTILINE)
FR_ARTICLE = re.compile(r'(?:Article|Art\.?)\s*([\d\-\.]+)', re.MULTILINE)
# Expanded pattern supporting digits and written ordinal numbers
AR_ARTICLE = re.compile(
    r'^\s*(?:المادة|مادة|الفصل|فصل)\s*([\d\-\.]+|الأولى|الثانية|الثالثة|الرابعة|الخامسة)',
    re.MULTILINE,
)

def normalize_arabic(text: str) -> str:
    """Fix garbled Arabic ligatures/presentation forms from PDF extraction."""
    text = unicodedata.normalize("NFKC", text)
    # Rejoin article numbers that PyMuPDF split across lines in RTL PDFs:
    # reality in the PDF text flow is  "الفصل 1\n-\n447"  but the REAL number is
    # 447-1 (the base number 447 comes AFTER the dash in the extraction order).
    #
    # IMPORTANT why this pattern is safe: the grep-style fix I gave before
    # ("(الفصل)\s*\n?(\d+)\s*-\s*\n?\s*(\d+)") also matched an ALREADY-CORRECT
    # "الفصل 447-1" line and rewrote it backwards to "الفصل 1-447" — corrupting
    # good labels. This version demands a NEWLINE between the two number halves
    # (the PDF line break), which only happens in the broken case, so a normal
    # "الفصل 447-1" line is left untouched.
    #   broken: "الفصل 1\n-\n447" and "الفصل 1-\n447"
    #   good:   "الفصل 447-1"  (no newline between halves -> no match)
    text = re.sub(
        r"(الفصل|المادة)\s*(\d+)\s*\n+\s*-\s*\n+\s*(\d+)",
        lambda m: f"{m.group(1)} {m.group(3)}-{m.group(2)}",
        text,
    )
    text = re.sub(
        r"(الفصل|المادة)\s*(\d+)-+\s*\n\s*(\d+)",
        lambda m: f"{m.group(1)} {m.group(3)}-{m.group(2)}",
        text,
    )
    return text


def load_pdf(path: str) -> list[str]:
    doc = fitz.open(path)
    pages = [page.get_text() for page in doc]
    doc.close()
    return pages


# Text documents we can also index. A PDF is not the only container for a law,
# and insisting on one cost us the labour code — see chunk_document().
TEXT_SUFFIXES = (".txt", ".md", ".text")


def load_text_document(path: str) -> list[str]:
    """
    Read a plain-text / markdown / HTML law file as a list of "pages".

    HTML is stripped here rather than at download time so that a saved page and
    a live scrape go through exactly the same chunking path.
    """
    raw = open(path, encoding="utf-8", errors="replace").read()
    if path.lower().endswith((".html", ".htm")):
        raw = _html_to_text(raw)
    # One element: article_chunks() slices on article markers, not on pages, so
    # page boundaries are irrelevant here and inventing them would only risk
    # splitting an article in half.
    return [raw]


def _html_to_text(raw: str) -> str:
    """Visible text of an HTML page, with the chrome removed."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "header",
                         "footer", "form", "aside"]):
            tag.decompose()
        return soup.get_text("\n", strip=True)
    except ImportError:
        # bs4 is a hard dependency of the scrapers, so this should not happen;
        # degrade to a regex strip rather than failing ingestion outright.
        import re as _re
        return _re.sub(r"<[^>]+>", " ", raw)


def load_document(path: str) -> list[str]:
    """Dispatch on file type. PDFs go through PyMuPDF; text through the reader."""
    if path.lower().endswith(".pdf"):
        return load_pdf(path)
    if path.lower().endswith((".html", ".htm") + TEXT_SUFFIXES):
        return load_text_document(path)
    raise ValueError(
        f"unsupported document type: {path} (expected .pdf or one of {TEXT_SUFFIXES})"
    )


def chunk_text(text: str, chunk_size: int = 100, chunk_overlap: int = 20) -> list[str]:
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += chunk_size - chunk_overlap
        if chunk_size <= chunk_overlap:
            raise ValueError("chunk_size must be strictly greater than chunk_overlap")
    return chunks


def _window(text: str, max_chars: int, overlap: int) -> list[str]:
    """
    Split one long text into overlapping character windows.

    WHY THIS EXISTS
    ---------------
    `article_chunks()` slices the document between two article markers. If the
    markers are sparse, ONE slice can swallow tens of thousands of characters
    (measured: a 384-page administrative-law book produced a single 47 437-char
    chunk, and a 171-page labour code produced a single 48 932-char chunk).

    A 49k-char "chunk" is poison for a RAG system:
      * it carries one article number, so every citation derived from it is wrong
      * it burns a whole top-k slot
      * its embedding is a mean-pooled vector over 49k characters => semantically blurry
      * it eats the prompt token budget

    Splitting on CHARACTERS (not words) is deliberate: the broken PDFs in this
    corpus have almost no reliable whitespace, so `text.split()` cannot be trusted.
    """
    if len(text) <= max_chars:
        return [text]
    out, start = [], 0
    while start < len(text):
        out.append(text[start:start + max_chars])
        if start + max_chars >= len(text):
            break
        start += max_chars - overlap
    return out


def article_chunks(text: str, law: str, source: str = "") -> list[dict]:
    """
    Split text into one-chunk-per-article with metadata.
    Returns list of {law, article, source, content}.
    """
    text = normalize_arabic(text)
    matches = list(AR_ARTICLE.finditer(text)) or list(FR_ARTICLE.finditer(text))

    if not matches:
        # No article markers → fall back to word chunks
        """{
    "law": "Example Labour Code",
    "article": "Example article number",
    "content": "The actual text extracted from the legal article...",
    "source": "original PDF source",
    "embedding": [0.012, -0.084, 0.031, ...]
}"""
        return [
            {"law": law, "article": "", "source": source, "content": normalize_arabic(t)}
            for t in chunk_text(text)
        ]

    chunks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        article_num = m.group(1)
        content = text[start:end].strip()
        if len(content) <= 10:
            continue
        # NEW: never let a single slice become a giant blob
        for piece in _window(content, settings.max_article_chars, 200):
            piece = piece.strip()
            if len(piece) > 10:
                chunks.append({
                    "law": law,
                    "article": article_num,
                    "source": source,
                    "content": piece,
                })
    return chunks


def chunk_document(path: str, law: str = "", chunk_size: int = 100,
                   chunk_overlap: int = 20) -> list[dict]:
    """
    Load a law document of ANY supported type and return legal-aware chunks.

    WHY THIS EXISTS
    ---------------
    Ingestion was PDF-only, so a law only entered the index if some publisher
    happened to offer a PDF of it. The labour code is the concrete cost: the
    only PDF we could find (`مدونة الشغل.pdf`, 171 pages) has a corrupted glyph
    table, and the identical file is what ISM publishes too, so there was no
    second copy to fetch. Its text is 61% Arabic characters and completely
    unreadable:

        '22\\n ٔ\\n٣٘غ طٔو٤َ\\n ٧ح.َٜح أ ٝ ؿز َح'

    `الفصل`, `مادة`, `باب` and `مقال` occur ZERO times in 316,280 characters,
    while the same regex finds 659 articles in the penal code. Five PyMuPDF
    extraction modes and a second engine all fail identically, so the glyphs
    are not recoverable from that file by any means.

    The same law published as clean text is perfectly readable - 589 articles,
    dense numbering, 78% Arabic. So the container was the problem, not the
    law. Ingesting text costs ~40 lines and makes the corpus depend on
    publishers rather than on file formats.
    """
    if not law:
        law = path.split("/")[-1]
    pages = load_document(path)
    full_text = "\n".join(pages)
    return article_chunks(full_text, law, source=path)


def chunk_pdf(path: str, law: str = "", chunk_size: int = 100, chunk_overlap: int = 20) -> list[dict]:
    """
    Load a PDF and return legal-aware chunks as dicts.
    If `law` not given, uses the filename.
    """
    if not law:
        law = path.split("/")[-1]
    pages = load_pdf(path)
    full_text = "\n".join(pages)
    return article_chunks(full_text, law, source=path)


# ==============================================================================
# PDF QUALITY GATE  (added after the "مدونة الشغل.pdf = 1 chunk" incident)
# ==============================================================================
# The old gate in app/main.py was only `if not chunks`, which passes ANY file
# that returns *something*. Two broken PDFs sailed straight into the index:
#
#   مدونة الشغل.pdf                 171 pages, 316 280 chars, 1 chunk of 48 932 chars
#   constitution_marocaine_2011-ar   82 pages,                          31 chunks
#
# Root cause of the labour code: its RTL glyphs are stored in VISUAL order, so
# PyMuPDF returns fragments ("ظل ٌ٤ \n انفزع وألا") and the article regex
# `^\s*(?:المادة|مادة|الفصل|فصل)\s*\d` matches only ONCE in 316 280 chars.
# One match => one slice from that point to EOF => a 49k-char blob.
#
# So a filename allow/deny list is the wrong tool: it can only exclude files we
# already know about. These four measurable signals generalise to every future
# PDF, and they tell you *why* a file was rejected.
# ------------------------------------------------------------------------------
def pdf_health_check(path: str, law: str = "") -> tuple[bool, str, dict]:
    """
    Measure a local corpus document and decide whether it may enter the index.

    Returns (ok, reason, stats). `ok=False` means SKIP the file.
    `reason` is a human-readable explanation (goes straight into the API report).

    Despite the name this now measures any supported type (see
    `chunk_document`); it is kept under its original name because the API
    response field and the README both refer to it.
    """
    law = law or path.split("/")[-1]
    pages = load_document(path)
    text = "\n".join(pages)              # load_document() returns a LIST of strings
    chars = len(text)
    chunks = chunk_document(path, law=law)

    stats = {
        "pages": len(pages),
        "chars": chars,
        "chunks": len(chunks),
        "avg_chunk_chars": (chars // len(chunks)) if chunks else 0,
        "max_chunk_chars": max((len(c["content"]) for c in chunks), default=0),
        "articles": sum(1 for c in chunks if c.get("article")),
    }

    if not chunks or chars < settings.min_pdf_chars:
        return False, f"scanned/no text layer ({chars} chars, {stats['pages']} pages)", stats

    if len(chunks) < settings.min_pdf_chunks:
        return (False,
                f"article split failed: {len(chunks)} chunks from {chars} chars "
                f"(broken RTL text layer?)",
                stats)

    if stats["avg_chunk_chars"] > settings.max_avg_chunk_chars:
        return (False,
                f"chunks too big: avg {stats['avg_chunk_chars']} chars "
                f"(max {stats['max_chunk_chars']})",
                stats)

    if stats["articles"] / len(chunks) < 0.5:
        return (False, f"only {stats['articles']}/{len(chunks)} chunks carry an article", stats)

    return True, "ok", stats
