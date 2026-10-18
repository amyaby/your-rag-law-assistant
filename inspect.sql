-- Quick inspection queries for the `assistant` database.
-- In VS Code: click "No connection attached" in the status bar
-- and choose your SQLTools PostgreSQL connection.

-- 1. Which am I connected to?
SELECT current_database();

-- 2. Which tables do I own? (3 expected: documents, conversations, messages)
SELECT tablename
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY 1;

-- 3. How many vectors do I have?
SELECT count(*) AS chunks FROM documents;

-- 4. What dimension are the stored vectors? (must be 384)
SELECT DISTINCT vector_dims(embedding) AS dims FROM documents;

-- 5. Rows per law
SELECT law, count(*) AS chunks
FROM documents
GROUP BY law
ORDER BY chunks DESC;

-- 6. Is the Labour code present yet? (0 rows until /ingest-all runs)
SELECT count(*) AS labour_chunks
FROM documents
WHERE law ILIKE '% travail%' OR law ILIKE '%social%';

-- 7. Prove idempotency: these two numbers must be EQUAL
SELECT count(*) AS total,
       count(DISTINCT (law, article, md5(content))) AS unique_chunks
FROM documents;

-- 8. Article 505 (theft) — the canonical retrieval test
SELECT id, law, article, vector_dims(embedding) AS dims,
       left(content, 70) AS snippet
FROM documents
WHERE article = '505'
ORDER BY law;

-- 9. The idempotency key itself
SELECT law, article, md5(content) AS content_hash
FROM documents
WHERE article = '505'
LIMIT 1;

-- 10. Chat memory (empty until you use /ask)
SELECT count(*) AS conversations FROM conversations;
SELECT count(*) AS messages FROM messages;
