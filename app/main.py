"""
main.py — FastAPI Web Server
Exposes HTTP endpoints for ingestion, vector search with fallback, and LLM query answering.
"""

import os
import glob
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.ingestion.chunker import chunk_document, pdf_health_check
from app.core.embed import embed_texts
from app.retrieval.vector_store import (
    add_message,
    conversation_exists,
    create_conversation,
    create_table,
    delete_conversation,
    get_messages,
    insert_chunks,
    list_conversations,
    get_conn,
)
from app.core.llm import generate_answer, generate_suggestions, rephrase_query
from app.retrieval.search import search
from app.retrieval.hybrid import hybrid_search, invalidate_cache
from app.retrieval.retriever import crag_needed, retrieve
from app.retrieval.corrective import corrective_search

app = FastAPI(title="Moroccan Law Assistant", version="2.0")

# Serve static files for the frontend chat interface
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


def log(event: str, **fields):
    """One-line structured log. Replaces silent prints (README issue F5)."""
    payload = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {event} {payload}",
          flush=True)


class AskRequest(BaseModel):
    # NEW: conversation_id turns /ask from a stateless function into a chat.
    # It is optional, so every old client keeps working unchanged.
    question: str
    conversation_id: str | None = None


class IngestRequest(BaseModel):
    pdf_path: str


@app.on_event("startup")
def startup():
    """
    Boot even if the schema is broken.

    CHANGE: previously an exception here killed the process, so a database in
    the exact state that /reset is designed to repair was unrecoverable — you
    could not call the endpoint that fixes it. Now we log loudly and keep
    serving, so /reset, /docs and /ui stay reachable.
    """
    try:
        create_table()
        log("startup", ok=True, top_k=settings.top_k,
            threshold=settings.similarity_threshold,
            hybrid=settings.use_hybrid, chain=str(settings.fallback_models))
    except Exception as e:
        log("startup.FAILED", error=str(e),
            hint="POST /reset then POST /ingest-all")


@app.post("/reset")
def reset():
    """
    Drop and recreate every table (clear all data).

    WHY strict=False HERE
    ---------------------
    `create_table()` normally refuses to boot when `documents` still holds
    duplicates from a pre-idempotency run. That guard is useless here: /reset
    has just DROPPED the table, so it is provably empty and the unique index
    cannot fail. Passing strict=False skips the duplicate probe and lets the
    operator recover from the exact state the guard complains about.
    """
    with get_conn() as conn:
        conn.execute("DROP TABLE IF EXISTS messages;")
        conn.execute("DROP TABLE IF EXISTS conversations;")
        conn.execute("DROP TABLE IF EXISTS documents;")
        conn.commit()
    create_table(strict=False)
    invalidate_cache()          # the BM25 index described the deleted rows
    log("reset", ok=True)
    return {"status": "ok", "message": "Table reset. Ready for fresh ingestion."}


@app.post("/ingest")
def ingest(req: IngestRequest):
    """
    Ingest a single PDF after it passes the quality gate.

    CHANGE: the gate used to be `if not chunks`, which passes any file that
    returns *something* — a scanned PDF or a 49 000-char blob both sailed into
    the index. Now a file must clear four measurable thresholds or it is
    refused with the reason.
    """
    if not os.path.exists(req.pdf_path):
        raise HTTPException(status_code=404, detail=f"not found: {req.pdf_path}")

    law_name = os.path.basename(req.pdf_path)
    ok, reason, stats = pdf_health_check(req.pdf_path, law_name)
    if not ok:
        return {"status": "skipped", "file": law_name, "reason": reason, "stats": stats}

    chunks = chunk_document(req.pdf_path, law=law_name)
    embeddings = embed_texts([c["content"] for c in chunks])
    written = insert_chunks(chunks, embeddings)
    invalidate_cache()
    return {"status": "ok", "chunks": written, "stats": stats}


@app.post("/ingest-all")
def ingest_all():
    """Batch ingest every law document in data/docs/, with the quality gate.

    Glob is not PDF-only. The labour code could only be obtained as clean text
    (the official PDF's glyph table is corrupted and ISM republishes the same
    unusable file), so a text-only glob would have kept the single most
    commonly asked-about law out of the index forever.
    """
    doc_files = (glob.glob("data/docs/*.pdf")
                 + glob.glob("data/docs/*.txt")
                 + glob.glob("data/docs/*.html"))
    if not doc_files:
        return {"status": "error", "message": "No law documents found in data/docs/"}

    results = []
    for pdf_path in doc_files:
        law_name = os.path.basename(pdf_path)
        try:
            ok, reason, stats = pdf_health_check(pdf_path, law_name)
            if not ok:
                results.append({"file": pdf_path, "status": "skipped",
                                "reason": reason, "stats": stats})
                print(f"⏭  Skipped {law_name}: {reason}")
                continue

            chunks = chunk_document(pdf_path, law=law_name)
            embeddings = embed_texts([c["content"] for c in chunks])
            written = insert_chunks(chunks, embeddings)
            results.append({"file": pdf_path, "chunks": written, "status": "ok",
                            "stats": stats})
            print(f"✓ Ingested: {pdf_path} ({written} chunks)")
        except Exception as e:
            results.append({"file": pdf_path, "status": "error", "message": str(e)})
            print(f"✗ Failed: {pdf_path}: {e}")

    invalidate_cache()
    ok_files = [r for r in results if r["status"] == "ok"]
    skipped = [r for r in results if r["status"] == "skipped"]
    total_chunks = sum(r.get("chunks", 0) for r in ok_files)
    log("ingest-all", files=len(results), ingested=len(ok_files),
        skipped=len(skipped), chunks=total_chunks)
    return {
        "status": "ok",
        "total_files": len(results),
        "ingested_files": len(ok_files),
        "skipped_files": len(skipped),
        "total_chunks": total_chunks,
        "details": results,
    }



