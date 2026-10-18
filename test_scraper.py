"""
test_scraper.py — Test Adala scraper ALONE, without DB or LLM
Run:  ./venv/bin/python test_scraper.py
      ./venv/bin/python test_scraper.py "الشيك بدون رصيد"
"""
import sys
from app.retrieval.scraper import scrape_adala_text, _fetch_search_props

def test_raw_props(query):
    print(f"\n[TEST 1] _fetch_search_props('{query}') — does Adala respond with __NEXT_DATA__?")
    props = _fetch_search_props(query)
    print(f"  keys: {list(props.keys())}")
    print(f"  latestReleases: {len(props.get('latestReleases', []))} items")
    print(f"  searchResult.data: {len(props.get('searchResult', {}).get('data', []))} items")
    if not props:
        print("  -> EMPTY: Adala changed HTML structure or blocked. Try curl below.")
        return False
    # preview first hit
    if props.get('latestReleases'):
        print(f"  preview latestReleases[0]: {str(props['latestReleases'][0])[:300]}")
    if props.get('searchResult', {}).get('data'):
        print(f"  preview searchResult[0]: {str(props['searchResult']['data'][0])[:400]}")
    return True

def test_scrape(query):
    print(f"\n[TEST 2] scrape_adala_text('{query}', max_chunks=3) — full pipeline")
    chunks = scrape_adala_text(query, max_chunks=3)
    print(f"  returned {len(chunks)} chunks")
    for i, c in enumerate(chunks):
        print(f"  --- chunk {i+1} ---")
        print(f"  law: {c.get('law')} | article: {c.get('article')} | source: {c.get('source')}")
        print(f"  content preview: {c.get('content','')[:400]}")
        print()
    if not chunks:
        print("  -> NO CHUNKS: query had no keyword overlap or Adala has no Arabic doc for it.")
    return chunks

if __name__ == "__main__":
    queries = sys.argv[1:] if len(sys.argv) > 1 else ["السرقة", "الشيك بدون رصيد", "447-1 الخصوصية"]
    for q in queries:
        print("\n" + "="*70)
        print(f" QUERY: {q}")
        print("="*70)
        ok = test_raw_props(q)
        if ok:
            test_scrape(q)

    print("\n[TEST 3] Manual curl alternative (if python fails):")
    print('  curl -sL -A "Mozilla/5.0" "https://adala.justice.gov.ma/fr/search?term=%D8%A7%D9%84%D8%B3%D8%B1%D9%82%D8%A9" | grep -o "__NEXT_DATA__" | head -1')
    print("  -> if grep finds nothing, Adala changed structure -> scraper needs update")
