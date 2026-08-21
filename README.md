# Uni Assistant

A RAG (Retrieval-Augmented Generation) chatbot that answers questions about your university using official school documents.

## What it does

1. You upload university PDFs (regulations, course catalogs, schedules)
2. The system chunks them into pieces and stores them as vectors
3. When you ask a question, it finds the most relevant chunks
4. It sends those chunks + your question to Gemini and returns an answer with citations

## Architecture

```
User asks: "What are the exam rules?"
        │
        ▼
┌─────────────────────────────────────────────┐
│  1. EMBED (app/core/embed.py)              │
│     Convert question → vector [0.1, -0.3...]│
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  2. SEARCH (app/retrieval/search.py)       │
│     Find top 5 similar chunks from pgvector│
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  3. GENERATE (app/core/llm.py)             │
│     Send chunks + question to Gemini       │
│     Return answer with sources             │
└─────────────────────────────────────────────┘
```

## How ingestion works

```
PDF file
    │
    ▼
┌─────────────────────────────────────────────┐
│  LOAD (app/ingestion/chunker.py)           │
│     Extract text from each page            │
│     Split into 500-char chunks             │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  EMBED (app/core/embed.py)                 │
│     Convert each chunk → vector            │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│  STORE (app/retrieval/vector_store.py)     │
│     Save chunks + vectors in PostgreSQL    │
└─────────────────────────────────────────────┘
```

## Project structure

```
ai-uni-assistant/
├── app/
│   ├── config.py              # Settings from .env
│   ├── main.py                # FastAPI endpoints
│   ├── core/
│   │   ├── embed.py           # Gemini embedding wrapper
│   │   └── llm.py             # Gemini chat wrapper
│   ├── ingestion/
│   │   ├── chunker.py         # PDF loader + text splitter
│   │   └── embed_test.py      # Test script (delete after testing)
│   ├── retrieval/
│   │   ├── vector_store.py    # PostgreSQL + pgvector setup
│   │   └── search.py          # Similarity search
│   └── evaluation/            # Accuracy tests
├── data/docs/                 # Drop your PDFs here
├── tests/                     # Unit tests
├── requirement.txt            # Python dependencies
└── .env                       # API keys (never commit)
```

## Tech stack

- **Gemini 2.0 Flash** — LLM for generating answers
- **Gemini Embedding 001** — converts text to vectors
- **PostgreSQL + pgvector** — stores and searches vectors
- **FastAPI** — web API
- **PyMuPDF** — reads PDF files
- **Pydantic** — data validation

## Run it

```bash
# 1. Install dependencies
pip install -r requirement.txt

# 2. Start PostgreSQL
sudo service postgresql start

# 3. Ingest a PDF
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"pdf_path": "data/docs/regulations.pdf"}'

# 4. Ask a question
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the exam rules?"}'
```

## API endpoints

| Method | Path      | Description              |
|--------|-----------|--------------------------|
| POST   | `/ingest` | Upload and index a PDF   |
| POST   | `/ask`    | Ask a question           |

## Development plan (4 weeks)

### Week 1: Foundation — Understand RAG + Build core wrappers

**Project tasks:**
- [x] Project structure created
- [x] `.env` with API key configured
- [x] `config.py` with all settings
- [x] `embed_test.py` — verified Gemini embeddings work
- [x] `README.md` written
- [ ] Create `app/core/embed.py` — embedding wrapper function
- [ ] Create `app/core/llm.py` — LLM chat wrapper function
- [ ] Test both independently

**LLM Zoomcamp — Module 1: Agentic RAG (Part 1)**
Read these lessons to understand WHY we're building this:

