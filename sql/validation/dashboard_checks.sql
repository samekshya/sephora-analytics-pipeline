-- ============================================================================
-- dashboard_checks.sql — VALIDATION, not view definitions.
--
-- Kept out of sql/analytics/views/ on purpose. That folder is DDL: running it
-- changes the database. This file is read-only assertion: running it changes
-- nothing and tells you whether what the dashboard shows is true.
--
-- The rule: every headline number a Streamlit visual displays must be
-- reproducible here. If the dashboard and this file disagree, THE DASHBOARD IS
-- WRONG — the views and the fact table are the authority, not the app.
--
--   docker exec -i leapfrog_sephora_postgres psql -U postgres -d sephora_dw \
--     -v ON_ERROR_STOP=1 -f - < sql/validation/dashboard_checks.sql
-- ============================================================================

\echo '=== 1. KPI summary (dashboard header) ==='
SELECT * FROM dw.vw_kpi_summary;

\echo ''
\echo '=== 2. RECONCILIATION: every view must agree with the fact table ==='
-- Each view aggregates the same 1.09M fact rows a different way. Summing each
-- one back up must return the same total. A mismatch means a view has a join
-- that drops or duplicates rows - the classic fan-out bug, which inflates
-- totals silently and is invisible in any single chart.
WITH totals AS (
    SELECT 'fact_reviews (authority)' AS source, count(*)::bigint AS reviews
    FROM dw.fact_reviews
    UNION ALL SELECT 'vw_kpi_summary',        total_reviews FROM dw.vw_kpi_summary
    UNION ALL SELECT 'vw_rating_by_brand',    sum(review_count) FROM dw.vw_rating_by_brand
    UNION ALL SELECT 'vw_rating_by_category', sum(review_count) FROM dw.vw_rating_by_category
    UNION ALL SELECT 'vw_rating_by_brand_category', sum(review_count) FROM dw.vw_rating_by_brand_category
    UNION ALL SELECT 'vw_rating_by_price_band', sum(review_count) FROM dw.vw_rating_by_price_band
    UNION ALL SELECT 'vw_review_trend_monthly', sum(review_count) FROM dw.vw_review_trend_monthly
    UNION ALL SELECT 'vw_review_volume_by_month', sum(review_count) FROM dw.vw_review_volume_by_month
    UNION ALL SELECT 'vw_rating_by_skin_tone', sum(review_count) FROM dw.vw_rating_by_skin_tone
    UNION ALL SELECT 'vw_rating_by_review_length', sum(review_count) FROM dw.vw_rating_by_review_length
)
SELECT
    source,
    reviews,
    reviews - (SELECT count(*) FROM dw.fact_reviews) AS diff_from_fact,
    CASE WHEN reviews = (SELECT count(*) FROM dw.fact_reviews)
         THEN 'OK' ELSE '*** MISMATCH ***' END AS status
FROM totals
ORDER BY source;

\echo ''
\echo '--- views that are deliberately SUBSETS (not expected to match) ---'
-- vw_rating_by_skin_type filters to Skincare; vw_hype_vs_reality requires
-- >= 50 reviews per product. Both are stated here so a smaller number is
-- visibly intentional rather than looking like loss.
SELECT 'vw_rating_by_skin_type (Skincare only)' AS view_name,
       sum(review_count) AS reviews,
       (SELECT count(*) FROM dw.fact_reviews) AS fact_total
FROM dw.vw_rating_by_skin_type
UNION ALL
SELECT 'vw_hype_vs_reality (products >= 50 reviews)',
       sum(review_count),
       (SELECT count(*) FROM dw.fact_reviews)
FROM dw.vw_hype_vs_reality;

\echo ''
\echo '=== 3. Warehouse vs OLTP source ==='
-- fact_reviews must equal staging.review exactly. Cross-database, so run the
-- staging half against sephora_oltp; the expected value is asserted by
-- tests/integration/test_pipeline_reconciliation.py on every pytest run.
SELECT count(*) AS fact_rows,
       max(submission_date) AS watermark,
       min(submission_date) AS earliest
FROM dw.fact_reviews;

\echo ''
\echo '=== 4. Referential integrity: orphan fact rows (must be 0) ==='
SELECT count(*) AS orphan_rows
FROM dw.fact_reviews f
LEFT JOIN dw.dim_product          p  ON p.product_key = f.product_key
LEFT JOIN dw.dim_customer         c  ON c.customer_key = f.customer_key
LEFT JOIN dw.dim_reviewer_profile rp ON rp.reviewer_profile_key = f.reviewer_profile_key
LEFT JOIN dw.dim_date             d  ON d.date_key = f.date_key
WHERE p.product_key IS NULL OR c.customer_key IS NULL
   OR rp.reviewer_profile_key IS NULL OR d.date_key IS NULL;

