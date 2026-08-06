-- Cross-checks for the dashboard. Every headline number a visual shows should
-- be reproducible here; if Power BI and this file disagree, the dashboard is
-- wrong, not this.

\echo '=== KPI summary (dashboard page 1 header) ==='
SELECT * FROM dw.vw_kpi_summary;

\echo ''
\echo '=== BQ1a: top 10 brands by rating (min 500 reviews) ==='
SELECT brand_name, review_count, product_count, avg_rating, recommend_pct, avg_price_usd
FROM dw.vw_rating_by_brand
WHERE review_count >= 500
ORDER BY avg_rating DESC
LIMIT 10;

\echo ''
\echo '=== BQ1a: bottom 10 brands by rating (min 500 reviews) ==='
SELECT brand_name, review_count, product_count, avg_rating, recommend_pct, avg_price_usd
FROM dw.vw_rating_by_brand
WHERE review_count >= 500
ORDER BY avg_rating ASC
LIMIT 10;

\echo ''
\echo '=== coverage: which primary categories actually have reviews? ==='
-- Every reviewed product is Skincare (D16). Stated explicitly rather than left
-- for a viewer to infer from a single-bar chart.
SELECT primary_category,
       sum(review_count)  AS reviews,
       sum(product_count) AS products_reviewed
FROM dw.vw_rating_by_category
GROUP BY primary_category
ORDER BY reviews DESC;

\echo ''
\echo '=== BQ1b: secondary categories by volume (the level that varies) ==='
SELECT secondary_category,
       sum(review_count)                                                AS reviews,
       sum(product_count)                                               AS products,
       round(sum(avg_rating * review_count) / sum(review_count), 4)     AS avg_rating,
       round(sum(recommend_pct * review_count) / sum(review_count), 2)  AS recommend_pct
FROM dw.vw_rating_by_category
GROUP BY secondary_category
ORDER BY reviews DESC;

\echo ''
\echo '=== BQ2: review volume and rating by year ==='
SELECT year,
       sum(review_count)                                            AS reviews,
       round(sum(avg_rating * review_count) / sum(review_count), 4) AS avg_rating
FROM dw.vw_review_trend_monthly
GROUP BY year
ORDER BY year;

\echo ''
\echo '=== BQ3: does price predict satisfaction? ==='
SELECT price_band, review_count, product_count, avg_rating, recommend_pct, rating_stddev
FROM dw.vw_rating_by_price_band
ORDER BY band_order;

\echo ''
\echo '=== BQ4: skin type vs rating on skincare ==='
SELECT skin_type,
       sum(review_count)                                            AS reviews,
       round(sum(avg_rating * review_count) / sum(review_count), 4) AS avg_rating,
       round(sum(recommend_pct * review_count) / sum(review_count), 2) AS recommend_pct
FROM dw.vw_rating_by_skin_type
GROUP BY skin_type
ORDER BY avg_rating DESC;

\echo ''
\echo '=== reconciliation: warehouse vs source ==='
SELECT
    (SELECT count(*) FROM dw.fact_reviews)                              AS fact_rows,
    (SELECT count(*) FROM dw.dim_customer)                              AS customers,
    (SELECT count(*) FROM dw.dim_product)                               AS products,
    (SELECT count(*) FROM dw.dim_brand)                                 AS brands,
    (SELECT count(*) FROM dw.dim_reviewer_profile)                      AS profiles,
    (SELECT count(*) FROM dw.dim_date)                                  AS dates;