@app.post("/ask")
def ask(req: AskRequest):
    """
    Query pipeline: rephrase -> hybrid retrieval -> CRAG fallback -> memory-aware LLM.

    CHANGES HERE
    ------------
    * `search()` hard-coded `top_k=10` while a second `SIMILARITY_THRESHOLD =
      0.78` lived in the body. Two sources of truth for the same two numbers.
      Now: `settings.top_k` / `settings.similarity_threshold`.
    * Retrieval is now `hybrid_search()` (BM25 + RRF) instead of dense+boost.
    * `conversation_id` loads prior turns and appends this one, so "واش كاين
      شي استثناء؟" resolves instead of restarting the conversation.
    * The response carries `sources` and the retriever's own metrics so the
      evaluation harness and the UI can show WHY a chunk was chosen.
    """
    t0 = time.perf_counter()

    # 1. Rewrite Darija/Arabizi into formal legal Arabic search terms
    search_query = rephrase_query(req.question)

    # 2. Load conversation memory (optional feature, backwards compatible)
    history: list[dict] = []
    conversation_id = req.conversation_id
    if conversation_id and conversation_exists(conversation_id):
        history = get_messages(conversation_id, limit=settings.memory_turns * 2)

    # 3. Retrieval: one shared entry point (hybrid BM25+RRF or dense, per config)
    results, retriever = retrieve(search_query)
    top_score = max((r.get("similarity", 0.0) for r in results), default=0.0)
    needs_scrape = crag_needed(results)

    scraped = []
    if needs_scrape:
        try:
            # Corrective RAG: adala -> ism -> .ma web search
            scraped = corrective_search(search_query, max_chunks=settings.crag_max_chunks)
            if scraped:
                results = scraped + results
            log("crag", triggered=True, top_similarity=round(top_score, 3),
                chunks=len(scraped), q=search_query[:60])
        except Exception as e:
            log("crag.error", error=type(e).__name__)

    # Cap merged context so a CRAG hit cannot blow up the token budget
    results = results[:settings.context_max_chunks]

    context = "\n\n".join([
        f"[{r.get('law', 'N/A')} — المادة {r.get('article', 'N/A')}]\n{r.get('content', '')}"
        for r in results
    ])

    if not context.strip():
        answer = ("هاد الموضوع خارج تخصصي حاليا (القانون الجنائي، مدونة الأسرة، "
                  "مدونة الشغل، القانون الرقمي 09.08). جرب تصيغ سؤالك بطريقة أخرى، "
                  "مثلا: \"ما هي عقوبة السرقة الفصل 505؟\"")
        return {"answer": answer, "sources": [], "scraped": False,
                "suggestions": ["ما هي عقوبة السرقة؟", "ما هي شروط الحضانة؟",
                                "شنو عقوبة التشهير 447-1؟"],
                "conversation_id": conversation_id, "retriever": retriever}

    # 4. Answer with history for pronoun/reference resolution
    t_gen = time.perf_counter()
    answer = generate_answer(req.question, context, history=history)
    suggestions = generate_suggestions(req.question, context)

    # 5. Persist the turn so the next question in this conversation has context
    if conversation_id:
        if not conversation_exists(conversation_id):
            create_conversation(title=req.question[:120], conv_id=conversation_id)
        add_message(conversation_id, "user", req.question)
        add_message(conversation_id, "assistant", answer)

    log("ask", q=req.question[:60], retriever=retriever, hits=len(results),
        top_similarity=round(top_score, 3), scraped=len(scraped) > 0,
        history_turns=len(history),
        retrieve_ms=int((t_gen - t0) * 1000),
        total_ms=int((time.perf_counter() - t0) * 1000))

    return {
        "answer": answer,
        "sources": results,
        "scraped": len(scraped) > 0,
        "suggestions": suggestions,
        "conversation_id": conversation_id,
        "retriever": retriever,
    }


# ============================================================ conversation ====
@app.post("/conversations")
def start_conversation(title: str = "محادثة جديدة"):
    cid = os.urandom(8).hex()
    create_conversation(title=title, conv_id=cid)
    log("conversation.new", id=cid)
    return {"conversation_id": cid, "title": title}



@app.get("/conversations")
def conversations():
    return {"conversations": list_conversations()}


@app.get("/conversations/{cid}")
def conversation(cid: str):
    if not conversation_exists(cid):
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"conversation_id": cid, "messages": get_messages(cid, limit=200)}


@app.delete("/conversations/{cid}")
def drop_conversation(cid: str):
    if not conversation_exists(cid):
        raise HTTPException(status_code=404, detail="conversation not found")
    delete_conversation(cid)
    return {"status": "deleted", "conversation_id": cid}



@app.get("/ui")
def ui():
    """Serves the frontend chat page"""
    # new split UI (html+css+js separated)
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return FileResponse("static/chat.html")


@app.get("/")
def root():
    """Landing page: explains the solution and links to the chat."""
    if os.path.exists("static/landing.html"):
        return FileResponse("static/landing.html")
    return {"message": "Visit /ui for chat or /docs for API"}