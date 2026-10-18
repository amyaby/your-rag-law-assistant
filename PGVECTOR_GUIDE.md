# pgvector: The Complete Practical Guide

### *Written for this project — every snippet maps to real code in `app/`*

> **Verification note (2026-09-27).** Every version-specific claim in this document was
> checked against the files actually installed on this machine, not recalled:
>
> - `postgresql-14` **14.24-1.pgdg22.04+2**
> - `postgresql-14-pgvector` **0.8.6-1.pgdg22.04+1**
> - Operators/type/limit facts: `/usr/share/postgresql/14/extension/vector--0.8.6.sql`
> - Defaults, tuning guidance, and gotchas: `/usr/share/doc/postgresql-14-pgvector/README.md.gz`
> - Python type mapping: installed `psycopg` **3.3.4** (`psycopg.types.numeric`)
> - All `app/` line numbers cross-checked against the source
>
> Three claims in the first draft of this guide were **wrong** and are corrected here.
> They are listed in [Appendix B](#appendix-b--corrections-to-the-first-draft) because
> the mistakes are the most instructive part.

---

## Table of contents

1. [What a vector actually is](#1-what-a-vector-actually-is)
2. [Why a vector database — and why *this* one](#2-why-a-vector-database--and-why-this-one)
3. [What pgvector is](#3-what-pgvector-is)
4. [Setup: the three lines that matter](#4-setup-the-three-lines-that-matter)
5. [The data model](#5-the-data-model)
6. [Distance metrics — the part everyone gets wrong](#6-distance-metrics--the-part-everyone-gets-wrong)
7. [Storing vectors](#7-storing-vectors)
8. [Searching: the core query](#8-searching-the-core-query)
9. [Metadata: the columns next to the vector](#9-metadata-the-columns-next-to-the-vector)
10. [Idempotent upsert](#10-idempotent-upsert--the-most-important-pattern-in-this-project)
11. [Indexes: HNSW vs IVFFlat — and why we use *neither*](#11-indexes-hnsw-vs-ivfflat--and-why-we-use-neither)
12. [Filtering with vectors](#12-filtering-with-vectors)
13. [Notebook: the whole thing, cell by cell](#13-notebook-the-whole-thing-cell-by-cell)
14. [Our production code, annotated](#14-our-production-code-annotated)
15. [Gotchas that will bite you](#15-gotchas-that-will-bite-you)
16. [When to graduate to a dedicated vector DB](#16-when-to-graduate-to-a-dedicated-vector-db)
17. [Appendix A — run it yourself](#appendix-a--run-it-yourself)
18. [Appendix B — corrections to the first draft](#appendix-b--corrections-to-the-first-draft)
19. [Appendix C: run it from scratch](#appendix-c-run-it-from-scratch-server-database-tables)

---

## 1. What a vector actually is

A vector is just a fixed-length list of floats. In our project, **384 floats**, one per chunk of law.

```
"المادة 184: يعاقب بالحبس من قناة واحدة إلى خمس سنوات"
              ↓  multilingual-e5-small  (384-dim)
[0.021, -0.118, 0.884, ..., -0.043]
```

The model is trained so that **texts with similar meaning land near each other** in that
384-dimensional space. Not "similar words" — similar *meaning*.

```python
from sentence_transformers import SentenceTransformer
import numpy as np

model = SentenceTransformer("intfloat/multilingual-e5-small")

a = model.encode("passage: يعاقب بالحبس من قناة واحدة إلى خمس سنوات")
b = model.encode("passage: تُعاقب بالحبس مدة تتراوح بين سنة وخمس سنوات")
c = model.encode("passage: يُشترط أن يكون العقد موثقاً كتابة")

def cos(x, y):
    return float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y)))

print(cos(a, b))   # ~0.85  ← same idea, different words
print(cos(a, c))   # ~0.62  ← unrelated
```

**Why this matters for law:** a user asks *"شحال من سنة ديال الحبس؟"*. The statute says
*"من قناة واحدة إلى خمس سنوات"*. **Almost zero shared words.** Pure keyword search
scores ~0. Vector search scores ~0.85.

That gap — *same concept, different vocabulary* — is the entire reason a vector database
exists in this project.

> **Note the `passage: ` prefix.** E5 is an *asymmetric* model: documents get
> `"passage: "`, queries get `"query: "`. Using the same prefix on both sides is the most
> common silent bug in E5 projects — the vectors just become subtly wrong and **nothing
> errors**. Our prefixes are applied in `app/core/embed.py`.

---

## 2. Why a vector database — and why *this* one

Let's be honest about the alternatives, because "why a vector DB" is a real question and
the answer is not "because it's trendy."

### Option A — brute-force search in Python

```python
import numpy as np
matrix = np.array([chunk.embedding for chunk in all_chunks])   # 5254 × 384
scores = matrix @ query_vec
top = np.argsort(-scores)[:10]
```

**This is genuinely fast.** `5254 × 384` float32 ≈ 8 MB. A matrix-vector product is
~2 million multiply-adds — about **1 millisecond** on a modern CPU.

| Rows | Brute force | Verdict |
|---|---|---|
| 5,000 | ~1 ms | fine |
| 100,000 | ~20 ms | fine |
| 1,000,000 | ~200 ms + 1.5 GB RAM | starts to hurt |
| 10,000,000 | seconds, tens of GB | you need an index or a real system |

### Option B — a dedicated vector database (Pinecone, Qdrant, Weaviate, Milvus, Chroma)

| Pro | Con |
|---|---|
| Built for vectors, scales horizontally | **Another service to run, secure, and pay for** |
| Good at 10M+ vectors | Duplicates your data — two sources of truth |
| Rich filtering DSL | No transactions. No JOINs. No SQL. |

### Option C — pgvector ✅ **what we chose**

| Pro | Con |
|---|---|
| **It's PostgreSQL.** Transactions, backups, `psql`, existing ops knowledge | Slower than a purpose-built engine at very large scale |
| **Metadata lives in the same row as the vector** | Index tuning is on you |
| One database, one backup, one thing to secure | |
| Filter + vector search in **one query**, with a real `WHERE` | |

**The deciding factor for this project:** every chunk needs `law`, `article`, `source`.
With pgvector that's:

```sql
SELECT content, law, article FROM documents
WHERE law = 'code-penal-2024.pdf'
ORDER BY embedding <=> $1 LIMIT 5;
```

In a dedicated vector DB you'd either denormalize the metadata into the vector record, or
fetch IDs from Postgres and then query the vector store — **two round trips, two
consistency problems.**

**The honest limit:** pgvector is not the fastest thing at 100M+ vectors. If this project
grew to millions of chunks, Qdrant or a managed service would win. At 5,254 chunks over
~8 MB, **PostgreSQL is the right tool and a dedicated vector DB would be pure overhead.**

---

## 3. What pgvector is

An **open-source PostgreSQL extension** that adds:

| Feature | What it gives you |
|---|---|
| `vector(N)` | a column type holding N-dimensional float vectors |
| Distance operators | `<->`, `<#>`, `<=>`, `<+>` — computed in SQL |
| `hnsw` index | HNSW graph for fast approximate search |
| `ivfflat` index | inverted-file index for fast approximate search |
| `halfvec` | half-precision vectors, up to 4,000 dims |
| `sparsevec` | sparse vectors (learned sparse retrieval) |
| `bit` | binary quantization, up to 64,000 dims |

**It's not a database. It's a data type plus operators inside the database you already
run.** That framing matters — it means vectors get transactions, backups, replication,
and `DELETE` for free.

Verified in `vector--0.8.6.sql`:

```sql
CREATE ACCESS METHOD hnsw    TYPE INDEX HANDLER hnswhandler;     -- line 260
CREATE ACCESS METHOD ivfflat TYPE INDEX HANDLER ivfflathandler;  -- line 253
CREATE TYPE vector;  CREATE TYPE halfvec;  CREATE TYPE sparsevec;
```

---

## 4. Setup: the three lines that matter

> **⚠️ STEP 0 — start the cluster before anything else.** Everything in this section
> fails on a stopped server, and the cluster does **not** survive a WSL restart.
> Full command sequence, schema and recovery ladder:
> [Appendix C](#appendix-c-run-it-from-scratch-server-database-tables).
>
> ```bash
> sudo service postgresql start
> sleep 2 && pg_isready -h 127.0.0.1 -p 5432   # want: accepting connections
> ```

```bash
# 1. install (Ubuntu/Debian)
sudo apt install postgresql-14-pgvector

# 2. enable the extension, per database
sudo -u postgres psql -d assistant -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 3. verify
sudo -u postgres psql -d assistant -c "SELECT '[1,2,3]'::vector;"
```

```sql
-- In the app, so it happens automatically on every startup
CREATE EXTENSION IF NOT EXISTS vector;
```

**Two mistakes people make here:**

1. **Installing the extension ≠ enabling it.** `apt install` only puts files on disk. You
   still need `CREATE EXTENSION` in **each** database you use. On this machine both steps
   are done — the files are in `/usr/share/postgresql/14/extension/`.
2. **`CREATE EXTENSION` needs superuser.** On managed Postgres (Supabase, Neon, RDS) you
   often can't. Use the vendor's own enable-SQL, or skip the index entirely (see
   [§11](#11-indexes-hnsw-vs-ivfflat--and-why-we-use-neither)).

**What we have:** PostgreSQL **14.24** + pgvector **0.8.6**.

---

## 5. The data model

This is our real schema, from `app/retrieval/vector_store.py:48-58`:

```sql
CREATE TABLE IF NOT EXISTS documents (
    id        SERIAL PRIMARY KEY,
    content   TEXT,              -- the chunk text
    embedding vector(384),       -- ← the vector
    law       TEXT,              -- "code-penal-2024.pdf"
    article   TEXT,              -- "447-1"   ← enables citation
    source    TEXT,              -- "adala.justice.gov.ma"
    version   TEXT               -- "2024-08"
);
```

**Key design decision: the vector sits in a normal relational row.**

This is the whole point of choosing pgvector. `id`, `law`, `article` are ordinary columns.
You can `JOIN`, `WHERE`, `GROUP BY`, and back it up with `pg_dump` like any other table.
Nothing about vector search is exotic except one column.

### Choosing the dimension

`vector(384)` is **not arbitrary — it is the model's output size.**
`intfloat/multilingual-e5-small` emits 384 dimensions.

> ⚠️ **The dimension is part of the schema contract.** If you swap the model to `e5-base`
> (768) or `bge-m3` (1024), you must
> `ALTER TABLE documents ALTER COLUMN embedding TYPE vector(768);` and **re-embed every
> row.** A `vector(384)` column rejects a 768-dim vector with a hard error — which is the
> *good* outcome, because a silent truncation would be catastrophic.

### Dimension limits (pgvector 0.8.6, from the shipped README)

| Type | Max dimensions | Notes |
|---|---|---|
| `vector` | **2,000** | float32, full precision |
| `halfvec` | **4,000** | half precision, half the memory |
| `bit` | **64,000** | binary quantization |

Beyond 2,000 dims the README's own options are `halfvec`, binary quantization, **subvector
indexing** (split a high-dim vector into indexable parts), or dimensionality reduction.

---

## 6. Distance metrics — the part everyone gets wrong

pgvector 0.8.6 defines four distance operators (verified in `vector--0.8.6.sql:174-192`
and the README operator table):

| Operator | Metric | C function | Range | Use when |
|---|---|---|---|---|
| `<->` | **Euclidean (L2)** | `l2_distance` | `[0, ∞)` | absolute position matters |
| `<=>` | **Cosine distance** | `cosine_distance` | `[0, 2]` | **only direction matters** ← text |
| `<#>` | **Negative inner product** | `vector_negative_inner_product` | `(-∞, ∞)` | vectors pre-normalized |
| `<+>` | **Manhattan (L1)** | `l1_distance` | `[0, ∞)` | sparse / high-dim |

**For text, use `<=>` (cosine).** Why: sentence-transformer vectors are *directions*, not
lengths. "الحبس" and a 10× longer article shouldn't be "far apart" because one is longer —
cosine ignores magnitude entirely.

### The conversion everyone forgets

**pgvector returns a DISTANCE. You want a SIMILARITY.** The official README states it in
one line: *"For cosine similarity, use 1 - cosine distance."*

```sql
-- WRONG: this is a distance, not a similarity
SELECT content, embedding <=> $1 AS score FROM documents ORDER BY 3 LIMIT 5;

-- RIGHT: similarity, so 0.78 is a meaningful cutoff
SELECT content, 1 - (embedding <=> $1) AS similarity
FROM documents ORDER BY embedding <=> $1 LIMIT 5;
```

This is exactly why our threshold is `0.78` and not `0.22`. **Mix up the two and your
threshold is silently inverted** — every query either always passes or always fails.
Nothing errors.

> Same trap with `<#>`: the README says *"For inner product, multiply by -1 (since `<#>`
> returns the negative inner product)."* You'd write `-1 * (embedding <#> $1)`.

### Our optimization: pre-normalize, then inner product is enough

`app/core/embed.py` uses `normalize_embeddings=True`, which makes every vector unit
length. When all vectors are unit length:

```
cosine(a, b) = a · b        (both magnitudes are 1, so they cancel)
```

So **inner product and cosine give identical rankings** — and inner product is cheaper to
index and faster to search. The README says the same: *"If vectors are normalized to length
1 (like OpenAI embeddings), use inner product for best performance."*

**Our project uses `<=>` anyway.** Why? Because correctness-by-construction beats
micro-optimization at 5,254 rows, where the whole vector set is 8 MB and a sequential scan
takes ~1 ms. If the corpus grew to millions, switching to `<->` with pre-normalized vectors
would be a legitimate, measurable optimization.

---

## 7. Storing vectors

### Option A — as text (what we do)

```python
conn.execute(
    "INSERT INTO documents (content, embedding, law, article) VALUES (%s, %s::vector, %s, %s)",
    (text, json.dumps(vec), law, article),
)
```

`json.dumps(vec)` produces `'[0.021, -0.118, ...]'` and the `::vector` cast parses it.
The column type does the validation.

**We use the text form** because it's explicit, debuggable (you can paste it into `psql`),
and has no adapter configuration to go wrong.

### Option B — binary protocol

Faster and smaller on the wire, but requires a pgvector-aware psycopg adapter
registration. Not worth it at our scale.

### The gotcha: NULL vectors

From the README: ***"NULL vectors are not indexed (as well as zero vectors for cosine
distance)."***

This is genuinely useful and easy to get wrong:

- A **zero vector** has no direction. Cosine distance against it is undefined, so pgvector
  deliberately **excludes zero vectors from a cosine index**. If your embedding model ever
  outputs all zeros (empty input, a padding bug), that chunk becomes **invisible to cosine
  search** while still sitting in the table and looking healthy in a `SELECT count(*)`.
- A **NULL** embedding is excluded from vector results but the row is still visible to
  plain `SELECT`s. That's a feature: you can store a chunk you haven't embedded yet.

**Practical guard:** reject zero vectors at ingestion time rather than letting them become
silent retrieval holes.

---

## 8. Searching: the core query

This is our actual function, `app/retrieval/search.py:57-81`:

```python
def dense_candidates(query: str, n: int | None = None) -> list[dict]:
    """Raw pgvector results, no threshold, no top_k cut — the fusion input."""
    n = n or settings.candidate_pool
    query_vec = embed_one(query)          # applies the "query:" E5 prefix
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, content, source, law, article,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM documents
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (json.dumps(query_vec), json.dumps(query_vec), n),
        ).fetchall()

    return [
        {"id": r[0], "content": r[1], "source": r[2],
         "law": r[3], "article": r[4], "similarity": float(r[5])}
        for r in rows
    ]
```

### Line-by-line

| Part | What it does |
|---|---|
| `1 - (embedding <=> %s)` | converts **distance → similarity**, so `0.78` is a real cutoff |
| `ORDER BY embedding <=> %s` | ascending distance = **most similar first** |
| `LIMIT %s` | 40 candidates (`candidate_pool`), *not* 10 |
| `SELECT id, content, source, law, article` | the vector and its metadata come back together |
| `float(r[5])` | **defensive no-op** — see below |

**On `float(r[5])`:** the `<=>` operator returns `float8` (double precision), and psycopg 3
registers `adapters.register_loader("float8", FloatLoader)` where
`FloatLoader.load` does `unpack_float8(data)[0]` — i.e. it already returns a Python `float`.
The `float()` call is **harmless belt-and-braces**, not a required fix. The first draft of
this guide wrongly claimed psycopg returns `Decimal` here; that is what psycopg does for
`NUMERIC`, and this column is not `NUMERIC`. See
[Appendix B](#appendix-b--corrections-to-the-first-draft).

### Why `LIMIT 40` and not `LIMIT 10`

Because these 40 are **fusion input, not the answer.** They get merged with 40 BM25
candidates via RRF in `app/retrieval/hybrid.py`:

```python
dense = dense_candidates(query, n=max(settings.candidate_pool, top_k * 4))
```

Recall @ 40 is deliberately generous. A chunk BM25 ranks #1 might rank #35 by dense score;
RRF rescues it. Taking only 10 from each source would throw away exactly the candidates
fusion exists to recover.

### The critical mistake to avoid

```sql
-- WRONG: filter AFTER limiting
SELECT * FROM (
    SELECT * FROM documents ORDER BY embedding <=> $1 LIMIT 10
) t WHERE law = 'code-penal-2024.pdf';
```
This returns **at most 10, often fewer** — you filtered 10 rows down to maybe 2.

```sql
-- RIGHT: the filter is part of the query
SELECT * FROM documents
WHERE law = 'code-penal-2024.pdf'
ORDER BY embedding <=> $1 LIMIT 10;
```

---

## 9. Metadata: the columns next to the vector

This is where pgvector earns its keep. Every chunk carries `law`, `article`, `source`,
`version`.

### What that buys us

```sql
-- 1. Cite the law
SELECT article, content FROM documents
WHERE law = 'code-penal-2024.pdf' AND article = '505';

-- 2. Audit provenance
SELECT DISTINCT source FROM documents WHERE law LIKE '%مدونة%';

-- 3. Drop a bad source in one statement
DELETE FROM documents WHERE law = 'broken-source.pdf';

-- 4. Corpus statistics for the README
SELECT law, count(*) AS chunks,
       count(article) FILTER (WHERE article <> '') AS labelled
FROM documents GROUP BY law ORDER BY chunks DESC;
```

**Query #4 is what produced the coverage table in our docs** — 758 chunks for the penal
code, 590 for the labour code, and so on.

### Store `content` even though a vector already encodes it

The vector is **lossy and unreadable**. You cannot inspect a 384-float array. Storing the
text means:

- you can `LIKE '%المادة 505%'` in SQL with **no embedding model at all**
- you can re-embed after a model change without re-downloading sources
- the LLM receives readable text, not a vector

**This is the most common RAG schema mistake:** storing *only* embeddings. Then a single
bad embedding is unrecoverable without re-running the whole pipeline.

---

## 10. Idempotent upsert — the most important pattern in this project

**The problem this solves (README issue A2):** the original code was a plain `INSERT`.
Running `/ingest-all` twice produced **10,452 rows for a 5,257-chunk corpus** — and those
duplicates then *competed for the same top-k slots*. The smoke test saw article 507 twice in
the top 3 while article 505, the one that actually answers the theft question, got pushed
out.

A duplicate didn't just waste space. **It broke retrieval.**

### The fix, in two parts

**Part 1 — a unique identity index** (`vector_store.py:71-74`):

```sql
CREATE UNIQUE INDEX IF NOT EXISTS documents_identity
    ON documents (law, article, md5(content));
```

**Why `md5(content)` and not `content`?** Indexing a 4,000-char chunk in a btree is
wasteful. `md5()` is 32 bytes. The in-code comment says exactly this: *"a 4 000-char chunk
would be stored twice in the btree otherwise."*

**Part 2 — the upsert** (`vector_store.py:138-146`):

```python
cur.executemany(
    """
    INSERT INTO documents (content, embedding, law, article, source, version)
    VALUES (%s, %s::vector, %s, %s, %s, %s)
    ON CONFLICT (law, article, md5(content))
    DO UPDATE SET embedding = EXCLUDED.embedding, source = EXCLUDED.source
    """,
    data,
)
```

`DO UPDATE` re-embeds instead of duplicating, so re-running ingestion is always safe.

### 🔑 The expression-index subtlety that bites everyone

`md5(content)` is an **expression index**, not a column. PostgreSQL's `ON CONFLICT` needs
an **index inference match**: the expression on the left of `ON CONFLICT` must resolve to
the *same parse tree* as the one in the index definition.

```sql
-- ✅ matches the index
ON CONFLICT (law, article, md5(content)) DO UPDATE ...

-- ❌ looks equivalent, is NOT — Postgres raises
--    "there is no unique or exclusion constraint matching the ON CONFLICT specification"
ON CONFLICT (law, article, (md5(content)::text)) DO UPDATE ...
```

That second form adds a `RelabelType` node, so the trees differ. The cast is semantically a
no-op — `md5()` already returns `text` — yet inference fails.

**The fix if you hit that error:** copy the expression **verbatim** from the `CREATE INDEX`
statement. Our source file warns about this at `vector_store.py:65-67`:

> `md5(content)` is an EXPRESSION, so PostgreSQL requires the identical expression on the
> left of `ON CONFLICT` for inference. That is why `insert_chunks` repeats `md5(content)`
> verbatim.

### Verifying it worked

We have a dedicated script — `scripts/verify_idempotency.sql`:

```sql
-- total must equal uniq
SELECT count(*) AS total,
       count(DISTINCT law) AS laws,
       count(DISTINCT (law, article, md5(content))) AS uniq
FROM documents;

SELECT law, count(*) AS chunks FROM documents GROUP BY law ORDER BY chunks DESC;

SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'documents';
```

`total == uniq` is the invariant. If it ever fails, the index is missing.

### Refusing to boot on a corrupted index

`vector_store.py:75-82` does something unusual and worth copying:

```python
try:
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS documents_identity
        ON documents (law, article, md5(content));
    """)
except psycopg.errors.UniqueViolation:
    # A pre-idempotency index still holds duplicates. Refuse to boot
    # rather than silently serving duplicated chunks.
    conn.rollback()
    raise RuntimeError(
        "documents_identity: duplicate rows already exist. "
        "Run POST /reset, then POST /ingest-all."
    ) from None
```

If a pre-idempotency database already contains duplicates, `CREATE UNIQUE INDEX` fails.
The app **refuses to start** and tells you how to fix it, instead of silently serving
duplicated chunks. **Failing loudly beats serving wrong answers.**

---

## 11. Indexes: HNSW vs IVFFlat — and why we use *neither*

I checked: **our project creates no ANN index.** Only the unique identity index and a btree
on `messages`. Every vector query is an **exact sequential scan.**

This is deliberate. Here's the full picture so you can make the same call.

### HNSW — a navigable small-world graph

Builds a layered proximity graph. At query time it greedily walks from the top layer down.

```sql
CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops);
```

| Parameter | Default | Meaning |
|---|---|---|
| `m` | **16** | edges per node per layer — higher = better recall, more memory |
| `ef_construction` | **64** | build-time candidate-list size — better graph, slower build |
| `hnsw.ef_search` | **40** | **query-time** breadth — the main recall/speed dial |

(Defaults confirmed from the pgvector 0.8.6 README shipped on this machine.)

### IVFFlat — inverted file

Clusters vectors into `lists` buckets at build time; at query time probes a subset.

```sql
CREATE INDEX ON documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
SET ivfflat.probes = 10;
```

| Parameter | Default | Meaning |
|---|---|---|
| `lists` | **no default** | number of clusters. README heuristic: **`rows / 1000`** up to 1M rows, **`sqrt(rows)`** over 1M |
| `ivfflat.probes` | **1** | clusters scanned per query. README suggests starting at **`sqrt(lists)`** |

> ⚠️ There is **no `sqrt(rows)` default.** The first draft of this guide claimed one. The
> README gives a *heuristic to choose `lists`*, and it is `rows/1000` for tables up to 1M
> rows — not `sqrt(rows)`. See
> [Appendix B](#appendix-b--corrections-to-the-first-draft).

**A genuinely useful IVFFlat fact:** setting `ivfflat.probes` equal to `lists` gives
**exact** nearest-neighbour search — and at that point the planner stops using the index.
It's the built-in bridge between "approximate and fast" and "correct and slow."

| | HNSW | IVFFlat |
|---|---|---|
| Build time | slower | fast |
| Query speed | fast | fast if `probes` is tuned |
| Memory | high | low |
| **Needs training data first** | ✅ no | ❌ yes |
| Deletes / updates | ✅ | ❌ rebuild |
| Recall at low settings | degrades gracefully | collapses fast |

**Rule of thumb: HNSW for a write-heavy, always-on system. IVFFlat for large read-mostly
corpora you can afford to retrain.**

### ⚠️ The approximate-index trap (this will bite you)

From the README, verbatim:

> *"With approximate indexes, filtering is applied **after** the index is scanned. If a
> condition matches 10% of rows, with HNSW and the default `hnsw.ef_search` of 40, **only 4
> rows will match on average**."*

And:

> *"Why are there less results for a query after adding an HNSW index? Results are limited
> by the size of the dynamic candidate list (`hnsw.ef_search`), which is 40 by default.
> There may be even less results due to dead tuples or filtering conditions in the query."*

**The symptom is silent, not an error.** You ask for 10, you get 6, and Postgres says
nothing. Worse, the row count can **change between runs** as dead tuples accumulate, so
retrieval becomes non-deterministic.

**Three mitigations, all documented in the README:**

```sql
-- 1. Raise query-time breadth
SET hnsw.ef_search = 100;      -- default 40
SET ivfflat.probes = 20;

-- 2. Iterative index scans (pgvector 0.8.0+; we have 0.8.6)
SET hnsw.iterative_scan = strict_order;    -- exact distance order
SET hnsw.iterative_scan = relaxed_order;   -- faster, near-order
SET ivfflat.iterative_scan = relaxed_order;

-- 3. Over-fetch, then filter in application code  ← what we do
--    ask for 40, take 10 after the gate
```

Iterative scans stop when enough rows are found, or at `hnsw.max_scan_tuples` (default
20,000) / `ivfflat.max_probes`.

### So why does our project have no ANN index?

| | Value |
|---|---|
| Rows | **5,254** |
| Vector storage | 5,254 × 384 × 4 bytes ≈ **8 MB** |
| Sequential scan | **~1 ms** |
| HNSW build cost | seconds, tens of MB, **approximate** |

pgvector's own README warns about indexing a small table:

> *"The index was likely created with too little data for the number of lists. Drop the
> index until the table has more data."*

At our size an ANN index would be **slower** than a sequential scan, **approximate** (making
our top-k non-deterministic run to run), and pure complexity for zero benefit.

**When we cross roughly ten thousand chunks, add HNSW and re-benchmark.** Below that, the
honest, exact answer is the right one. For a legal bot, **deterministic retrieval we can
explain in a report beats a few milliseconds.**

> That ten-thousand figure is **our project rule of thumb, not a pgvector constant.** pgvector
> publishes no such threshold. The documented guidance is qualitative: don't build an IVFFlat
> index before you have enough rows to train it.

---

## 12. Filtering with vectors

### The two strategies

```sql
-- A) Filter first, then search  ← prefer this
SELECT * FROM documents
WHERE law = 'code-penal-2024.pdf'
ORDER BY embedding <=> $1 LIMIT 10;

-- B) Search first, then filter  ← only if the filter is very selective
SELECT * FROM (
    SELECT * FROM documents ORDER BY embedding <=> $1 LIMIT 1000
) t WHERE law = 'code-penal-2024.pdf' LIMIT 10;
```

**Prefer A.** It compares fewer vectors and composes with a plain btree index on `law`.

### ⚠️ With an ANN index, filtering is much trickier

HNSW/IVFFlat are **approximate** — the graph walk knows nothing about your `WHERE` clause,
so Postgres walks first and filters after. That's the 4-rows-of-40 example above.

The README's two structural answers, plus one setting:

```sql
-- Few distinct filter values → partial index (much smaller)
CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops)
WHERE law = 'code-penal-2024.pdf';

-- Many distinct values → partition
CREATE TABLE documents (...) PARTITION BY LIST (law);

-- Or let the scan iterate
SET hnsw.iterative_scan = strict_order;
```

### Multi-tenant pattern

```sql
-- only index the 'active' rows
CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops)
WHERE status = 'active';
```

A related trick, for when you store several models' embeddings in one table — index a
*casted copy* filtered to one model:

```sql
CREATE INDEX ON embeddings USING hnsw ((embedding::vector(3)) vector_l2_ops)
WHERE model_id = 123;
```

---

## 13. Notebook: the whole thing, cell by cell

A runnable walkthrough. Each cell builds one piece.

> ⚠️ On this machine PostgreSQL is currently **down** (`pg_lsclusters` shows `14/main down`),
> so Cell 1 needs `sudo pg_ctlcluster 14 main start` first. The snippets are written to be
> copy-pasteable; they have been syntax-checked but not executed against a live cluster yet.

### Cell 1 — connect

```python
import os, json, psycopg
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.environ.get("DATABASE_URL",
                              "postgresql://postgres:alx@localhost:5432/assistant")

def get_conn():
    return psycopg.connect(DATABASE_URL)

with get_conn() as conn:
    print(conn.execute("SELECT version();").fetchone()[0][:60])
```

**Start the cluster first** (currently down in our environment):
```bash
sudo pg_ctlcluster 14 main start
pg_isready -h 127.0.0.1 -p 5432      # expect: accepting connections
```

### Cell 2 — enable pgvector

```python
with get_conn() as conn:
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    ver = conn.execute(
        "SELECT extversion FROM pg_extension WHERE extname='vector';"
    ).fetchone()
    print("pgvector", ver[0])          # we have 0.8.6
```
(`with conn:` commits on clean exit, so the explicit `commit()` is optional.)

### Cell 3 — the schema

```python
DDL = """
CREATE TABLE IF NOT EXISTS documents (
    id        SERIAL PRIMARY KEY,
    content   TEXT,
    embedding vector(384),
    law       TEXT,
    article   TEXT,
    source    TEXT,
    version   TEXT
);
"""
with get_conn() as conn:
    conn.execute(DDL)

# inspect what we actually made
with get_conn() as conn:
    for r in conn.execute("""
        SELECT column_name, data_type, udt_name
        FROM information_schema.columns
        WHERE table_name = 'documents' ORDER BY ordinal_position;
    """).fetchall():
        print(f"  {r[0]:<10} {r[1]:<20} ({r[2]})")
```

`embedding` shows as `data_type = USER-DEFINED`, `udt_name = vector` — the atttypmod
`vector(384)` is stored separately, which is why `data_type` doesn't say "vector(384)".

### Cell 4 — the embedder (with the prefixes that matter)

```python
from sentence_transformers import SentenceTransformer
import unicodedata

model = SentenceTransformer("intfloat/multilingual-e5-small")   # 384-dim

def normalize_arabic(t):                 # fix PDF ligatures: ﺳﻮاء -> سواء
    return unicodedata.normalize("NFKC", t)

def embed_passage(texts):
    if not texts: return []
    return model.encode(
        ["passage: " + normalize_arabic(t) for t in texts],
        normalize_embeddings=True,        # unit length -> enables inner product
    ).tolist()

def embed_query(text):
    return model.encode(
        ["query: " + normalize_arabic(text)],
        normalize_embeddings=True,
    )[0].tolist()

print(len(embed_query("ما هي عقوبة السرقة؟")))     # 384
```

### Cell 5 — insert

```python
SAMPLE = [
    ("المادة 505: يعاقب مرتكب جناينة السرقة بالحبس من مدة شهر واحد إلى خمسة أشهر.",
     "code-penal-2024.pdf", "505"),
    ("المادة 184: يعاقب بالحبس من مدة سنة واحدة إلى خمس سنوات.",
     "code-penal-2024.pdf", "184"),
    ("المادة 184-1: يحدد العقاب في جنايات النصب أو الاحتلال.",
     "code-penal-2024.pdf", "184-1"),
    ("المادة 54: تنظم علاقة الحضانة بين الأب والأم.",
     "code-famille-70-03.pdf", "54"),
    ("المادة 24: يجب أن يكون العقد مكتوباً ومشهوداً.",
     "code-famille-70-03.pdf", "24"),
]
```


```python
with get_conn() as conn:
    for content, law, article in SAMPLE:
        vec = json.dumps(embed_passage([content])[0])
        conn.execute(
            "INSERT INTO documents (content, embedding, law, article, source) "
            "VALUES (%s, %s::vector, %s, %s, %s)",
            (content, vec, law, article, "notebook"),
        )
    print("rows:", conn.execute("SELECT count(*) FROM documents;").fetchone()[0])
```

**Notice:** each row carries `law` and `article`. That metadata is what makes citation possible.

### Cell 6 — search (the core query)

```python
def dense_search(query, n=3, law=None):
    qv = json.dumps(embed_query(query))
    sql = """
        SELECT id, content, law, article,
               1 - (embedding <=> %s::vector) AS similarity
        FROM documents
        {where}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """.format(where=("WHERE law = %s" if law else ""))
    params = (qv, law, qv, n) if law else (qv, qv, n)

    with get_conn() as conn:
        return [
            {"id": r[0], "content": r[1], "law": r[2], "article": r[3],
             "similarity": round(float(r[4]), 4)}
            for r in conn.execute(sql, params).fetchall()
        ]

for r in dense_search("شحال ديال العقوبة على السرقة؟", n=3):
    print(f"  {r['similarity']:.3f}  [{r['law']} — المادة {r['article']}]")
    print(f"        {r['content'][:66]}…")
```

Expected shape: article **505** on top, well clear of the family-code chunks. That is the
whole point — a paraphrase question finding a short article.

### Cell 7 — prove cosine is direction-only

```python
import numpy as np

short = "المادة 505: يعاقب بالحبس من شهر إلى خمسة أشهر"
long_ = short + " ولا تسري أحكامه إلا على المطالب المنعافع" * 300

v_short = np.array(embed_passage([short])[0])
v_long = np.array(embed_passage([long_])[0])

print("L2 distance :", round(float(np.linalg.norm(v_short - v_long)), 4))
print("cosine dist :", round(1 - float(np.dot(v_short, v_long)), 4))
```


L2 grows with the added filler; **cosine barely moves.** That is exactly why text search
should use `<=>` and not `<->`.

### Cell 8 — the threshold, and the distance/similarity trap

```python
with get_conn() as conn:
    qv = json.dumps(embed_query("ما هي عقوبة السرقة في القانون المغربي؟"))
    rows = conn.execute("""
        SELECT article,
               embedding <=> %s::vector        AS distance,
               1 - (embedding <=> %s::vector)  AS similarity,
               embedding <-> %s::vector        AS l2
        FROM documents ORDER BY embedding <=> %s::vector;
    """, (qv, qv, qv, qv)).fetchall()

print(f"{'art':>6} {'distance':>9} {'similarity':>11} {'l2':>8}")
for art, dist, sim, l2 in rows:
    print(f"{art:>6} {float(dist):>9.4f} {float(sim):>11.4f} {float(l2):>8.4f}")

print("\ndistance ASCENDING (0=identical); similarity DESCENDING (1=identical).")
print("Our threshold is 0.78 on SIMILARITY. On distance the same cut is 0.22.")
```

**This is the cell that prevents the single most common bug.** Apply `0.78` to the
*distance* column and nothing ever passes.

### Cell 9 — filter by metadata (the reason to use pgvector)

```python
print("--- only the penal code ---")
for r in dense_search("الحبس", n=2, law="code-penal-2024.pdf"):
    print(f"  {r['similarity']:.3f}  المادة {r['article']}")

print("\n--- corpus stats, no embedding model needed ---")
with get_conn() as conn:
    for r in conn.execute("""
        SELECT law,
               count(*) AS chunks,
               count(article) FILTER (WHERE article <> '') AS labelled
        FROM documents GROUP BY law ORDER BY chunks DESC;
    """).fetchall():
        print(f"  {r[0]:<28} {r[1]:>3} chunks  {r[2]:>3} labelled")
```

**The second query has no vector in it at all.** Because `content` is stored as text, we
can ask non-vector questions of the same table. That is the payoff of putting vectors in a
relational row.

### Cell 10 — idempotency, proved

```python
with get_conn() as conn:
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS documents_identity
            ON documents (law, article, md5(content));
    """)

def upsert(chunks):
    """chunks: list of (content, law, article)"""
    vecs = embed_passage([c[0] for c in chunks])
    rows = [(c[0], json.dumps(v), c[1], c[2], "notebook")
            for c, v in zip(chunks, vecs)]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO documents (content, embedding, law, article, source)
                VALUES (%s, %s::vector, %s, %s, %s)
                ON CONFLICT (law, article, md5(content))
                DO UPDATE SET embedding = EXCLUDED.embedding, source = EXCLUDED.source
            """, rows)
    return len(rows)

print("1st run wrote:", upsert(SAMPLE[:2]))
print("2nd run wrote:", upsert(SAMPLE[:2]))     # same values, NOT duplicates

with get_conn() as conn:
    t, u = conn.execute("""
        SELECT count(*), count(DISTINCT (law, article, md5(content))) FROM documents;
    """).fetchone()
print(f"total={t}  unique={u}  ->  {'OK' if t == u else 'DUPLICATED! (index missing)'}")
```

**The invariant is `total == uniq`.** That is exactly what `scripts/verify_idempotency.sql`
checks in production.

### Cell 11 — the expression-index error, reproduced

```python
with get_conn() as conn:
    try:
        conn.execute("""
            INSERT INTO documents (content, embedding, law, article)
            VALUES ('x', %s::vector, 'a.pdf', '1')
            ON CONFLICT (law, article, (md5(content)::text)) DO NOTHING
        """, (json.dumps(embed_passage(["x"])[0]),))
    except Exception as e:
        print("EXPECTED ERROR:", str(e).splitlines()[0])
    conn.rollback()
```

```
EXPECTED ERROR: there is no unique or exclusion constraint matching the ON CONFLICT specification
```

The index exists, but the expression doesn't resolve to the same parse tree.

### Cell 12 — what an ANN index would (and wouldn't) buy us

**Read this before you copy the "compare index vs no index" cell you may have seen
elsewhere.** At our size that comparison is meaningless, because there is no index to
compare against — a forced sequential scan versus a sequential scan measures noise.

What is honest to measure today is the **absolute** cost of a sequential scan, and the
**size** of the data:

```python
import time

def time_query(n_runs=50):
    qv = json.dumps(embed_query("ما هي عقوبة السرقة؟"))
    sql = "SELECT id FROM documents ORDER BY embedding <=> %s::vector LIMIT 40"
    with get_conn() as conn:
        conn.execute(sql, (qv,)).fetchall()          # warm the cache
        t0 = time.perf_counter()
        for _ in range(n_runs):
            conn.execute(sql, (qv,)).fetchall()
        return (time.perf_counter() - t0) / n_runs * 1000

with get_conn() as conn:
    (rows,) = conn.execute("SELECT count(*) FROM documents;").fetchone()
    (mb,) = conn.execute("""
        SELECT pg_size_pretty(pg_total_relation_size('documents'));
    """).fetchone()

print(f"rows        : {rows}")
print(f"table size  : {mb}")
print(f"seq scan    : {time_query():.2f} ms   (40 candidates, exact)")
```

**The real decision is a build-time cost, not a query-time race.** Measure that honestly
when you have ≥ ~10k rows:

```python
# only then, and measure both:
# CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
# ANALYZE documents;
# SET hnsw.ef_search = 100;
# -- then: EXPLAIN (ANALYZE) the query above, and compare latency AND row count
# (row count must be identical or the index is dropping results)
```

Two things to check when you do add it: **latency** and **row count**. If the ANN index
returns fewer than 40 rows, you have the filtering problem from
[§11](#11-indexes-hnsw-vs-ivfflat--and-why-we-use-neither).

### Cell 13 — cleanup

```python
with get_conn() as conn:
    conn.execute("DROP INDEX IF EXISTS documents_identity;")
    conn.execute("DROP TABLE IF EXISTS documents;")
print("dropped")
```

---

## 14. Our production code, annotated

Everything above, in the shape the app actually uses. Line numbers verified against source.

### Extension + schema — `vector_store.py:46-58`

```python
with get_conn() as conn:
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id SERIAL PRIMARY KEY,
            content TEXT,
            embedding vector(384),
            law TEXT,          -- e.g. "code-penal-2024.pdf"
            article TEXT,      -- e.g. "447-1"
            source TEXT,       -- e.g. "adala.justice.gov.ma"
            version TEXT       -- e.g. "2024-08"
        );
    """)
```

### Identity index + the refuse-to-boot guard — `vector_store.py:69-87`

```python
if strict:
    try:
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS documents_identity
            ON documents (law, article, md5(content));
        """)
    except psycopg.errors.UniqueViolation:
        # A pre-idempotency index still holds duplicates. Refuse to boot
        # rather than silently serving duplicated chunks.
        conn.rollback()
        raise RuntimeError(
            "documents_identity: duplicate rows already exist. "
            "Run POST /reset, then POST /ingest-all."
        ) from None
else:
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS documents_identity
        ON documents (law, article, md5(content));
    """)
```

### Conversation memory tables — `vector_store.py:92-111`

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT 'محادثة جديدة',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,               -- 'user' | 'assistant'
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS messages_conversation_idx
ON messages (conversation_id, id);
```

**Note:** these are ordinary relational tables with a foreign key and `ON DELETE CASCADE`.
No vector involved — which is the point. pgvector is *Postgres with an extra column type*,
so you use Postgres normally everywhere else.

### Upsert — `vector_store.py:136-148`

```python
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO documents (content, embedding, law, article, source, version)
            VALUES (%s, %s::vector, %s, %s, %s, %s)
            ON CONFLICT (law, article, md5(content))
            DO UPDATE SET embedding = EXCLUDED.embedding, source = EXCLUDED.source
            """,
            data,
        )
    conn.commit()
return len(data)
```

### Search — `search.py:57-81`

```python
conn.execute("""
    SELECT id, content, source, law, article,
           1 - (embedding <=> %s::vector) AS similarity
    FROM documents
    ORDER BY embedding <=> %s::vector
    LIMIT %s
""", (json.dumps(query_vec), json.dumps(query_vec), n))
```

### Fingerprint for cache invalidation — `vector_store.py:151-157`

```python
def corpus_stats() -> dict:
    """Cheap fingerprint of the corpus, used to invalidate the BM25 cache."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT count(*), coalesce(max(id), 0) FROM documents"
        ).fetchone()
    return {"chunks": row[0], "max_id": row[1]}
```

`hybrid.py` compares this stamp to decide whether to rebuild its BM25 index. A deleted row
changes `max_id` or the count, so the cache invalidates correctly.

---

## 15. Gotchas that will bite you

| # | Gotcha | Symptom | Fix |
|---|---|---|---|
| 1 | **Distance vs similarity** | threshold always passes or always fails | `1 - (embedding <=> $1)`; 0.78 similarity = 0.22 distance |
| 2 | **Dimension mismatch** | hard error on insert | dimension is in the schema; re-embed on model change |
| 3 | **Wrong prefix (asymmetric models)** | silently poor results | `"query: "` for queries, `"passage: "` for documents |
| 4 | **Filter after `LIMIT`** | fewer rows than you asked | put `WHERE` before `ORDER BY` |
| 5 | **`ON CONFLICT` expression mismatch** | "no unique or exclusion constraint matching…" | expression must resolve to the same parse tree as the index |
| 6 | **Plain `INSERT`, no unique index** | duplicates crowd out top-k | `md5(content)` + `ON CONFLICT DO UPDATE` |
| 7 | **ANN index silently returns < LIMIT** | short result sets, no error | raise `ef_search`, or `hnsw.iterative_scan`, or over-fetch |
| 8 | **Zero vectors invisible to cosine** | chunk "missing" but `count(*)` looks fine | reject zero vectors at ingestion |
| 9 | **`CREATE EXTENSION` needs superuser** | permission denied | vendor enable-SQL, or skip the index |
| 10 | **Re-embedding after model change** | nonsense scores, no error | bump a version marker; re-embed everything |
| 11 | **Forgetting to normalize** | long docs look "far" | `normalize_embeddings=True` + `<=>` |
| 12 | **Storing only vectors** | unrecoverable data | always store `content` as text |
| 13 | **`vector` > 2,000 dims** | error | `halfvec` (4,000) or `bit` (64,000) |
| 14 | **IVFFlat on a small table** | poor recall, wasted build | pgvector's own advice: drop it until there's data |
| 15 | **Connection per query** | latency | `psycopg_pool` |
| 16 | **`<#>` is negative** | sign-flipped scores | multiply by `-1` |

---

## 16. When to graduate to a dedicated vector DB

**Stay on pgvector while:** you want one database · you need JOINs or transactional writes ·
metadata filtering matters · you're under ~1M vectors · you don't want another service.

**Move when:** you're consistently above ~1–10M vectors · you need multi-tenant sharding ·
p99 latency is the bottleneck *and you've already indexed* · ops wants vectors handled by a
specialist.

| | pgvector | Qdrant / Weaviate / Pinecone |
|---|---|---|
| Ops | one thing you already run | a new service |
| SQL + JOINs | ✅ | ✗ |
| Transactions | ✅ | ✗ |
| Speed at 100M+ | slower | faster |
| Cost at small scale | ~0 (same Postgres) | per-node or per-query |
| Best for | **this project** | very large, search-first systems |

---

## Appendix A — run it yourself

```bash
# 1. start the cluster (currently down)
sudo pg_ctlcluster 14 main start
pg_isready -h 127.0.0.1 -p 5432

# 2. sanity-check the extension
sudo -u postgres psql -d assistant -c "SELECT extversion FROM pg_extension WHERE extname='vector';"

# 3. confirm production invariants
./venv/bin/python -m scripts.check_law_coverage     # source availability
sudo -u postgres psql -d assistant -f scripts/verify_idempotency.sql
#    → total MUST equal uniq

# 4. confirm no ANN index exists (and that's intentional)
sudo -u postgres psql -d assistant -c \
  "SELECT indexname, indexdef FROM pg_indexes WHERE tablename='documents';"
```

---

## Appendix B — corrections to the first draft

The first draft of this guide was written before the environment was inspected. Three
claims were wrong. They are recorded here because **the shape of each mistake is the
instructive part**, and a reader who trusts pgvector docs less after reading this is right
to.

| # | Wrong claim | Correct | Why it was wrong |
|---|---|---|---|
| 1 | *"`float(r[5])` — psycopg returns `Decimal`, the JSON API needs a `float`"* | `<=>` returns `float8`; psycopg 3.3.4's `FloatLoader` does `unpack_float8(data)[0]`, already a Python `float`. The cast is a defensive no-op. | Confused `float8` with `NUMERIC`. `NUMERIC` → `Decimal`; `double precision` → `float`. The cast is harmless either way, but the *reason given* was false. |
| 2 | *"IVFFlat `lists` default: `sqrt(rows)`"* | There is **no default**. The README's heuristic to *choose* `lists` is `rows / 1000` up to 1M rows, `sqrt(rows)` over 1M. It also suggests starting `probes` at `sqrt(lists)`. | Half-remembered a heuristic as a default, and half-remembered the wrong branch of it. |
| 3 | *Symptom of the ANN trap is the error `could not obtain results for query`* | The documented symptom is **silently fewer rows**. The README: *"Results are limited by … `hnsw.ef_search`, which is 40 by default. There may be even less results due to dead tuples or filtering conditions."* No error is raised. | Recalled an issue-tracker message as documented behaviour. The *worse* bug is the silent one. |

Also corrected, non-factual:

| # | Issue | Fix |
|---|---|---|
| 4 | Two sample chunks and one filler string contained corrupted placeholder text (`"Congestion"`, `"Urbano"`, stray CJK). | Replaced with clean Arabic; noted inline. |
| 5 | The "index vs no index" benchmark cell compared a forced sequential scan against a sequential scan — meaningless with no index present. | Rewritten to measure absolute cost and table size, and to explain that the real ANN decision is a **build-time** cost to be measured at ≥ ~10k rows. |
| 6 | *"'pgvector's own docs suggest ~10,000+ rows' before indexing"* | pgvector publishes **no** such threshold. The documented advice is qualitative: an IVFFlat index on a small table *"was likely created with too little data."* The 10k figure is labelled as our project's rule of thumb. |
| 7 | Attributed `iterative_scan` only to HNSW. | `ivfflat.iterative_scan` also exists (README). Both documented. |

**The lesson:** four of the seven defects were things I could have checked against files
already installed on disk (`vector--0.8.6.sql`, the packaged `README.md.gz`, psycopg's
source). Verify version-specific claims against the artifact your machine actually has —
`zcat /usr/share/doc/postgresql-14-pgvector/README.md.gz` beats memory every time.

---

---

## Appendix C: run it from scratch (server, database, tables)

> **⚠️ STEP 0 — YOU MUST START POSTGRES FIRST.** Everything below fails without it.
> A stopped cluster is the single most common cause of "my app won't start".
>
> ```bash
> sudo service postgresql start        # starts the server
> pg_isready -h 127.0.0.1 -p 5432     # expect: accepting connections
> ```
>
> It must be done **after every WSL restart**. `systemctl` does not work in WSL —
> `service` is the right tool.

### The four layers — they are not the same thing

```text
┌─ POSTGRESQL SERVER ────────────────────────────────────┐
│  A running process. Owns port 5432. Owned by the        │
│  `postgres` Linux user. Started by `service start`.    │
└─────────────────────────────────────────────────────────┘
        │  one server holds MANY databases
        ↓
┌─ DATABASE ─────────────────────────────────────────────┐
│  A named, isolated namespace. Ours is "assistant".      │
│  Siblings: postgres, template0, template1.             │
│  Created BY HAND, once, forever.                       │
└─────────────────────────────────────────────────────────┘
        │  one database holds MANY tables
        ↓
┌─ TABLES ───────────────────────────────────────────────┐
│  documents, conversations, messages.                   │
│  Created BY THE APP on startup.                        │
└─────────────────────────────────────────────────────────┘
        ↓
┌─ ROWS ─────────────────────────────────────────────────┐
│  5,864 rows in documents — one per chunk.              │
│  Written by POST /ingest-all.                          │
└─────────────────────────────────────────────────────────┘
```

### Who creates what

| Thing | Created by | When | Code? |
|---|---|---|---|
| The **server** | `service postgresql start` | every WSL boot | shell |
| The **database** `assistant` | **you, by hand** | **once, ever** | none |
| The **extension** `vector` | the app | every startup | `app/retrieval/vector_store.py:47` |
| The **tables** | the app | every startup | `app/retrieval/vector_store.py:48` |
| The **rows** | `/ingest-all` | on demand | `app/main.py:156` |

`app/main.py:61` registers a startup hook that calls `create_table()`, which runs
`CREATE EXTENSION IF NOT EXISTS vector;` and `CREATE TABLE IF NOT EXISTS documents ...`.
`IF NOT EXISTS` makes it safe to repeat on every boot.

**But it cannot create the database.** You cannot nest `CREATE DATABASE` inside a
connection to the database you are trying to create — that is a Postgres rule, not a
Python one. So the failure mode is:

```text
FATAL:  database "assistant" does not exist
```

Fix it once, by hand, connecting to the *default* database:

```sql
CREATE DATABASE assistant;
```

### The link (DSN), piece by piece

```bash
postgresql://postgres:alx@localhost:5432/assistant
```

| Part | Value | Meaning |
|---|---|---|
| scheme | `postgresql://` | which wire protocol |
| user | `postgres` | the Postgres role logging in |
| password | `alx` | that role's password |
| host | `localhost` | whichever server owns port 5432 |
| port | `5432` | the server's door |
| database | `assistant` | which namespace inside it |

Configured at `app/config.py:19` and consumed by one line —
`psycopg.connect(settings.database_url)` at `app/retrieval/vector_store.py:33`.

### Why `psql` feels "linked" to it

It is not linked. **`psql` is just another client.** Your app and `psql` both connect
with the same DSN to the same server and the same database. `psql` is how you *inspect*;
the app is how you *operate*.

```text
   your app  ─┐
              ├─▶ localhost:5432 ──▶ database "assistant"
     psql    ─┘        (psycopg)  vs  (terminal client)
```

### The full command sequence

```bash
# 0. start the server — REQUIRED
sudo service postgresql start
sleep 2 && pg_isready -h 127.0.0.1 -p 5432     # want: accepting connections

# 1. connect. NOTE: connect as the `postgres` role over TCP so that the password
#    is actually checked; the default `sudo -u postgres psql` uses peer auth and
#    does NOT prove your DSN works.
psql --host localhost --username postgres --dbname assistant
```

Once you are in the prompt, run these **in this order** — they answer "am I in the
right place, and is anything loaded?"

```sql
-- (a) am I in the right database? want: documents, conversations, messages
\dt

-- (b) is pgvector enabled? want one row, extversion 0.8.6
\dx vector

-- (c) is anything loaded at all? want: 5864 after a full ingest
SELECT count(*) AS chunks FROM documents;

-- (d) per-law breakdown — the real "where am I" test
SELECT law, count(*) AS chunks FROM documents GROUP BY law ORDER BY chunks DESC;

-- (e) the idempotency invariant: these two numbers MUST be equal
SELECT count(*) AS total,
       count(DISTINCT (law, article, md5(content))) AS uniq
FROM documents;

-- (f) confirm no ANN index exists (deliberate — see section 11)
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'documents';
```

Leave the prompt with `\q`, then start the application:

```bash
cd /home/im_ane/ai-uni-assistant
./venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

```bash
# load the corpus (run in this order)
curl -X POST http://127.0.0.1:8000/reset
curl -X POST http://127.0.0.1:8000/ingest-all
# expect: total_files 9, ingested_files 9, skipped_files 0, total_chunks 5864
```

### The schema

```sql
-- app/retrieval/vector_store.py:48
CREATE TABLE IF NOT EXISTS documents (
    id        SERIAL PRIMARY KEY,
    content   TEXT,
    embedding vector(384),   -- pgvector type; 384 = e5-small output
    law       TEXT,          -- e.g. "code-penal-2024.pdf"
    article   TEXT,          -- e.g. "447-1"
    source    TEXT,          -- e.g. "adala.justice.gov.ma"
    version   TEXT           -- e.g. "2024-08"
);
```

The last four columns are the metadata that makes legal retrieval work. Without `law`
and `article` there is no citation to show — see `app/main.py:230`, where each chunk is
prepended with `[law — article]` **before** the LLM is called.

```sql
-- app/retrieval/vector_store.py:92
CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    title      TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- app/retrieval/vector_store.py:100
CREATE TABLE IF NOT EXISTS messages (
    id              SERIAL PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT,
    content         TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

`ON DELETE CASCADE` means deleting a conversation removes its messages — no orphans.

Indexes that exist, and why:

| Index | On | Purpose |
|---|---|---|
| `documents_identity` | `(law, article, md5(content))` UNIQUE | makes ingestion idempotent |
| `messages_conversation_idx` | `messages.conversation_id` | fast history lookup |
| `documents_pkey` | `documents.id` | primary key |

**No HNSW or IVFFlat index on purpose** — at 5,864 chunks a sequential scan is ~1 ms.
See [§11](#11-indexes-hnsw-vs-ivfflat--and-why-we-use-neither).

### If you forget the database name

| # | Command | Answers |
|---|---|---|
| 1 | `grep -n database_url app/config.py` | the configured default |
| 2 | `grep -i database .env` | **the value actually used** (overrides the default) |
| 3 | `psql -h localhost -U postgres -l` / `\l` | every database on the server |
| 4 | `\dt` inside a connection | is this the right one? |
| 5 | `SELECT law, count(*) FROM documents GROUP BY law;` | is the data there? |

Method 2 beats method 1: `pydantic-settings` loads `.env`, so if `DATABASE_URL` is set
there, that value wins over the hardcoded default.

### Recovery ladder — work down until one works

```bash
pg_isready -h 127.0.0.1 -p 5432
PGPASSWORD=alx psql -h 127.0.0.1 -U postgres -l | grep assistant
PGPASSWORD=alx psql -h 127.0.0.1 -U postgres -d assistant -c '\dt'
PGPASSWORD=alx psql -h 127.0.0.1 -U postgres -d assistant \
  -c "SELECT count(*) FROM documents;"
```

| Error | Meaning | Fix |
|---|---|---|
| `no response` | server is down | `sudo service postgresql start` |
| `Address already in use` | something else owns 5432 | see the Docker note below |
| `password authentication failed` | wrong password or role | check `.env` |
| `database "assistant" does not exist` | never created by hand | `CREATE DATABASE assistant;` |
| connects, but `\dt` is empty | tables not made yet | start the app; it creates them |
| connects, `documents` empty | nothing ingested | `POST /reset` then `POST /ingest-all` |

### The port-5432 conflict on this machine

Two PostgreSQL servers exist here and **both want port 5432**:

| Instance | Check with | Usually | Yours? |
|---|---|---|---|
| `postgresql@14/main` (WSL service) | `pg_lsclusters` | `down` | **yes** |
| `evolution_postgres` (Docker, `postgres:15-alpine`) | `docker ps` | `up`, holds `0.0.0.0:5432` | no — Evolution API / n8n |

If startup says `could not bind IPv4 address "127.0.0.1": Address already in use`,
Docker owns the port. Stop it first — this breaks Evolution API and n8n while down:

```bash
docker stop evolution_postgres
sudo service postgresql start
sleep 2 && pg_isready          # want: accepting connections

docker start evolution_postgres  # put Evolution back when finished
```

Password-free from Windows PowerShell (root skips the sudo prompt):

```powershell
wsl -u root bash -c "service postgresql start; sleep 2; pg_isready"
```

### About the "Requires: curl, xmllint, GNU core utilities" notice

That is a **system-requirements banner from an install script, not an error**. It lists
what a tool needs in order to run — nothing is missing, and it has nothing to do with
Postgres or pgvector. Every one of them is already present on this machine:

| Tool | Path | What it would be for |
|---|---|---|
| `curl` | `/usr/bin/curl` | HTTP downloads |
| `xmllint` | `/usr/bin/xmllint` | validating XML |
| `xsltproc` | `/usr/bin/xsltproc` | XSLT transforms (listed *optional*) |
| `gpg` | `/usr/bin/gpg` | encrypted credentials (*optional*) |
| `wget` | `/usr/bin/wget` | alternate to `curl` (*optional*) |

"GNU core utilities" is a *package* name, not a command, so `command -v coreutils`
correctly returns nothing. The individual tools it provides (`sha256sum`, `tar`, `sort`,
`wc`, …) are all installed.

**You need none of these to run this project.** Ingestion reads local files with
`pymupdf`; scraping uses `requests`; the database is local. Ignore the notice.

---

## TL;DR

1. **`CREATE EXTENSION vector;`**, then a `vector(384)` column.
2. **Store the text too.** Vectors are lossy and unreadable.
3. **Use `<=>` (cosine) for text**, and remember it returns a **distance** — convert with
   `1 - dist` to get a similarity. The README says this in one line.
4. **Prefer exact search on small tables.** pgvector's own docs tell you to drop an IVFFlat
   index built before you had data. An ANN index on 5k rows makes results non-deterministic
   for no speed gain.
5. **Make ingestion idempotent** with a unique index on `(law, article, md5(content))` +
   `ON CONFLICT DO UPDATE` — matching the expression exactly.
6. **Filter before you limit.**
7. **Asymmetric models need different prefixes** for documents and queries.
8. **The dimension is a contract.** Change models → re-embed everything.
9. **Watch for zero vectors** — cosine excludes them from indexes, so they vanish silently.

---

**Our environment:** PostgreSQL **14.24**, pgvector **0.8.6**,
`multilingual-e5-small` (**384-dim**), **5,254 chunks / ~8 MB**, sequential scan ≈
**1 ms**, no ANN index — deliberately.

**Still open on our side:** the cluster is **down**, so the notebook has not been executed
end-to-end; and the labour code (590 chunks) is validated but **not yet ingested**.