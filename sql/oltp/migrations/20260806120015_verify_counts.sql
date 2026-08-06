-- Reconciliation: raw -> 3nf -> staging.
--
-- Run after every full rebuild of the OLTP database. Every row that leaves a
-- layer must be accounted for; "expected" is what the exploration and cleaning
-- runs measured, so a mismatch means something changed, not that the number was
-- a guess.

\echo '=== row counts by layer ==='

SELECT 'raw.product_info'   AS table_name, count(*) AS rows, 8494    AS expected FROM raw.product_info
UNION ALL SELECT 'raw.reviews',            count(*), 1093371 FROM raw.reviews
UNION ALL SELECT '3nf.brand',              count(*), 304     FROM "3nf".brand
UNION ALL SELECT '3nf.category',           count(*), 174     FROM "3nf".category
UNION ALL SELECT '3nf.product',            count(*), 8494    FROM "3nf".product
UNION ALL SELECT '3nf.author',             count(*), 503216  FROM "3nf".author
UNION ALL SELECT '3nf.skin_tone',          count(*), 13      FROM "3nf".skin_tone
UNION ALL SELECT '3nf.skin_type',          count(*), 4       FROM "3nf".skin_type
UNION ALL SELECT '3nf.eye_color',          count(*), 5       FROM "3nf".eye_color
UNION ALL SELECT '3nf.hair_color',         count(*), 7       FROM "3nf".hair_color
UNION ALL SELECT '3nf.review',             count(*), 1093371 FROM "3nf".review
UNION ALL SELECT 'staging.product',        count(*), 8494    FROM staging.product
UNION ALL SELECT 'staging.review',         count(*), 1093371 FROM staging.review
ORDER BY table_name;

\echo ''
\echo '=== reconciliation: every raw row must reach 3nf and staging ==='

SELECT
    (SELECT count(*) FROM raw.product_info) AS raw_products,
    (SELECT count(*) FROM "3nf".product)    AS nf_products,
    (SELECT count(*) FROM staging.product)  AS stg_products,
    (SELECT count(*) FROM raw.product_info) - (SELECT count(*) FROM staging.product) AS product_gap;

SELECT
    (SELECT count(*) FROM raw.reviews)     AS raw_reviews,
    (SELECT count(*) FROM "3nf".review)    AS nf_reviews,
    (SELECT count(*) FROM staging.review)  AS stg_reviews,
    (SELECT count(*) FROM raw.reviews) - (SELECT count(*) FROM staging.review) AS review_gap;

\echo ''
\echo '=== integrity checks (all must be 0) ==='

SELECT 'orphan reviews (product missing)' AS check_name, count(*) AS bad
FROM "3nf".review r LEFT JOIN "3nf".product p USING (product_id)
WHERE p.product_id IS NULL
UNION ALL
SELECT 'orphan reviews (author missing)', count(*)
FROM "3nf".review r LEFT JOIN "3nf".author a USING (author_id)
WHERE a.author_id IS NULL
UNION ALL
SELECT 'products with no brand', count(*)
FROM "3nf".product p LEFT JOIN "3nf".brand b USING (brand_id)
WHERE b.brand_id IS NULL
UNION ALL
SELECT 'products with no category', count(*)
FROM "3nf".product p LEFT JOIN "3nf".category c USING (category_id)
WHERE c.category_id IS NULL
UNION ALL
SELECT 'staging reviews with NULL attribute', count(*)
FROM staging.review
WHERE skin_tone IS NULL OR skin_type IS NULL OR eye_color IS NULL OR hair_color IS NULL
UNION ALL
SELECT 'duplicate (source_row_id, product_id)', count(*)
FROM (SELECT source_row_id, product_id FROM "3nf".review
      GROUP BY 1, 2 HAVING count(*) > 1) d;

\echo ''
\echo '=== full / incremental split, as the warehouse load will see it ==='

SELECT
    count(*) FILTER (WHERE submission_date <  DATE '2023-01-01') AS full_load_rows,
    count(*) FILTER (WHERE submission_date >= DATE '2023-01-01') AS incremental_rows,
    count(*)                                                     AS total_rows,
    min(submission_date) AS earliest,
    max(submission_date) AS latest
FROM staging.review;
