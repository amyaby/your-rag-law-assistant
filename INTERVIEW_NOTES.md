# Interview Notes — Moroccan Legal RAG

This document is designed for quick revision before technical interviews (defense + internship/recruiter interviews). Keep answers short, concrete, and backed by code.

## 1. What Recruiters Actually Want From You

For a PFE/internship technical interview, they want to verify **three things** above all:

1. **You can explain what you built, not just what it does.** Explain the *why* behind design choices (hybrid vs pure dense, RRF, article-aware chunking, CRAG). Cite concrete line numbers when pressed.
2. **You wrote/understand the code, not that you stitched tutorials.** They expect you to be able to trace one request end-to-end, point to real code, and justify trade-offs. The rule: *"explain, don't recite"*.
3. **You tested it and know its limits.** Proof > claims. Be ready to say: "PostgreSQL + pgvector, ingested 9 files → 5,864 chunks, I tested X and Y and got Z, with these citations." Also know known bugs + future work.

**Key expectation:** *You must be able to reason through the code on your own and test it yourself.* Tutorials helped you learn concepts, but you must defend **your implementation** (choices, thresholds, fixes).

## 2. The 8 Things You Must Be Able To Explain

Memorize these in order. 30-second answers each:

1. **Why embeddings?** Different wording, same meaning (paraphrase). Keyword search misses synonyms; dense vectors capture semantic similarity (e.g. "عطلة سنوية" vs inflected forms).
2. **Why a Vector DB + Postgres (not Pinecone)?** All data (metadata: `law`, `article`, `source`, `version`, IDs) lives in the same row. pgvector keeps retrieval + metadata + memory in one ACID DB (no extra service, easier to reason about, idempotent upserts). Simpler for a uni project + defensible.
3. **Why cosine `<=>` and `1 - distance = similarity`?** `<=>` is cosine distance (0 = same direction, 1 = opposite). We invert to similarity (0→1, higher = better) for human-readable thresholds (`0.78`).
4. **Why Hybrid (BM25 + Dense + RRF)?** Neither is enough alone. Dense is fuzzy (misses exact numbers/articles). BM25 is exact-term driven (loses paraphrase). RRF merges ranks without comparing incompatible scores (cosine 0–1 vs BM25 0–30). It's the standard (Cormack et al. SIGIR 2009).
5. **Why article-aware chunking?** Legal answers must cite an article (الفصل/المادة). Fixed-size chunking cuts across article boundaries and loses the label. `article_chunks()` preserves `law` + `article` per chunk — those labels become citations at `main.py:230`.
6. **Why idempotent upsert?** Prevents duplicates on re-ingestion. Without `(law,article,md5(content))` identity, re-running `/ingest-all` could duplicate chunks and push the correct article (e.g. 505) down the results. Invariant: `total == uniq`.
7. **What is Corrective RAG (CRAG)?** DB has nothing useful OR best dense similarity < threshold (`crag_needed`, `retriever.py:41–52`) → fetch live from Adala → ISM → DDG (.ma only). Scraped chunks get `relevance >= 0.25`, get article bonus, are prepended (not fused via RRF) and capped (`context_max_chunks=10`).
8. **Biggest known weak point?** `app/retrieval/robots.py` does **not** enforce path-specific Disallow rules (only a coarse/global view in places). Also `list_ism_pdfs()` historically bypassed the shared guarded path in that area (documented defect) — needs per-path cache/parser fix + regression test.

## 3. Pipeline Trace (One Question) — Must Know Cold

Question: `"كم يوم عطلة سنوية؟"`

```text
POST /ask
  ├─ main.py:184 ask()
  ├─ llm.py:157 rephrase_query()  (Darija→Arabic; if already Arabic → returns unchanged, llm.py:166–168)
  ├─ retriever.py:25 retrieve()   (single entry point, returns (results, name))
  │   └─ hybrid.py:135 hybrid_search()
  │       ├─ tokenize.py:68 tokenize(query)  → ["يوم","عطلة","سنوية"] (كم removed = stopword)
  │       ├─ hybrid.py:153 get_index()        (corpus fingerprint cache, built once)
  │       ├─ search.py:57  dense_candidates()  (pgvector <=>, LIMIT 40, embed with query: prefix)
  │       ├─ hybrid.py:154 BM25.scores()      (IDF over 5,864, k1=1.5,b=0.75)
  │       ├─ hybrid.py:155–163 top 40 BM25
  │       └─ hybrid.py:165–229 RRF fusion (w_dense=1.0, w_sparse=0.35, k=60) → sort by (rrf_score, score)
  ├─ retriever.py:41 crag_needed()  (best dense < 0.78 OR empty?)
  │   └─ corrective.py (Adala → ISM → DDG .ma) if triggered
  ├─ main.py:230 context assembled  (labels: "[{law} — المادة {article}]\n{content}")
  └─ llm.py:221+  generate_answer(original question, context, history)
```

## 4. Key Numbers To Memorize

| Value | Where | Meaning |
|---|---|---|
| `0.78` | `config.py:26` | Cosine similarity threshold ("retrieval good enough?") |
| `40` | `config.py:29` | `candidate_pool` — fetch 4× top_k before fusion (room to rerank) |
| `0.35` | `config.py:33` | `bm25_weight` — lexical is tie-breaker, dense dominant |
| `60` | `config.py:32` | `rrf_k` — RRF constant (1/(k+rank)) |
| `10` | `config.py:21,70` | `top_k`, `context_max_chunks` |
| `0.25` | `config.py:67` | `crag_min_relevance` (scraped chunks must pass) |
| `5,864` | Measured | Chunks after ingest (9 files: 8 PDFs + Labour TXT) |

