-- Business question 1a, sliced by category.
--
-- Why this exists rather than a WHERE on vw_rating_by_brand: that view groups by
-- brand alone, so it carries no category column and a category filter applied to
-- it would silently do nothing. The dashboard's category control has to scope the
-- brand chart as well as the category chart, or "filtered by Cleansers" would be
-- true of some sections of the page and quietly false of others.
--
-- Grain: one row per (brand, secondary_category). The dashboard re-aggregates to
-- brand level with a review-count-weighted mean, which is why avg_rating is
-- exposed alongside review_count rather than instead of it — averaging the
-- averages would weight a 12-review category the same as a 300,000-review one.
--
-- Full-population view: every fact row belongs to exactly one (brand, category)
-- pair, so sum(review_count) must equal count(*) FROM fact_reviews. Asserted in
-- sql/validation/dashboard_checks.sql alongside the others.
CREATE OR REPLACE VIEW dw.vw_rating_by_brand_category AS
SELECT
    b.brand_key,
    b.brand_name,
    p.secondary_category,
    count(*)                                                   AS review_count,
    count(DISTINCT p.product_key)                              AS product_count,
    round(avg(f.rating)::numeric, 4)                           AS avg_rating,
    round(avg(f.is_recommended::int)::numeric * 100, 2)        AS recommend_pct,
    round(avg(p.price_usd)::numeric, 2)                        AS avg_price_usd
FROM dw.fact_reviews f
JOIN dw.dim_product p ON p.product_key = f.product_key
JOIN dw.dim_brand   b ON b.brand_key   = p.brand_key
GROUP BY b.brand_key, b.brand_name, p.secondary_category;

COMMENT ON VIEW dw.vw_rating_by_brand_category IS
    'BQ1a sliced by secondary category, so the dashboard category filter can scope the brand chart. Re-aggregate with a review_count-weighted mean.';
