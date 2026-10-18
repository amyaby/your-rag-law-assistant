"""
relevance.py — "is this document actually about what was asked?"

THE BUG THIS FILE WAS CREATED TO FIX
------------------------------------
Corrective RAG runs when pgvector has no good hit, and it used to return the
output of the *first scraper that returned anything*:

    for fn in [scrape_adala_text, scrape_ism_text, web_search]:
        chunks = fn(query)
        if chunks:
            return chunks          # <-- no relevance check, ever

A live probe of `scrape_ism_text("عقوبة السرقة في القانون المغربي")` returned
three chunks extracted from:

    "عام - التبادل الإلكتروني للمعطيات القانونية"
    (General law on the electronic exchange of legal data)

...which has nothing to do with theft. The scraper "worked" - it downloaded a
real PDF from ism.ma and extracted real text. The document was simply the wrong
one. ISM matches on PDF *filenames*, and a filename match is weak evidence.

This is the same failure mode as the UAE-law bug (README issue D1), and it is
worse in one specific way. The domain allowlist does not save us here: ism.ma
really is Moroccan, so the chunk passes every provenance check we have. A
provenance filter answers "is this the right jurisdiction?" and cannot answer
"is this the right subject?". That requires a relevance check, and it has to
live at the CRAG boundary, after scraping and before generation.

WHY NOT USE THE VECTOR MODEL?
------------------------------
We could embed the query and the chunk and compare. That is more principled, and
it is deliberately NOT done here, for two reasons:

1. A single chunk is ~200-400 tokens. E5 is trained on passages, and a cosine
   between a question and one short chunk is noisy for exactly the
   "different vocabulary, same legal concept" case we care about.
2. It costs an extra forward pass per candidate inside a fallback path that
   already runs when the primary retriever failed. A cheap lexical gate first is
   the better trade.

This is a *filter*, not a ranker. It removes the obviously-off, and leaves
judgement to the LLM that receives the source text.

WHY A STEM, AND WHY A THRESHOLD
-------------------------------
Arabic is not English. "theft" and "the theft" share no characters:

    \u0627\u0644\u0633\u0631\u0642\u0629   "al-sarqah"  (definite article)
    \u0633\u0631\u0642\u0629               "sarqah"     (bare stem)

A raw substring test therefore scores the user's own phrasing as unrelated to a
document written about the same thing. This is not hypothetical - it is exactly
what made the Adala scraper return zero results for 40+ minutes of debugging
(see scraper.py). We strip the article and a few inflectional suffixes, then
score the OVERLAP FRACTION of query stems found in the document, so a long
question cannot pass by matching one incidental word.
"""

import re
import unicodedata

from app.retrieval.tokenize import tokenize

# The Arabic definite article and the clitic particles that attach to words.
# "ال" -> the, "و" -> and/but, "ف" -> so, "ب" -> with/by, "ك" -> like,
# "ل" -> for. Stripping them is what makes a question match a document title.
_AR_PREFIXES = ("ال", "وال", "بال", "كال", "فال", "لل", "وال", "و", "ف", "ب", "ك", "ل")

# Frequent nominal/verbal endings. Light "stemming" - we are matching legal
# vocabulary across a query and a document, not building a search engine, so a
# suffix list is enough and a real stemmer (no Arabic support in snowball) is
# not required.
#
# The `>= 4` minimum in stem() is load-bearing, not cosmetic. Arabic words often
# end in a plural-looking sequence by coincidence: "قانون" (law) ends in "ون",
# so a naive rule reduced it to "قان" - a 3-character stub that matched neither
# the word nor anything else, and silently defeated LEGAL_GENERIC below.
_AR_SUFFIXES = (
    "تهما", "اتهم", "ياتها", "تها",  # attached pronouns
    "ية", "ات", "ون", "ين", "ان", "ها", "هم", "هن", "كم", "كن",  # plurals / fem.
    "وا", "نا",
)


def stem(token: str) -> str:
    """
    Reduce an Arabic token to a crude stem.

    Order matters: prefixes before suffixes. Both are only stripped when enough
    of the word survives, so "laws" / "ال" cannot become an empty string (which
    would match everything).
    """
    t = unicodedata.normalize("NFC", token)
    for p in _AR_PREFIXES:
        if t.startswith(p) and len(t) - len(p) >= 3:
            t = t[len(p):]
            break
    for s in _AR_SUFFIXES:
        if t.endswith(s) and len(t) - len(s) >= 4:
            t = t[: -len(s)]
            break
    return t


def stems(text: str) -> set[str]:
    """Stems of the meaningful tokens in `text`."""
    return {stem(t) for t in tokenize(text)}


def keywords(text: str) -> list[str]:
    """
    Real (unstemmed) tokens, most distinctive first - for SEARCHING a site,
    not for scoring.

    Do not use stems() to build a search query. A live probe showed why:
        /ar/search?term=السرقة -> total 1   (the one good result)
        /ar/search?term=قانون   -> total 15  (pensions, finance, census...)
    The index is keyed on real words; a stem is a lossy form the site has never
    seen. Order: non-generic first, then longest.
    """
    generic = _generic_stems()
    toks = [t for t in tokenize(text) if stem(t) not in generic]
    return sorted(toks or list(tokenize(text)), key=len, reverse=True)


