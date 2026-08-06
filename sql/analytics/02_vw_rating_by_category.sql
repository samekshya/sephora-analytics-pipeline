-- Business question 1b: which categories earn the highest ratings?
--
-- Grouped on all three levels rather than rolled up, because the levels are not
-- a real hierarchy (D1) — one secondary category sits under up to 7 primaries,
-- so a rollup would double-count.
--
-- The dashboard must group on secondary_category, NOT primary. Every reviewed
-- product in this dataset is Skincare (D16): the review scrape covers skincare
-- only, so primary_category is constant across all 1,093,371 reviews and a
-- chart of it is a single bar. secondary_category is the level that actually
-- varies - Moisturizers, Treatments, Cleansers, Eye Care, Masks, Sunscreen.
CREATE OR REPLACE VIEW dw.vw_rating_by_category AS
SELECT
    p.primary_category,
    p.secondary_category,
    p.tertiary_category,
    count(*)                                             AS review_count,
    count(DISTINCT p.product_key)                        AS product_count,
    round(avg(f.rating)::numeric, 4)                     AS avg_rating,
    round(avg(f.is_recommended::int)::numeric * 100, 2)  AS recommend_pct,
    round(avg(p.price_usd)::numeric, 2)                  AS avg_price_usd
FROM dw.fact_reviews f
JOIN dw.dim_product p ON p.product_key = f.product_key
GROUP BY p.primary_category, p.secondary_category, p.tertiary_category;

COMMENT ON VIEW dw.vw_rating_by_category IS
    'BQ1b: rating per category triple. Not rolled up - the levels are not a true hierarchy (D1).';
