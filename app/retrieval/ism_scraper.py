"""
ism_scraper.py — ISM (ism.ma) scraper for Corrective RAG
Source: https://ism.ma/%d8%af%d8%b1%d8%a7%d8%b3%d8%a7%d8%aa-%d9%88%d8%a3%d8%a8%d8%ad%d8%a7%d8%ab/%d9%86%d8%b5%d9%88%d8%b5-%d9%82%d8%a7%d9%86%d9%88%d9%86%d9%8a%d8%a9/
Structure: WordPress static HTML -> h2/h3 المادة الجنائية -> ul -> a[href*=.pdf] -> PDF direct
"""
import re
import time

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

ISM_URL = "https://ism.ma/%d8%af%d8%b1%d8%a7%d8%b3%d8%a7%d8%aa-%d9%88%d8%a3%d9%86%d8%ad%d8%a7%d8%ab/%d9%86%d8%b5%d9%88%d8%b5-%d9%82%d8%a7%d9%86%d9%88%d9%86%d9%8a%d8%a9/"
BASE = "https://ism.ma"
HEADERS = {"User-Agent": "MoroccanLawRAG-StudentProject/1.0 (educational RAG research)"}
TIMEOUT = 15

# ism.ma's robots.txt is a 164-byte Yoast stub with an empty Disallow, i.e. it
# permits crawling. We still space out requests: 161 PDFs at full speed is not
# what "permitted" is asking for, and this is someone else's public server.
_REQUEST_GAP = 1.5
_last_request = 0.0

# Topic -> ISM section, used ONLY when no listing is titled after the query.
# The key is a legal topic; the value is the ISM "المادة ..." heading that
# contains it. This is domain knowledge stated explicitly, and every use is
# logged, so it can be corrected by a lawyer rather than guessed at by code.
# Verified against the live 161-listing index: theft and custody have no PDF of
# their own, so without this map those questions silently lose the ISM source.
_TOPIC_SECTIONS = {
    "المادة الجنائية": (
        "سرق", "جريم", "عقوب", "قتل", "اغتيال", "كراه", "نصب", "احتيال",
        "رشوه", "اعتداء", "جناي", "مجرم", "فاضح", "زنا", "شيك",
    ),
    "المادة الأسرية": (
        "حضان", "زواج", "طلاق", "نكاح", "تبني", "خطبه", "جهه", "ولد",
        "نسب", "نفقه",
    ),
    "المادة الاجتماعية": (
        "شغل", "اجر", "عمل", "نقاب", "ضمان", "عطل", "تسريح", "ساعات",
        "خدمه",
    ),
    "المادة المدنية": (
        "معطيات", "رقم", "حمايه", "عقد", "مسؤول", "تعويض", "اثبات", "حق",
        "ارث", "كفاله",
    ),
    "المادة العقارية": (
        "عقار", "تحفيظ", "ايجار", "بناء", "قسمه", "رهن", "سكن", "ارض",
    ),
    "المادة التجارية": (
        "تجاره", "شرك", "مقاوله", "سند", "غش", "استهلاك", "بنك", "مؤسسه",
    ),
    "المادة الإدارية والمالية": (
        "ماليه", "جبائي", "ضريبه", "ميزاني", "مناصب", "نفقات", "خزينه",
    ),
    "المادة البيئية": (
        "بيئي", "ماء", "نفايات", "غابات", "مخلف", "معادن", "تلوث", "طاقه",
    ),
    "المادة الصحية والطبية": (
        "صحه", "طبيب", "دواء", "تمريض", "مستشف", "صيدله", "تحاليل", "ولاده",
    ),
    "التنظيم القضائي": (
        "قضائي", "محكمه", "نقض", "استئناف", "محام", "موثق", "خبير", "ترجمه",
    ),
    "المادة الدستورية": ("دستور", "جمهور", "انتخاب", "حريه", "برلمان"),
    "المادة الكرائية": ("كرائي", "حجز", "مالك", "تجديد"),
    "حقوق الإنسان": ("حقوق", "انسان", "معتقل", "محكوم"),
}


def _categories_for(query: str) -> list[str]:
    """
    Which ISM sections plausibly contain this topic? Best guess first.

    Matching is PREFIX-compatible, not exact. The map keys are word ROOTS and
    the stemmer returns INFLECTED forms, so exact set intersection can never
    work - measured:

        "الحضانة"      -> stem "حضانة"   vs map "حضان"   no match
        "شركة تجارية" -> stems {تجار, شركة} vs map {تجاره, شرك}  no match

    Arabic attaches mostly as prefixes and endings, so a root is nearly always
    a prefix of the inflected form, and `a.startswith(b) or b.startswith(a)`
    lines them up. The floor is 3, not 4: legitimate Arabic legal roots are
    that short ("شغل", "عقد", "سند", "غش", "قتل") and a 4-char floor silently
    dropped them - "ما هي حقوق العامل في الشغل" routed to nothing at all.
    """
    from app.retrieval.relevance import stems

    q = [s for s in stems(query) if len(s) >= 3]

    def compatible(a: str, b: str) -> bool:
        if len(a) < 3 or len(b) < 3:
            return False
        return a == b or a.startswith(b) or b.startswith(a)

    scores: dict[str, int] = {}
    for section, kws in _TOPIC_SECTIONS.items():
        for kw in kws:
            for k in stems(kw):
                if any(compatible(qs, k) for qs in q):
                    scores[section] = scores.get(section, 0) + 1
                    break

    return [s for s, _ in sorted(scores.items(), key=lambda t: -t[1])]