| Lesson | Link | What you learn |
|--------|------|----------------|
| 01 - Introduction | [01-intro.md](https://github.com/DataTalksClub/llm-zoomcamp/blob/main/01-agentic-rag/lessons/01-intro.md) | What the course builds and why |
| 03 - What is RAG | [03-rag.md](https://github.com/DataTalksClub/llm-zoomcamp/blob/main/01-agentic-rag/lessons/03-rag.md) | Why LLMs need context, the RAG architecture |
| 05 - Search | [05-search.md](https://github.com/DataTalksClub/llm-zoomcamp/blob/main/01-agentic-rag/lessons/05-search.md) | Building a search engine (keyword search) |
| 06 - Building a Prompt | [06-building-prompt.md](https://github.com/DataTalksClub/llm-zoomcamp/blob/main/01-agentic-rag/lessons/06-building-prompt.md) | Combining search results into a prompt |
| 07 - RAG Pipeline | [07-llm.md](https://github.com/DataTalksClub/llm-zoomcamp/blob/main/01-agentic-rag/lessons/07-llm.md) | Wiring search + prompt + LLM together |

---

### Week 2: Ingestion + Storage — Load PDFs, chunk, embed, store

**Project tasks:**
- [ ] Create `app/ingestion/chunker.py` — PDF loader + text splitter
- [ ] Create `app/retrieval/vector_store.py` — PostgreSQL table + insert
- [ ] Test: real PDF → chunk → embed → store in database

**LLM Zoomcamp — Module 1 Part 2 + Module 2: Vector Search**
Read these lessons to understand embeddings and vector storage:

| Lesson | Link | What you learn |
|--------|------|----------------|
| 09 - Data Ingestion | [09-data-ingestion.md](https://github.com/DataTalksClub/llm-zoomcamp/blob/main/01-agentic-rag/lessons/09-data-ingestion.md) | Persistent search with SQLite |
| 02 - What is Vector Search | [01-intro.md](https://github.com/DataTalksClub/llm-zoomcamp/blob/main/02-vector-search/lessons/01-intro.md) | Keyword search vs vector search |
| 03 - Embeddings | [02-embeddings.md](https://github.com/DataTalksClub/llm-zoomcamp/blob/main/02-vector-search/lessons/02-embeddings.md) | Turning text into vectors |
| 04 - Embedding Our Dataset | [03-embeddings-dataset.md](https://github.com/DataTalksClub/llm-zoomcamp/blob/main/02-vector-search/lessons/03-embeddings-dataset.md) | Generating embeddings for dataset |
| 08 - Vector Search with PGVector | [08-pgvector.md](https://github.com/DataTalksClub/llm-zoomcamp/blob/main/02-vector-search/lessons/08-pgvector.md) | **DIRECTLY relevant** — pgvector setup |

**Other concepts to learn:**
- PyMuPDF: `fitz.open()` → `page.get_text()` extracts text from PDF pages
- String slicing: `text[i:i+chunk_size]` splits text into pieces
- psycopg: `conn.execute("SELECT ...")` runs SQL queries
- SQL: `CREATE TABLE`, `INSERT INTO`, `SELECT`

---

### Week 3: Search + Generation — Ask questions, get answers

**Project tasks:**
- [ ] Create `app/retrieval/search.py` — similarity search
- [ ] Create `app/main.py` — FastAPI endpoints (`/ingest`, `/ask`)
- [ ] Test: ask question → get chunks → get Gemini answer

**LLM Zoomcamp — Module 2 continued + Module 1 Part 2 (Agents)**
Read these to understand the search + generate flow:

| Lesson | Link | What you learn |
|--------|------|----------------|
| 05 - Vector Search with minsearch | [05-minsearch-vector.md](https://github.com/DataTalksClub/llm-zoomcamp/blob/main/02-vector-search/lessons/05-minsearch-vector.md) | In-memory vector search |
| 06 - RAG with Vector Search | [06-rag-vector.md](https://github.com/DataTalksClub/llm-zoomcamp/blob/main/02-vector-search/lessons/06-rag-vector.md) | Replacing keyword with vector search |
| 13 - Function Calling | [13-function-calling.md](https://github.com/DataTalksClub/llm-zoomcamp/blob/main/01-agentic-rag/lessons/13-function-calling.md) | Giving LLM tools to use |
| 14 - The Agentic Loop | [14-agentic-loop.md](https://github.com/DataTalksClub/llm-zoomcamp/blob/main/01-agentic-rag/lessons/14-agentic-loop.md) | Repeating until model stops calling tools |

**Other concepts to learn:**
- pgvector: `ORDER BY embedding <=> %s::float[]` finds most similar vectors
- FastAPI: `@app.post("/ask")` creates an API endpoint
- Pydantic: `BaseModel` defines input/output structure

---

### Week 4: Evaluation + Polish — Measure accuracy, fix issues

**Project tasks:**
- [ ] Create `app/evaluation/test_questions.py` — 10 questions with expected answers
- [ ] Create `app/evaluation/evaluate.py` — run questions, score accuracy
- [ ] Run full pipeline end-to-end with real university PDFs
- [ ] Fix issues found during evaluation

**LLM Zoomcamp — Module 4: Evaluation**
Read these to learn how to measure your RAG system:

| Lesson | Link | What you learn |
|--------|------|----------------|
| Module 4 | [04-evaluation](https://github.com/DataTalksClub/llm-zoomcamp/tree/main/04-evaluation) | Measure retrieval and answer quality |
| Homework | [homework.md](https://github.com/DataTalksClub/llm-zoomcamp/blob/main/cohorts/2026/04-evaluation/homework.md) | Practical evaluation exercises |

**Other concepts to learn:**
- LLM-as-Judge: ask Gemini to score your answers
- Retrieval metrics: did the right chunks get retrieved?
- Answer quality: is the answer grounded in the context?
