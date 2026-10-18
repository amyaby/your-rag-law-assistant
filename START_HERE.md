# START_HERE.md — من الصفر حتى جواب، خطوة بخطوة

> **README of the runbook.** Deep reference lives in `TESTING.md` (277 lines, Darija).
> This file is the short path: **6 commands, one answer.** Follow it top to bottom.
>
> Last verified against the repo on **2026-09-27**. All expected numbers below were
> produced by running the real pipeline, not guessed.

---

## Before you start: open the right terminal

You need **two** terminals side by side.

| Terminal | What runs there | Where you are |
|---|---|---|
| **A** | PostgreSQL + uvicorn (the server) | inside WSL |
| **B** | the `curl` tests | anywhere — WSL or PowerShell |

If you're in **PowerShell**, prefix WSL commands with `wsl`. If you're already in the
WSL shell (prompt looks like `im_ane@...:~$`), drop the prefix.

---

## Step 1 — start PostgreSQL (no password needed)

This is the step that blocked you. **Do not use `sudo`.** From PowerShell, `wsl -u root`
becomes root with no password prompt:

```powershell
wsl -u root bash -c "service postgresql start; sleep 2; pg_isready"
```

**Expected:**
```
/var/run/postgresql:5432 - accepting connections
```

**If it says `no response`:** run it again. Cluster start is sometimes slow the first time.

### ⚠️ The port-5432 hijack — read this once

There is a **Docker container called `evolution_postgres`** that grabs port 5432 and
breaks password auth. This is the single most common failure in this project. If you get
`password authentication failed for user postgres`, that is the cause:

```powershell
wsl -u root bash -c "docker stop evolution_postgres; service postgresql start; sleep 2; pg_isready"
```

Run that combined line any time auth misbehaves.

---

## Step 2 — confirm the database and the extension exist

```bash
PGPASSWORD=alx psql -h 127.0.0.1 -U postgres -d assistant -c "\dx vector"
```

**Expected:** a row for `vector`. If instead you get *"database assistant does not exist"*
or *"extension vector is not available"*, create them:

```bash
# as root:
wsl -u root bash -c "su - postgres -c \"createdb assistant\""
wsl -u root bash -c "su - postgres -c \"psql -d assistant -c 'CREATE EXTENSION IF NOT EXISTS vector;'\""
```

**Checkpoint 🧠 — predict before you continue.**
You now have Postgres running with pgvector enabled. In one sentence, why do we need
`CREATE EXTENSION` when the package is already installed? (Hint: apt puts *files* on
disk; the extension has to be *registered* per database.) See `PGVECTOR_GUIDE.md` §4.

---

## Step 3 — start the API server

In **terminal A**:

```bash
cd ~/ai-uni-assistant
pkill -f uvicorn                       # kill any stale process, ignore the error
./venv/bin/uvicorn app.main:app --port 8000
```

**Expected — and this is the important part:**
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

`Application startup complete` means the DB connected **and** the schema was created.

> If startup hangs on `Application startup complete`, the DB is the problem — go back to
> step 1. If it crashes instead, scroll up in the terminal; the real traceback is above.

**Your venv is already complete** — FastAPI 0.141.1, uvicorn 0.52.4, psycopg 3.3.4,
sentence-transformers 6.0.0, python 3.10.12. No `pip install` needed.

---

## Step 4 — health checks

In **terminal B**:

```bash
for p in / /ui /docs; do
  printf "%-8s %s\n" "$p" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000$p)"
done
```

**Expected: `200` for all three.**

---

## Step 5 — load the laws into the database

```bash
curl -s -X POST http://127.0.0.1:8000/reset
curl -s -X POST http://127.0.0.1:8000/ingest-all
```

Takes **2-4 minutes** (it runs the embedding model locally on every chunk). Watch
terminal A — one line per file.

**This is the exact expected response** (measured by running the real pipeline):

```json
{
  "status": "ok",
  "total_files": 9,
  "ingested_files": 9,
  "skipped_files": 0,
  "total_chunks": 5864
}
```

And the per-law breakdown you should see in the database:

| chunks | law |
|---|---|
| 1581 | كتاب مجموعة القانون الاداري… (admin code collection) |
| 1303 | obligations-contracts.pdf |
| 852 | code-procedure-penale-22-01.pdf |
| 758 | code-penal-2024.pdf |
| 590 | **قانون 65.99 مدونة الشغل.txt** ← the new one |
| 399 | code-famille-70-03.pdf |
| 205 | loi-31-08-consommation.pdf |
| 121 | قانون الصحافة والنشر 88.13.pdf |
| 55 | قانون 09.08 مرسوم تطبيقي.pdf |

