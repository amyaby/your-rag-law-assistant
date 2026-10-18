"""
tokenize.py — the ONE tokenizer in the project

Both the lexical retriever (BM25) and the keyword boost in `search.py` must cut
text exactly the same way, otherwise a term BM25 believes is rare is invisible
to the boost and vice versa. That is why this lives in its own module instead
of being copy-pasted.

THE BUG THIS FILE WAS CREATED TO FIX
------------------------------------
The original character class was:

    _WORD_RE = re.compile(r"[\\w\\u0600-\\u06ff]+")

`\\w` is already Unicode-aware and matches Arabic letters, so the extra range
looked harmless. It is not. U+0600-U+06FF is the whole Arabic block and it
CONTAINS PUNCTUATION:

    U+060C Arabic comma          ،
    U+061B Arabic semicolon      ؛
    U+061F Arabic question mark  ؟
    U+06D6..U+06ED Arabic percent, decimal, etc.

So `"السرقة؟"` tokenized to the single token `'السرقة؟'`, which appears in NO
document, and BM25 returned 0 for every query ending in a question mark — i.e.
for almost every real question in this app. Hybrid search silently degraded to
dense-only.

`\\w` alone matches Arabic letters and digits but NOT Arabic punctuation
(category Po), which is exactly the behaviour wanted here. Diacritics
(U+064B..U+0652) are category Mn and are kept, so "قُانون" and "قانون" would
still be two tokens; normalise them out below to avoid the same class of miss.
"""

import re
import unicodedata

# \w only: Unicode letters + digits. No Arabic punctuation.
_WORD_RE = re.compile(r"\w+", re.UNICODE)

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

# Arabic function words: present in every question, carry no retrieval signal.
# Removing them stops BM25 from spending IDF mass on "ما" / "في" / "the".
AR_STOPWORDS = {
    # Arabic pronouns / particles / function words
    "ما", "من", "في", "على", "و", "او", "أو", "التي", "الذي", "هذا", "هذه",
    "هل", "كم", "ثم", "كل", "بعد", "قبل", "عند", "إلى", "الى", "عن", "هو",
    "هي", "مع", "بدون", "بين", "أن", "إن", "لا", "لم", "لن", "كما", "حيث",
    "أي", "اي", "ولا", "به", "له", "بها", "لها", "هذا_المтек",
    # English function words
    "the", "and", "for", "with", "what", "which", "how", "does", "are", "you",
    "can", "tell", "about", "that", "this", "was", "were", "has", "have",
    "law", "code", "morocco", "moroccan",
}


def normalize(text: str) -> str:
    """Arabic-Indic digits -> ASCII, strip diacritics/tatweel, collapse whitespace."""
    text = text.translate(_AR_DIGITS)
    # NFD splits base letter + combining mark; dropping category 'Mn' kills
    # harakat (ً ُ ِ) and tatweel (ـ) so they cannot create phantom tokens.
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", text)


def tokenize(text: str) -> list[str]:
    """
    Lowercase -> normalise digits/diacritics -> split on word boundaries ->
    drop stop-words and 1-2 character tokens (Arabic prefixes like "ال" are
    noise on their own, and short latin tokens are usually abbreviations).
    """
    text = normalize(text).lower()
    return [
        w for w in _WORD_RE.findall(text)
        if len(w) >= 3 and w not in AR_STOPWORDS
    ]
