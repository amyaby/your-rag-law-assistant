import fitz
"""
chunker.py — PDF Loading and Text Chunking
Reads PDF files using PyMuPDF, extracts text from each page,
then splits the text into 100-word chunks with 20-word overlap.
Word-based splitting ensures no words get cut in half.
"""

def load_pdf(path: str) -> list[str]:
    doc = fitz.open(path)
    pages = [page.get_text() for page in doc]
    doc.close()
    return pages


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


def chunk_pdf(path: str, chunk_size: int = 100, chunk_overlap: int = 20) -> list[str]:
    pages = load_pdf(path)
    all_chunks = []
    for page in pages:
        all_chunks.extend(chunk_text(page, chunk_size, chunk_overlap))
    return all_chunks