Verify:

```bash
PGPASSWORD=alx psql -h 127.0.0.1 -U postgres -d assistant \
  -c "select law, count(*) from documents group by law order by 2 desc"
```

**Checkpoint 🧠.** `مدونة الشغل` now shows **590**, not the 1 it used to show. Explain in
one sentence why the old PDF gave 1 chunk and the new text file gives 590. (Hint: the
official PDF's glyph map is corrupted, so PyMuPDF extracts garbage and the article regex
finds nothing. See `PGVECTOR_GUIDE.md` §5 and `TESTING.md` §9.)

---

## Step 6 — ask a question

```bash
curl -s -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"ما هي عقوبة السرقة في المادة 505؟"}' | head -c 1200
```

**Expected:** an `answer` in Arabic, plus `sources` containing
`"article": "505"`.

Try a labour question too — this is the whole point of step 5:

```bash
curl -s -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"ما هي المدة السنوية للعطلة حسب مدونة الشغل؟"}' | head -c 1200
```

**Checkpoint 🧠 — the most important one.** Look at the `sources` array. Where did the
labour answer come from: `documents` (local index) or `scraped`? How would you tell the
difference from the JSON alone? (`scraped: true` means Corrective RAG went out to the
internet. See `ARCHITECTURE.md`.)

---

## Step 7 — open the chat UI

<http://127.0.0.1:8000/> → click **ابدأ المحادثة** → lands on `/ui`.

Chat there instead of `curl` — same backend, nicer. If styling looks stale, hard-refresh
with `Ctrl+Shift+R`.

---

## Step 8 — prove it works (optional, but do it once)

```bash
cd ~/ai-uni-assistant && ./venv/bin/python -m app.evaluation.smoke_test
```

Expected: `[PASS]` per section, ending `SMOKE TEST: ALL PASS`. Exit code 0.

The full evaluation (`app.evaluation.evaluate`, 15 questions) takes 2-4 min and makes
~30 Gemini calls — **it burns quota.** Save it for when you actually need the number.

---

## Troubleshooting — only the things that actually happen

| Symptom | Cause | Fix |
|---|---|---|
| `no response` from `pg_isready` | cluster down | redo step 1 |
| `password authentication failed for user postgres` | Docker `evolution_postgres` owns 5432 | `wsl -u root bash -c "docker stop evolution_postgres; service postgresql start"` |
| `Address already in use` | old uvicorn | `pkill -f uvicorn` |
| `ModuleNotFoundError: app` | you're inside `app/` | `cd ~/ai-uni-assistant` |
| startup never reaches "complete" | DB unreachable | step 1 |
| `503 UNAVAILABLE ... high demand` | Gemini overloaded | retry later, or it falls back |
| `429 RESOURCE_EXHAUSTED` | Gemini quota | wait, or switch model |
| `fitz API is deprecated` | PyMuPDF warning | harmless, ignore |
| `HF Hub unauthenticated` | no HF token | harmless, ignore |

---

## You're done when

- [ ] `pg_isready` says `accepting connections`
- [ ] uvicorn logged `Application startup complete`
- [ ] `/ingest-all` returned `total_chunks: 5864`
- [ ] `SELECT count(*)` on `documents` is close to 5864
- [ ] `/ask` returned an answer citing **article 505**
- [ ] you can say, out loud, *why* pgvector and not a dedicated vector DB
      (`PGVECTOR_GUIDE.md` §2)

That last box is the one that matters for your defense.

---

## Where to go next

| Goal | Read / run |
|---|---|
| Understand every concept | `ARCHITECTURE.md` |
| Understand the database layer | `PGVECTOR_GUIDE.md` |
| Full Darija test reference | `TESTING.md` |
| Measure quality | `./venv/bin/python -m app.evaluation.evaluate` |
| Own a subsystem | `app/retrieval/tokenize.py` → `relevance.py` → `app/ingestion/chunker.py` |

Two known issues are **not** in the way of anything above: `robots.py` doesn't enforce
path-level `Disallow`, and local hybrid hits don't get the relevance gate. Fix them after
you have a working server.
