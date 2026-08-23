import httpx  # Standard Python HTTP client library used to make API calls (similar to requests)

BASE = "http://localhost:8000"  # The local address where your Uvicorn/FastAPI server is running

# --- INGESTION STAGE ---
# You send a POST request to tell the backend to process a document.
r = httpx.post(#send a POST request
    f"{BASE}/ingest",#to http://localhost:8000/inges
    json={"pdf_path": "data/docs/TD_TF-IDF_Apriori.pdf"},  # Payload specifying which file to read & index
    timeout=60,  # Extends max waiting time to 60s because parsing, chunking, and embedding creation take time
)
print(r.json())  # Output: {'status': 'ok', 'chunks': 6} -> Server processed the PDF into 6 vector chunks.

# --- RETRIEVAL & GENERATION (ASK) STAGE ---
questions = [
    "What is TF-IDF?",
    "How to calculate IDF?",
    "What is cosine similarity?",
]
# through each question send question snd post request to ../ask sent the question waht 
for q in questions:
    r = httpx.post(
        f"{BASE}/ask", json={"question": q}, timeout=60  # Sends query to the /ask endpoint(parse JSON response)
    )
    data = r.json()  # Server returns JSON containing {'answer': '...', 'sources': [...]}

    print(f"\nQ: {q}")#print question
    print(
        f"A: {data['answer'][:200]}..."
    )  # Truncates the LLM response to display the first 200 characters
    print(
        f"Sources: {len(data['sources'])} chunks found"
    )  # Displays how many context chunks were retrieved from PostgreSQL