## 5. Tricky Interview Questions + Suggested Answers

| Question | Answer (concise) |
|---|---|
| **"Why RRF instead of weighted sum?"** | Cosine (0–1) and BM25 (0–30) aren't comparable. Weighted average is arbitrary. RRF discards scores and uses ranks only: `RRF(d)=∑ 1/(k+rank_r(d))` (k=60). This rewards consensus without normalizing different scales. (`hybrid.py:131–132, 165–173`) |
| **"If admission was only `similarity >= 0.78`, what happens to a BM25-only hit?"** | It has `similarity = 0.0` (never seen by pgvector, `hybrid.py:186–189`). It would be rejected entirely, so BM25 would only *reorder* dense hits (not add lexical-only results) — effectively reducing hybrid back to dense+boost (no true fusion). The fix: `OR bm25_score >= best_bm25 * bm25_admit_ratio` (`hybrid.py:213–221`) admits strong lexical hits even with 0.0 cosine. |
| **"Why not rewrite Arabic queries?"** | `rephrase_query` checks `has_arabic` (`llm.py:166–168`). If already Arabic, it returns unchanged. Rewriting a clean Arabic legal query tends to degrade retrieval (loses exact article numbers/terminology). It only activates for Arabizi/French/English. Also `generate_answer` receives the **original** question (`main.py:246`) — we search with normalized/formal terms, answer in natural form to the user (intent preserved). |
| **"Where do citations come from?"** | Chunks carry `law`, `article` from ingestion/chunking. At `main.py:230` we prepend `"[{law} — المادة {article}]\n{content}"` to form context *before* calling the LLM. The LLM is instructed to cite the exact article (SYSTEM_INSTRUCTION). Citations come from stored metadata, not hallucinated. |
| **"Why fetch 40, return 10?"** | `candidate_pool=40` (`config.py:29`) gives fusion breathing room. Dense top-10 might miss the chunk that contains the exact number; BM25 might push it from rank 35→top 5 after RRF. We fuse over 40 from each, sort by RRF, cut to `top_k=10`. (`hybrid.py:148, 155–159, 229–232`) |
| **"CRAG vs Hybrid — when do they fire?"** | Hybrid runs **always** (`use_hybrid=True`). CRAG runs **only** when retrieval is insufficient: `crag_needed` checks best dense similarity < 0.78 OR no results (`retriever.py:41–52`), called at `main.py:213`. CRAG is a fallback (Adala→ISM→DDG), not part of fusion (scraped prepended at `main.py:221`, capped at 10). |
| **"Why tokenize if we only chunk?"** | Chunk = document segmentation (units to retrieve/embed). Tokenize = term segmentation (for BM25 index + keyword boost). Different layers: embeddings use chunk text; BM25 builds `tf/df/idf` over token lists (`hybrid.py:69–76, 120`). Same normalization (NFKC, diacritics stripped, Arabic digits→ASCII, stopwords removed) to avoid mismatches (`tokenize.py:58–78`). |
| **"Why not Selenium?"** | Data is server-rendered. Adala exposes `__NEXT_DATA__` (JSON) in HTML (`scraper.py:137–142`), ISM panels are in HTML (Bootstrap `data-bs-target`), DDG static HTML. We extract JSON + direct PDF GETs (`/api/{path}`) via `requests`. Faster, deterministic, easier to enforce same UA + `robots.txt` + throttling in one `_get()` path. Selenium only needed if fully client-rendered with no embedded payload (signal: `pageProps` empty). Current approach is better here. |

## 6. Practical Tips For The Interview

- **Trace, don't dump.** If asked "how does a question flow?", use the 6-file pipeline above (30s max). Point to line numbers.
- **Admit limits.** Say: "robots.py needs per-path Disallow enforcement + regression test; local hybrid hits don't yet apply `relevance()`/`article_bonus()` (documented gaps). Future work: curated ISM subset for reproducibility."
- **Testing > theory.** Be ready to show: `/ingest-all` gives 5,864 chunks, test article 505 + annual leave, inspect `sources` (dense_rank/bm25_rank/rrf_score).
- **Code-on-your-own rule.** State it clearly: "I learned concepts, implemented fixes myself, verified with tests (`compileall`, `scripts/check_*.py`, `audit_issues.py` pass). Tutor reviewed, I wrote non-trivial changes."
- **Ethics + compliance.** Mention honest User-Agent, throttling, `.ma`-only allowlist for DDG, Moroccan markers (prevents wrong-jurisdiction leakage), PDF magic-byte check (`%PDF`), min chars/Arabic ratio.
- **Reproducibility vs freshness.** CRAG = live freshness (long tail), DB = reproducible/deterministic (demo stability). Good trade-off.

## 7. Common Pitfalls To Avoid

- Saying "we scrape links" — clarify: extract HTML/JSON → download PDFs (PyMuPDF) OR extract HTML text → chunk via `article_chunks()` (all normalized to same shape).
- Confusing chunk vs token.
- Saying RRF averages scores (it doesn't — uses ranks).
- Forgetting `rephrase_query` returns unchanged if Arabic.
- Claiming untested work ("it should work") — say "tested X, saw Y".

## 8. One-Minute Self-Intro Hook (Suggested)

*"I built a Moroccan legal RAG: pgvector hybrid (BM25+dense) fused with RRF, article-aware chunking, and CRAG (Adala→ISM→DDG, .ma-restricted). Ingestion: 9 sources → 5,864 chunks, idempotent. I focused on correctness (article citations, jurisdiction guardrails, idempotency) and traceability (retriever name + per-chunk ranks in responses)."*