def _resolve_section(key: str, live: list[str]) -> str | None:
    """
    Map a map-key onto the site's CURRENT category string.

    The site is not frozen: our key "التنظيم القضائي" is really served as
    "التنظيم القضائي والمهن القضائية". A hard == would silently stop routing,
    so match on the longest shared prefix instead and let the caller log any
    key that no longer resolves.
    """
    if key in live:
        return key
    best, best_n = None, 0
    for c in live:
        n = 0
        for a, b in zip(key, c):
            if a != b:
                break
            n += 1
        if n > best_n:
            best, best_n = c, n
    # require a real overlap, not a coincidental first character
    return best if best_n >= 6 else None


_SECTION_RE = re.compile(
    r"^\s*(المادة\s|التنظيم القضائي|حقوق الإنسان|عام)"
)


def list_ism_pdfs() -> list[dict]:
    """
    Fetch the ISM law index and return [{category, title, url}] for every PDF.

    STRUCTURE, verified against the live page on 2026-09-27 (191 KB, 161 PDFs):

        <button class="accordion-button" data-bs-target="#flush-collapseOne-7">
            المادة الجنائية
        </button>
        <div class="accordion-collapse" id="flush-collapseOne-7">
            <ul><li><a href="/pdf/ARABE/xxx.pdf">مجموعة القانون الجنائي</a></li>...

    The old parser looked for the section name in an <h2>/<h3>. Those headings
    on this page are "نصوص قانونية", "وزارة العدل", "محكمة النقض", "التصفح" -
    none of them are sections. So the filter matched nothing, `out` stayed
    empty, and every one of the 161 PDFs came back from the fallback branch
    with category "عام".

    That is not cosmetic. Category is what a legal question is routed on, so
    "any PDF" is what the scraper effectively searched: it could not tell a
    family-law PDF from a tax one, which is a large part of why ISM answered a
    theft question with an electronic-exchange circular (D5).
    """
    html = requests.get(ISM_URL, headers=HEADERS, timeout=TIMEOUT).text
    soup = BeautifulSoup(html, "html.parser")

    if len(html) < 2000:
        print(f"[ism] empty or blocked page, len={len(html)}")
        return []

    out: list[dict] = []
    seen: set[str] = set()

    # Preferred: the accordion button -> its collapse panel -> the PDF list.
    for btn in soup.select("button.accordion-button, [data-bs-target]"):
        cat = btn.get_text(strip=True)
        if not _SECTION_RE.match(cat):
            continue

        target = (btn.get("data-bs-target") or "").lstrip("#")
        panel = soup.find(id=target) if target else None
        if panel is None:
            panel = btn.find_next(class_=re.compile("accordion-collapse|collapse"))
        if panel is None:
            continue

        for a in panel.find_all("a", href=lambda x: x and ".pdf" in x):
            href = a["href"]
            url = href if href.startswith("http") else urljoin(BASE, href)
            if url in seen:
                continue
            seen.add(url)
            out.append({"category": cat, "title": a.get_text(strip=True),
                        "url": url})

    if not out:
        # The page layout changed. Rather than silently mislabel everything,
        # say so - a silent fallback that invents a category is how D5 happened.
        print("[ism] WARNING: no accordion sections found; category will be "
              "'عام' for all PDFs and legal questions cannot be routed")
        for a in soup.find_all("a", href=lambda x: x and ".pdf" in x):
            url = a["href"] if a["href"].startswith("http") else urljoin(BASE, a["href"])
            if url not in seen:
                seen.add(url)
                out.append({"category": "عام", "title": a.get_text(strip=True),
                            "url": url})

    return out


