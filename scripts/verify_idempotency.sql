-- Verifies change #2 (idempotent ingestion).
-- total must equal uniq: no duplicate (law, article, content) rows exist.
SELECT count(*) AS total,
       count(DISTINCT law) AS laws,
       count(DISTINCT (law, article, md5(content))) AS uniq
FROM documents;

SELECT law, count(*) AS chunks
FROM documents
GROUP BY law
ORDER BY chunks DESC;

-- The old bug: re-running /ingest-all doubled the index. Prove the index
-- and the ON CONFLICT upsert are in place.
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'documents';
