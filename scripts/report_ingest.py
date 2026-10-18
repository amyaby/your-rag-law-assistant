import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ingest.json"
d = json.load(open(path))
print(f"ingested_files={d.get('ingested_files')} skipped={d.get('skipped_files')} "
      f"chunks={d.get('total_chunks')}")
for r in d.get("details", []):
    if r["status"] == "ok":
        st = r.get("stats", {})
        print(f"  OK    {r['file']:<45} {r.get('chunks'):>5} chunks  "
              f"pages={st.get('pages')} chars={st.get('chars')}")
    else:
        print(f"  {r['status'].upper():<5} {r['file']:<45} -> {r.get('reason') or r.get('message')}")
