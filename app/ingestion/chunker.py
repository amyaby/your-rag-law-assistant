CHUNK_SIZE = 500
CHUNK_OVERLAP = 100


def chunk_text(text: str) -> list[str]:
    paragraphs = text.split("\n\n")
    chunks = []
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= CHUNK_SIZE:
            chunks.append(paragraph)
        else:
            for i in range(0, len(paragraph), CHUNK_SIZE - CHUNK_OVERLAP):
                chunk = paragraph[i:i + CHUNK_SIZE]
                if chunk.strip():
                    chunks.append(chunk)
    return chunks