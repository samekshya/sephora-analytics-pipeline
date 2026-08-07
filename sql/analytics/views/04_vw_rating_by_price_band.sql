-- Business question 3: does price predict satisfaction?
--
-- Bands come from dim_product.price_band, computed once in etl/transform.py, so
-- every visual that groups by price uses identical boundaries. band_order exists
-- because '$100+' sorts before '$15-30' alphabetically, which would put the
-- chart in a meaningless order.
CREATE OR REPLACE VIEW dw.vw_rating_by_price_band AS
SELECT
    p.price_band,
    CASE p.price_band
        WHEN 'Under $15' THEN 1
        WHEN '$15-30'    THEN 2
        WHEN '$30-50'    THEN 3
        WHEN '$50-100'   THEN 4
        WHEN '$100+'     THEN 5
    END                                                  AS band_order,
    count(*)                                             AS review_count,
    count(DISTINCT p.product_key)                        AS product_count,
    round(avg(f.rating)::numeric, 4)                     AS avg_rating,
    round(avg(f.is_recommended::int)::numeric * 100, 2)  AS recommend_pct,
    round(avg(p.price_usd)::numeric, 2)                  AS avg_price_usd,
    round(stddev_pop(f.rating)::numeric, 4)              AS rating_stddev
FROM dw.fact_reviews f
JOIN dw.dim_product p ON p.product_key = f.product_key
GROUP BY p.price_band;

COMMENT ON VIEW dw.vw_rating_by_price_band IS
    'BQ3: does price predict satisfaction. Bands computed in transform.py so all visuals agree.';
