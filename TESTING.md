# TESTING.md — دليل Testing كامل (من 0 حتى /ask)

كلشي من الصفر: تشغيل → ingestion → verification → RAG → Corrective RAG → evaluation → UI.
كل خطوة فيها **الcommand**، **شنو كيدير**، و**المخرجات المتوقعة**.

---

## 0. Prerequisites

```bash
cd ~/ai-uni-assistant
source venv/bin/activate          # دايماً من root ديال المشروع، ماشي من app/
```
`GEMINI_API_KEY` خاصو يكون فـ `.env` (ما كيتقراش من git).

---

## 1. تشغيل PostgreSQL

```bash
wsl -u root bash -c "docker stop evolution_postgres; service postgresql start; pg_isready"
```
**المتوقع:** `/var/run/postgresql:5432 - accepting connections`

> ⚠️ `evolution_postgres` (Docker) كيخطف `5432` كل مرة وكيطيح الauth. خاصك توقفو **قبل** كل start.

---

## 2. تشغيل السيرفر

```bash
pkill -f uvicorn                                  # إلا كاين شي process قديم
cd ~/ai-uni-assistant && source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```
**المتوقع:**
```
INFO:     Started server process [PID]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

للـbackground (بلا terminal):
```bash
nohup ./venv/bin/uvicorn app.main:app --port 8000 > /tmp/uvicorn.log 2>&1 &
tail -20 /tmp/uvicorn.log
```

---

## 3. Health checks

```bash
curl -s -o /dev/null -w "root=%{http_code}\n" http://127.0.0.1:8000/     # 200 (landing)
curl -s -o /dev/null -w "ui=%{http_code}\n"   http://127.0.0.1:8000/ui    # 200 (chat)
curl -s -o /dev/null -w "css=%{http_code}\n"   http://127.0.0.1:8000/static/css/style.css  # 200
curl -s -o /dev/null -w "js=%{http_code}\n"    http://127.0.0.1:8000/static/js/app.js      # 200
curl -s -o /dev/null -w "docs=%{http_code}\n" http://127.0.0.1:8000/docs  # 200 (Swagger)
```

| Check | Expected | علاش |
|---|---|---|
| `/` | 200 | كايسرڤ `static/landing.html` |
| `/ui` | 200 | كايسرڤ `static/index.html` |
| `/static/*` | 200 | mount ديال `StaticFiles` |
| `/docs` | 200 | OpenAPI UI |

---

## 4. Ingestion (من صفر)

### 4.1 واش عندك PDFs؟
```bash
ls -lh data/docs/*.pdf | wc -l        # عدد الملفات
```

### 4.2 Reset + ingest-all
```bash
curl -X POST http://127.0.0.1:8000/reset
# {"status":"ok","message":"Table reset. Ready for fresh ingestion."}

curl -X POST http://127.0.0.1:8000/ingest-all
```
⏱️ كياخد **2-4 دقايق** (embedding محلي لكل chunk).

> ⚠️ **تنبيه: الأرقام القديمة ما بقاوش صحيحة.** الـglob ولا كيفما وليّا
> `*.pdf` + `*.txt` + `*.html`، وفـ `data/docs/` كاين غير **9 ملفات** (8 PDF + 1 TXT).
> الجواب الحقيقي المقيس فـ 2026-09-27:
>
> ```json
> {"status":"ok","total_files":9,"ingested_files":9,"skipped_files":0,"total_chunks":5864}
> ```
>
> `مدونة الشغل.pdf` محيّد، وبلاصتو `قانون 65.99 مدونة الشغل.txt` (الـPDF الرسمي
> glyph map ديالو خايب). ما بقاوش موجودَين فـ `data/docs/` لا
> `constitution_marocaine_2011-ar.pdf`.

### 4.3 Ingest PDF واحد
```bash
curl -X POST http://127.0.0.1:8000/ingest -H "Content-Type: application/json" \
  -d '{"pdf_path":"data/docs/code-penal-2024.pdf"}'
# {"status":"ok","chunks":756}
```

### 4.4 Verification فـ DB
```bash
PGPASSWORD=alx psql -h 127.0.0.1 -U postgres -d assistant \
  -c "select law, count(*) from documents group by law order by 2 desc"
```
**المتوقع (الأرقام الحقيقية، مقيسة 2026-09-27):**
```
 كتاب مجموعة القانون الاداري...pdf   | 1581
 obligations-contracts.pdf           | 1303
 code-procedure-penale-22-01.pdf     |  852
 code-penal-2024.pdf                 |  758
 قانون 65.99 مدونة الشغل.txt         |  590   ← نظيف، 590 مادة
 code-famille-70-03.pdf               |  399
 loi-31-08-consommation.pdf           |  205
 قانون الصحافة والنشر 88.13.pdf       |  121
 قانون 09.08 مرسوم تطبيقي.pdf         |   55
                                     | -----
                                     | 5864
```

> ⚠️ `مدونة الشغل.pdf` و `constitution_marocaine_2011-ar.pdf` ما بقاوش فـ
> `data/docs/`. الأول كان كيخرج **1 chunk** (glyph map خايب)، والثاني كان PDF ديال صور.
> بدل الأول ولّاو `data/docs/قانون 65.99 مدونة الشغل.txt` بـ **590 chunks**.

**Database مباشرة:**
```bash
PGPASSWORD=alx psql -h 127.0.0.1 -U postgres -d assistant \
  -c "select article, similarity from (select 1 as similarity, article from documents where article is not null limit 5) t"
PGPASSWORD=alx psql -h 127.0.0.1 -U postgres -d assistant \
  -c "select left(content, 120) from documents limit 3"
```

---

## 5. Smoke test (بلا server)

```bash
./venv/bin/python -m app.evaluation.smoke_test
```
5 sections: embeddings → vector search → ism scraper → adala scraper → web search.
**المتوقع:** `[PASS]` فكل واحد + `SMOKE TEST: ALL PASS` (exit code 0).

`WARN` ما كيخليش الscript يفشل — غير `FAIL` كيخلي `exit 1`.

---

## 6. RAG: `/ask`

### 6.1 جواب مباشر من DB
```bash
curl -s -X POST http://127.0.0.1:8000/ask -H "Content-Type: application/json" \
  -d '{"question":"ما هي عقوبة السرقة الفصل 505؟"}'
```
**المتوقع:**
```json
{"answer":"...الحبس...","sources":[{"law":"code-penal-2024.pdf","article":"505","content":"...","similarity":0.86}],
 "scraped":false,"suggestions":["..."]}
```

### 6.2 4 لغات (نفس الـendpoint)
```bash
# عربي فصيح
-d '{"question":"ما هي عقوبة النصب؟"}'
# دارجة
-d '{"question":"شنو العقوبة ديال النصب والاحتيال؟"}'
# Arabizi (كيتبعت لـGemini باش يعاود صياغتو)
-d '{"question":"kifach nt3amel m3a chikat bla rasid?"}'
# French
-d '{"question":"Quelle est la peine pour le vol de nuit?"}'
```
**المتوقع:** كل واحد `answer` + `sources` فيه `article`. فـ Arabizi/French غادي تشوف فـ terminal:
`-> rephrased: ...` (means `rephrase_query` خدم).

### 6.3 Follow-upSuggestions
نفس الـresponse فيه `suggestions: [...]` (2-3 أسئلة) — جرب كليكي واحد منهم.

---

## 7. Corrective RAG (CRAG)

```bash
# سؤال ما كاينش فـ DB (حقوق المؤلف)
curl -s -X POST http://127.0.0.1:8000/ask -H "Content-Type: application/json" \
  -d '{"question":"حقوق المؤلف والحقوق المجاورة؟"}'
```
**المتوقع:**
- JSON: `"scraped": true`
- Terminal: `[CRAG] corrective -> N live chunks for: حقوق المؤلف...`

**Trigger:** `top_score < 0.78` (`app/main.py:128`). الترتيب: `adala` → `ism` → `web`.

**Scrapers يدوياً:**
```bash
./venv/bin/python -c "from app.retrieval.ism_scraper import list_ism_pdfs; print(len(list_ism_pdfs()))"    # 161
./venv/bin/python -c "from app.retrieval.corrective import corrective_search; print(len(corrective_search('الحضانة')))"
```

---

## 8. Evaluation (15 سؤال)

```bash
./venv/bin/python -m app.evaluation.evaluate
```
**المتوقع:**
```
============================================================
Q1 [ar/السرقة]: ما هي العقوبة الأساسية للسرقة؟
  retrieval: 10 hits, top_sim=0.860
  -> fact: 100% (2/2) citation: 1 retrieval_ok: 1
     found articles: {'505','506'} | expected one of: {'505','506','508','509'}
...
OVERALL: fact 68% | citation 80% | retrieval 87% (15 Qs)
```
⏱️ **2-4 دقايق** + ~30 Gemini calls (quota!).

---

## 9. inspect PDF (diagnostic)

```bash
./venv/bin/python scripts/inspect_pdf.py data/docs/code-penal-2024.pdf   # PDF واحد
./venv/bin/python scripts/inspect_pdf.py data/docs/                      # Directory كامل
```
كيطبع: size, chars, chunks, chunk sizes, article numbers, verdict, text preview.

**الـverdicts:**
| Verdict | المعنى |
|---|---|
| `OK - one article per chunk` | PDF سليم |
| `FAIL - single chunk` | الregex ديال `المادة/الفصل` ما لقاش → chunk واحد ضخم |
| `FAIL - chunks are huge` | fallback ديال size-based chunking |
| `WARN - many chunks without an article` | الـmetadata ناقصة |

**حالياً:**
- `مدونة الشغل.pdf` → 1 chunk + نص **معكوس** (حروف مقطّعة) = الـRTL text layer خايب فـ PDF.
- `constitution_marocaine_2011-ar.pdf` → 82 حرف فقط = PDF ديال صور (scanned) → خاصو **OCR**.

**الحل ديالهم:** استعمل PDF نظيف من `ism.ma` (نفس النص، extracted text صحيح)، ولا OCR بـ Tesseract (`ara`).

---

## 10. UI (يدوي)

| Page | Check |
|---|---|
| `http://127.0.0.1:8000/` | ticker كيتحرك، Rakkas title، red brand، زرار `ابدأ المحادثة` كيودي `/ui` |
| `http://127.0.0.1:8000/ui` | sidebar (يمين), 12 pill buttons, red theme, chat |
| Chat | سول → جواب + `📂 المصادر` + chips ديال follow-up |
| Sidebar | `+ محادثة جديدة` كيبدا conversation جديد |
| Persistence | `localStorage.law_convs` — refresh وكي剩余] الجواب ديال قبل |
| Hard refresh | `Ctrl+Shift+R` باش تشوف أي تعديل CSS |

**Console (F12):**
```js
localStorage.getItem("law_convs")   // كايبان l'array ديال المحادثات
```

---

## 11. Troubleshooting

| Error | Causé | Fix |
|---|---|---|
| `Address already in use` | process قديم | `pkill -f uvicorn` |
| `password authentication failed for user postgres` | Docker `evolution_postgres` خا Balkanي 5432 | `docker stop evolution_postgres; service postgresql start` |
| `503 UNAVAILABLE ... high demand` | Gemini overloaded | عاود من بعد، ولا fallback model |
| `429 RESOURCE_EXHAUSTED` | quota | استنى، ولا بدّل model |
| `ModuleNotFoundError: No module named 'app'` | خايبتي فـ `app/` | `cd ~/ai-uni-assistant` |
| `fitz API is deprecated` | PyMuPDF warning | harmless |
| `HF Hub unauthenticated` | بلا HF_TOKEN | harmless |
| `[WARN] duplicate chunks in DB` | ingest بلا reset | `POST /reset` ثم `POST /ingest-all` |
| Landing ما كايبانش | cache | `Ctrl+Shift+R` |

---

## 12. Reset كامل (من الصفر literally)

```bash
pkill -f uvicorn
wsl -u root bash -c "docker stop evolution_postgres; service postgresql start"
cd ~/ai-uni-assistant && source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# (terminal آخر)
curl -X POST http://127.0.0.1:8000/reset
curl -X POST http://127.0.0.1:8000/ingest-all
./venv/bin/python -m app.evaluation.smoke_test
```