def scrape_ism_text(query: str, max_chunks: int = 3) -> list[dict]:
    """
    Live fallback: score the 161 PDF listings against the query, download the
    best few IN MEMORY, and chunk them.
    Two changes worth explaining, both prompted by reviewing an external
    scraper and by the D5 bug this function caused.

    1. Selection used to be substring matching:

           any(w in p["title"] or w in p["category"] for w in keywords)

       which is why "عقوبة السرقة" selected a document about the electronic
       exchange of legal data - the wrong subject entirely. It is now scored
       with relevance() against title + category, and the score is logged, so a
       bad pick is visible instead of silent.

    2. Downloading used tempfile.NamedTemporaryFile + subprocess curl, then
       read the file back. Three problems: the PDF touched the filesystem for no
       reason, a failed curl left the temp file behind (os.unlink is after the
       read, and never runs if fitz.open raises), and curl bypasses the
       robots/throttle path every other request goes through. Now:

           doc = fitz.open(stream=resp.content, filetype="pdf")

       No disk, no subprocess, and the .ma allowlist plus the request gap apply
       to PDFs as well as listings.
    """
    from app.config import settings
    from app.ingestion.chunker import article_chunks
    from app.retrieval.relevance import article_bonus, relevance
    from app.retrieval.robots import allowed

    global _last_request    # otherwise the assignment below shadows the module global

    try:
        all_pdfs = list_ism_pdfs()
    except Exception as e:
        print(f"[ism] list failed: {e}")
        return []
    if not all_pdfs:
        return []

    threshold = settings.crag_min_relevance
    scored = []
    for p in all_pdfs:
        score = relevance(query, f"{p['title']} {p['category']}")
        if score >= threshold:
            scored.append((score, p))
    scored.sort(key=lambda t: -t[0])

    if not scored:
        # No listing is titled after the query. This is the NORMAL case for
        # topic questions, not an edge case - verified against the live index:
        #   "حضانة" -> 0 of 161 listings contain it
        #   "سرقة"  -> 0 of 161 listings contain it
        # because custody and theft are CHAPTERS inside مدونة الأسرة and
        # مجموعة القانون الجنائي, not separate PDFs. A filename-indexed library
        # structurally cannot answer "what is the penalty for theft".
        #
        # The old code papered over this with a guess: if the query looked
        # legal, grab 2 PDFs from penal/family law and hope. That is how a
        # data-exchange circular ended up answering a theft question (D5).
        #
        # Instead we use an explicit topic -> ISM category map. It is domain
        # knowledge, stated openly and logged, rather than a hidden heuristic.
        print(f"[ism] no listing is titled after the query; "
              f"falling back to the topic->category map")
        live = sorted({p["category"] for p in all_pdfs})
        for key in _categories_for(query):
            cat = _resolve_section(key, live)
            if cat is None:
                print(f"[ism] map key {key!r} matches no live category "
                      f"(site may have renamed it)")
                continue
            picked = [p for p in all_pdfs if p["category"] == cat]
            if picked:
                print(f"[ism] topic map: {key!r} -> live {cat!r} "
                      f"({len(picked)} PDFs)")
            for p in picked:
                scored.append((0.2, p))   # 0.2 < threshold: a hint, not a claim
            if picked:
                break

    if not scored:
        print(f"[ism] nothing on-topic in {len(all_pdfs)} listings")
        return []

    for score, p in scored[:3]:
        print(f"[ism] candidate {p['title'][:44]!r} relevance={score:.3f}")
        try:
            if not allowed(p["url"]):
                print(f"[ism] robots.txt disallows {p['url'][:60]}")
                continue

            wait = _REQUEST_GAP - (time.monotonic() - _last_request)
            if wait > 0:
                time.sleep(wait)
            _last_request = time.monotonic()

            resp = requests.get(p["url"], headers=HEADERS, timeout=30)
            resp.raise_for_status()
            if b"%PDF" not in resp.content[:1024]:
                print(f"[ism] {p['url'][:50]} is not a PDF")
                continue

            import pymupdf as fitz
            doc = fitz.open(stream=resp.content, filetype="pdf")
            # "\n" not "": without a separator the last word of page 1 is welded
            # to the first word of page 2.
            text = "\n".join(page.get_text() for page in doc)
            doc.close()

            if len(text.strip()) < settings.min_pdf_chars:
                print(f"[ism] {p['title'][:34]!r} unusable: "
                      f"{len(text.strip())} chars (scan or broken text layer?)")
                continue

            law = f"{p['category']} - {p['title']}"
            chunks = article_chunks(text, law=law[:60], source=f"ism:{p['url']}")
            if not chunks:
                continue

            # Return the BEST chunks, not the first ones.
            #
            # The penal code is 1,581 chunks long and theft sits around article
            # 505, roughly 800 chunks in. `chunks[:max_chunks]` returned
            # articles 1.1 / 3.3 / 511 - the head of the document - and CRAG
            # then dropped all of them at relevance 0.000, correctly but
            # uselessly. CRAG cannot fix this itself: it is only ever handed
            # `max_chunks` candidates, so the choice has to be made here, where
            # the whole document is still in memory.
            #
            # `article_bonus` is what actually surfaces the article the user
            # named. Article 505 is two lines long, so it overlaps the query's
            # topic words *less* than a long neighbouring article that says
            # "السرقة" and "سنة" repeatedly. Lexical scoring alone therefore
            # prefers article 511 over the 505 that answers the question.
            for c in chunks:
                base = relevance(query, c.get("content", ""))
                bonus = article_bonus(query, c.get("article", ""),
                                      c.get("content", ""))
                c["relevance"] = round(min(1.0, base + bonus), 3)
            chunks.sort(key=lambda c: -c["relevance"])
            top = chunks[:max_chunks]
            print(f"[ism] {law[:34]!r}: {len(chunks)} chunks, "
                  f"best={top[0]['relevance']:.3f} "
                  f"(article={top[0].get('article')!r}), returning {len(top)}")
            return top

        except Exception as e:
            print(f"[ism] pdf {p['url'][:40]} fail {type(e).__name__}: {e}")
            continue

    return []
