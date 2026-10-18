"""Unit tests for the CRAG relevance gate. No network, no database."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.retrieval.relevance import relevance, stem, stems, matched_stems

AT = "\u0627\u0644"                                  # "al-"
SARQAH = "\u0633\u0631\u0642\u0629"                  # "sarqah"  theft
AQOUBA = "\u0639\u0642\u0648\u0628\u0629"             # "aqouba"  penalty
QANOUN = "\u0642\u0627\u0646\u0648\u0646"            # "qanoun"  law
TAQATIL = "\u062a\u0642\u0627\u062a\u064a\u0644"      # "taqatil" murders
BADALAH = "\u0628\u0627\u062f\u0644\u0629"            # "badalah" exchanges
ILAYTI = "\u0625\u0644\u0643\u062a\u0631\u0648\u0646\u064a"  # electronic
MAAL = "\u0645\u0627\u0644"                          # "maal"    money

ok = True


def check(label, cond, extra=""):
    global ok
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  {extra}" if extra else ""))
    if not cond:
        ok = False


def esc(s):
    return s.encode("unicode_escape").decode()


print("=" * 72)
print("1. stemming: the definite article must not block a match")
print("=" * 72)
check(f"stem({esc(AT + SARQAH)}) == {esc(SARQAH)}",
      stem(AT + SARQAH) == SARQAH, f"got {esc(stem(AT + SARQAH))}")
check("bare stem is unchanged", stem(SARQAH) == SARQAH)

print()
print("=" * 72)
print("2. THE BUG: ISM returned an unrelated document for a theft question")
print("=" * 72)
query = f"{AQOUBA} {AT}{SARQAH} \u0641\u064a {AT}{QANOUN} \u0627\u0644\u0645\u063a\u0631\u0628\u064a"
wrong_doc = (f"\u0639\u0627\u0645 {AT} {AT}{TAQATIL} \u0627\u0644\u0625\u0644\u0643\u062a\u0631\u0648\u0646\u064a "
             f"{AT}{BADALAH} {AT}{MAAL} \u0627\u0644\u0642\u0627\u0646\u0648\u0646\u064a")
# same real ISM title we observed live:
ism_title = "\u0627\u0644\u062a\u0628\u0627\u062f\u0644 \u0627\u0644\u0625\u0644\u0643\u062a\u0631\u0648\u0646\u064a \u0644\u0644\u0645\u0639\u0637\u064a\u0627\u062a \u0627\u0644\u0642\u0627\u0646\u0648\u0646\u064a\u0629"
r = relevance(query, ism_title)
check("relevance(theft query, electronic-exchange title) is low",
      r < 0.25, f"score={r:.3f}  matched={matched_stems(query, ism_title)}")

print()
print("=" * 72)
print("3. a genuinely on-topic page must PASS")
print("=" * 72)
good = (f"\u062a\u0639\u062a\u0628\u0631 {AT}{SARQAH} \u0645\u0646 \u0623\u0642\u062f\u0645 \u0627\u0644\u062c\u0631\u0627\u0626\u0645 "
        f"\u0627\u0644\u0648\u0627\u0642\u0639\u0629 \u0639\u0644\u0649 \u0627\u0644\u0623\u0645\u0648\u0627\u0644 \u0645\u0646 \u0627\u0644\u0645\u0644\u0643 "
        f"{AT}{MAAL} \u0627\u0644\u0645\u0645\u0644\u0648\u0643 \u0644\u0644\u063a\u064a\u0631")
r_good = relevance(query, good)
check("on-topic theft text scores above threshold", r_good >= 0.25,
      f"score={r_good:.3f}  matched={matched_stems(query, good)}")

print()
print("=" * 72)
print("4. the wrong doc scores LOWER than the right doc")
print("=" * 72)
check("on-topic > off-topic", r_good > r,
      f"on-topic={r_good:.3f}  off-topic={r:.3f}")

print()
print("=" * 72)
print("5. edge cases must not crash and must not pass everything")
print("=" * 72)
check("empty query -> 0.0", relevance("", good) == 0.0)
check("empty content -> 0.0", relevance(query, "") == 0.0)
check("punctuation-only query -> 0.0", relevance("?!?! ...", good) == 0.0)
check("stopword-only query -> 0.0", relevance("what is the", good) == 0.0)
check("unrelated English query -> 0.0",
      relevance("how do I bake sourdough bread at home", good) == 0.0)
check("long garbage text does not pass by volume",
      relevance(query, ("word " * 500)) == 0.0)
one_stem_doc = "\u0642\u0627\u0646\u0648\u0646 \u0627\u0644\u062c\u0631\u0627\u0626\u0645"   # "law crimes"
check("one incidental match out of 4 stems is below 0.25",
      relevance(query, one_stem_doc) < 0.25,
      f"score={relevance(query, one_stem_doc):.3f}")

print()
print("=" * 72)
print("6. every query stem present -> 1.0")
print("=" * 72)
exact = " ".join(stems(query))
check("perfect self-match == 1.0", relevance(query, exact) == 1.0,
      f"score={relevance(query, exact):.3f}")

print()
print("=" * 72)
print("RELEVANCE GATE: " + ("ALL PASS" if ok else "FAILURES PRESENT"))
print("=" * 72)
sys.exit(0 if ok else 1)
