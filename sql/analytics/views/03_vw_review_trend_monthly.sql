-- Business question 2: how do review volume and average rating trend over time?
--
-- Monthly rather than daily: at 1.09M reviews across 5,379 days, daily is noise.
-- dim_date supplies year/month rather than date_trunc on the fact table, which
-- is the whole reason a date dimension exists.
CREATE OR REPLACE VIEW dw.vw_review_trend_monthly AS
SELECT
    d.year,
    d.month,
    d.month_name,
    make_date(d.year, d.month, 1)                        AS month_start,
    count(*)                                             AS review_count,
    round(avg(f.rating)::numeric, 4)                     AS avg_rating,
    round(avg(f.is_recommended::int)::numeric * 100, 2)  AS recommend_pct,
    count(DISTINCT f.customer_key)                       AS reviewer_count,
    count(DISTINCT f.product_key)                        AS product_count,
    round(avg(f.review_length)::numeric, 1)              AS avg_review_length
FROM dw.fact_reviews f
JOIN dw.dim_date d ON d.date_key = f.date_key
GROUP BY d.year, d.month, d.month_name;

COMMENT ON VIEW dw.vw_review_trend_monthly IS
    'Q2: monthly review volume and average rating. Note 2023 is partial (to 21 March).';
