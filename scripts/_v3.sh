#!/bin/bash
EXT=/usr/share/postgresql/14/extension/vector--0.8.6.sql

echo "############ A) the <=> operator definition — what does it RETURNS? ############"
awk 'NR>=184 && NR<=200 {printf "%4d: %s\n", NR, $0}' $EXT

echo
echo "############ B) the <-> operator definition ############"
awk 'NR>=170 && NR<=184 {printf "%4d: %s\n", NR, $0}' $EXT

echo
echo "############ C) plain grep for the HNSW/IVFFlat GUC names anywhere in the SQL ############"
for k in iterative_scan ef_construction ef_search ivfflat.probes hnsw m probes lists; do
  n=$(grep -ciF "$k" $EXT)
  printf "  %-16s hits=%s\n" "$k" "$n"
done

echo
echo "############ D) what files did the pgvector package actually install? ############"
dpkg -L postgresql-14-pgvector 2>&1 | sed 's/^/  /'

echo
echo "############ E) is C source or header available to confirm defaults? ############"
ls /usr/include/postgresql/14/server/ 2>/dev/null | grep -i vector | sed 's/^/  /' || echo "  (no vector headers in server include)"
find / -name "guc.c" -path "*vector*" 2>/dev/null | sed 's/^/  /' || true
apt-get source postgresql-14-pgvector --print-uris 2>&1 | head -3 | sed 's/^/  /'