# Jurisdiction words. Every document this project can reach is already Moroccan
# legal text, so these carry no discriminative signal - but they are usually
# half the query ("... in Moroccan law"). Leaving them in the denominator makes
# a document that matches only "law" look like a 25% hit, which is the exact
# false positive the gate exists to remove. So we drop them from scoring.
#
# Concretely: query "عقوبة السرقة في القانون المغربي" has stems
# {aqouba, sarqah, qanoun, maghribi}. Counting qanoun/maghribi gave an
# off-topic document that merely mentioned "قانون" a score of 0.25 - the same
# as a genuinely on-topic page that matched the actual topic word.
LEGAL_GENERIC = {
    "قانون", "مدون", "تشريع", "جريدة", "رسمي",      # law / code / legislation / gazette
    "مغرب", "مغربي", "المغرب", "دول", "مملكة",       # Morocco / Moroccan / state
    "عقب", "معقب", "نص", "ينص",                    # article / states
}

# The list above is written the way a human reads it. Scoring compares STEMS, so
# it has to be stemmed too - otherwise "قانون" in the list never matches the
# stem of "القانون".
_GENERIC_STEMS: frozenset[str] | None = None


def _generic_stems() -> frozenset[str]:
    global _GENERIC_STEMS
    if _GENERIC_STEMS is None:
        _GENERIC_STEMS = frozenset(stem(w) for w in LEGAL_GENERIC)
    return _GENERIC_STEMS


def _scoring_stems(text: str) -> set[str]:
    """
    Stems used for scoring: generic jurisdiction words removed when something
    else survives, otherwise kept (so a query made only of generic words still
    produces a score rather than a division by zero).
    """
    s = stems(text)
    specific = s - _generic_stems()
    return specific or s


def relevance(query: str, content: str) -> float:
    """
    Fraction of the query's stems that appear in `content`, in [0.0, 1.0].

    Returns 0.0 when either side has no usable token, so a caller can treat
    "no signal" and "no overlap" identically and safely.

    Note this is a *recall*-style measure over the query only. A document that
    repeats one query stem 50 times does not score higher than one that mentions
    it once. That is intentional: BM25 already handles frequency weighting
    inside the corpus, and this function is only asked "is this on-topic at all".
    """
    q = _scoring_stems(query)
    if not q:
        return 0.0
    d = _scoring_stems(content)
    if not d:
        return 0.0
    return len(q & d) / len(q)


def matched_stems(query: str, content: str) -> list[str]:
    """Which query stems were found — for logging, so a rejection is explainable."""
    q = _scoring_stems(query)
    return sorted(q & _scoring_stems(content))


_ARTICLE_IN_QUERY = re.compile(
    r"(?:الفصل|المادة|مادة|فصل)\s*([0-9]{1,4}(?:\s*[-/]\s*[0-9]{1,3})?)"
)
_BARE_ARTICLE = re.compile(r"(?<![0-9])([0-9]{2,4}(?:\s*[-/]\s*[0-9]{1,3})?)(?![0-9])")


def query_articles(query: str) -> set[str]:
    """
    Article numbers the question names, e.g. "الفصل 505" -> {"505"},
    "المادة 447-1" -> {"447-1"}.

    Why this exists: a pure lexical score under-rates the one chunk that
    literally IS the article you asked about. Article 505 in the penal code is
    a couple of lines long, so it overlaps the query's topic words less than a
    long neighbouring article that happens to say "السرقة" and "سنة" three
    times. Measured: the theft query scored 0.500 on article 511 and would have
    scored lower on 505 - the article that actually answers it.

    A legal question naming an article is the single most common shape there
    is, and the article number is the strongest available evidence that we are
    looking at the right provision. Same idea as the evaluation harness's
    still-unused `expected_law_contains` (README F3), applied at query time.
    """
    found = {m.group(1).replace(" ", "") for m in _ARTICLE_IN_QUERY.finditer(query)}
    if found:
        return found
    # No "الفصل/المادة" marker: fall back to a bare 2-4 digit number, but only
    # if it looks like a law reference rather than a year or a quantity.
    for m in _BARE_ARTICLE.finditer(query):
        n = m.group(1).replace(" ", "")
        if not (1900 <= int(n.split("-")[0].split("/")[0]) <= 2100):
            found.add(n)
    return found


_XREF_OTHER_LAW = re.compile(
    r"(?:من|في)\s*(?:القانون|مدونة|دستور|الأمر|ظهير)\s*(?:رقم)?", re.IGNORECASE
)


def article_bonus(query: str, article: str, content: str = "") -> float:
    """
    Relevance credit for a chunk whose article number the question asked for.

    Returns 0.0 when the question names no article, or when this chunk is a
    different one. The bonus is additive and capped, so it can promote the
    right article to the top without letting a number match outrank a
    genuinely topical passage on its own.

    `content` is optional but should be passed. A number inside a citation to
    ANOTHER code is not an article of this document, and the ISM penal code
    PDF is full of them - the chunk we had been labelling `article='511'` for
    a theft question actually reads:

        "المادة 511 من القانون رقم 37.97 المتعلق بمدونة التجارة"

    which is article 511 of the *Commercial* Code. Awarding the theft bonus
    for it would promote a mis-attributed chunk to the top, so any chunk that
    cites a different law forfeits the bonus.
    """
    want = query_articles(query)
    if not want or not article:
        return 0.0
    a = str(article).strip().replace(" ", "")
    if not a:
        return 0.0
    if content and _XREF_OTHER_LAW.search(content):
        return 0.0
    if a in want:
        return 0.5
    # "447" should also match a chunk labelled "447-1" / "447/2".
    for w in want:
        if a.split("-")[0].split("/")[0] == w.split("-")[0].split("/")[0]:
            return 0.2
    return 0.0