\echo ''
\echo '=== 5. Idempotency key uniqueness (must be 0) ==='
SELECT count(*) AS duplicate_keys
FROM (SELECT source_row_id, product_id FROM dw.fact_reviews
      GROUP BY 1, 2 HAVING count(*) > 1) d;

\echo ''
\echo '=== 6. Dimension row counts ==='
SELECT
    (SELECT count(*) FROM dw.dim_brand)            AS brands,
    (SELECT count(*) FROM dw.dim_product)          AS products,
    (SELECT count(*) FROM dw.dim_customer)         AS customers,
    (SELECT count(*) FROM dw.dim_reviewer_profile) AS reviewer_profiles,
    (SELECT count(*) FROM dw.dim_date)             AS dates;

\echo ''
\echo '=== 7. Q1: top / bottom brands (min 500 reviews) ==='
SELECT brand_name, review_count, avg_rating, recommend_pct, avg_price_usd
FROM dw.vw_rating_by_brand WHERE review_count >= 500
ORDER BY avg_rating DESC LIMIT 5;

SELECT brand_name, review_count, avg_rating, recommend_pct, avg_price_usd
FROM dw.vw_rating_by_brand WHERE review_count >= 500
ORDER BY avg_rating ASC LIMIT 5;

\echo ''
\echo '=== 8. Q1: secondary categories (the level that varies - D16) ==='
-- Every reviewed product is Skincare at the primary level, so primary_category
-- is a single bar. Stated explicitly rather than left to be inferred.
SELECT secondary_category,
       sum(review_count)                                            AS reviews,
       round(sum(avg_rating * review_count) / sum(review_count), 4) AS avg_rating
FROM dw.vw_rating_by_category
GROUP BY secondary_category ORDER BY reviews DESC;

\echo ''
\echo '=== 9. Q2: hype vs reality - most overhyped products ==='
SELECT product_name, brand_name, loves_count, review_count, avg_rating, hype_gap
FROM dw.vw_hype_vs_reality ORDER BY hype_gap DESC LIMIT 10;

\echo ''
\echo '--- and the sleeper hits (better than their love count suggests) ---'
SELECT product_name, brand_name, loves_count, review_count, avg_rating, hype_gap
FROM dw.vw_hype_vs_reality ORDER BY hype_gap ASC LIMIT 10;

\echo ''
\echo '=== 10. Q3: does price predict satisfaction? ==='
SELECT price_band, review_count, product_count, avg_rating, recommend_pct, rating_stddev
FROM dw.vw_rating_by_price_band ORDER BY band_order;

\echo ''
\echo '=== 11. Q4: skin type and skin tone vs rating ==='
SELECT skin_type,
       sum(review_count)                                            AS reviews,
       round(sum(avg_rating * review_count) / sum(review_count), 4) AS avg_rating
FROM dw.vw_rating_by_skin_type GROUP BY skin_type ORDER BY avg_rating DESC;

SELECT skin_tone,
       sum(review_count)                                            AS reviews,
       round(sum(avg_rating * review_count) / sum(review_count), 4) AS avg_rating
FROM dw.vw_rating_by_skin_tone GROUP BY skin_tone ORDER BY reviews DESC;

\echo ''
\echo '=== 12. Q5: yearly volume and rating trend ==='
SELECT year,
       sum(review_count)                                            AS reviews,
       round(sum(avg_rating * review_count) / sum(review_count), 4) AS avg_rating
FROM dw.vw_review_volume_by_month GROUP BY year ORDER BY year;

\echo ''
\echo '=== 13. Partial-month flag (the final month is incomplete) ==='
SELECT month_start, review_count, is_partial_month
FROM dw.vw_review_volume_by_month
ORDER BY month_start DESC LIMIT 3;

\echo ''
\echo '=== 14. Review length vs rating ==='
-- Read the LAST three columns, not avg_rating. The mean is flat across every
-- bucket (~0.06 of a star), so length looks unrelated to satisfaction until the
-- tails are counted separately: pct_1_star and pct_5_star both fall as reviews
-- get longer. Short reviews are polarised, long reviews are moderate, and the
-- two effects cancel in the average. rating_stddev falling monotonically is the
-- same fact stated a second way.
SELECT length_bucket, review_count, avg_review_length, avg_rating,
       recommend_pct, rating_stddev, pct_1_star, pct_5_star, pct_extreme
FROM dw.vw_rating_by_review_length
ORDER BY bucket_order;
