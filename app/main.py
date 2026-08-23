"""
main.py — FastAPI Web Server
Exposes two HTTP endpoints:
- POST /ingest: takes a PDF path, chunks it, embeds it, stores it
- POST /ask: takes a question, searches for chunks, generates answer
This is the entry point that connects all other modules together.
"""

from fastapi import FastAPI
from pydantic import BaseModel
from app.ingestion.chunker import chunk_pdf
from app.core.embed import embed_texts
from app.retrieval.vector_store import create_table, insert_chunks
from app.retrieval.search import search
from app.core.llm import generate_answer

app = FastAPI()

class AskRequest(BaseModel):
    question: str


class IngestRequest(BaseModel):
    pdf_path: str


@app.on_event("startup")
def startup():
    create_table()


@app.post("/ingest")
def ingest(req: IngestRequest):
    """how we trait documents"""
    chunks = chunk_pdf(req.pdf_path)
    embeddings = embed_texts(chunks)
    insert_chunks(chunks, embeddings, source=req.pdf_path)
    return {"status": "ok", "chunks": len(chunks)}


@app.post("/ask")
def ask(req: AskRequest):
    """when the user ask"""
    results = search(req.question)
    context = "\n\n".join([r["content"] for r in results])
    answer = generate_answer(req.question, context)
    return {"answer": answer, "sources": results}