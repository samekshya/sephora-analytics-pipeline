-- Business question 1a: which brands earn the highest ratings, and which underperform?
--
-- review_count is exposed so the dashboard can enforce a minimum. Without one,
-- a "top brand" list is just a list of brands with one 5-star review — the
-- classic small-sample trap, and it is the first thing anyone will check.
CREATE OR REPLACE VIEW dw.vw_rating_by_brand AS
SELECT
    b.brand_key,
    b.brand_name,
    count(*)                                                   AS review_count,
    count(DISTINCT p.product_key)                              AS product_count,
    round(avg(f.rating)::numeric, 4)                           AS avg_rating,
    round(avg(f.is_recommended::int)::numeric * 100, 2)        AS recommend_pct,
    round(avg(p.price_usd)::numeric, 2)                        AS avg_price_usd,
    count(*) FILTER (WHERE f.rating = 5)                       AS five_star,
    count(*) FILTER (WHERE f.rating = 1)                       AS one_star
FROM dw.fact_reviews f
JOIN dw.dim_product p ON p.product_key = f.product_key
JOIN dw.dim_brand   b ON b.brand_key   = p.brand_key
GROUP BY b.brand_key, b.brand_name;

COMMENT ON VIEW dw.vw_rating_by_brand IS
    'BQ1a: rating and recommendation rate per brand. Filter on review_count in the dashboard.';
