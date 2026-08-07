-- "Hype vs reality": products the crowd loves that reviewers do not.
--
-- loves_count is a WISHLIST/favourite count — an intention signal, recorded
-- before anyone owns the product. avg_rating is a satisfaction signal, recorded
-- after. The two measure different moments, which is exactly why the gap
-- between them is interesting: a product with 200,000 loves and a 3.5 rating is
-- one whose marketing outruns the product.
--
-- The comparison has to be RELATIVE, not absolute. Raw loves_count is dominated
-- by category and price — a $12 moisturizer will out-love a $300 serum whatever
-- either is worth. So both signals are converted to percentile ranks across the
-- reviewed catalogue with PERCENT_RANK(), and the hype gap is the difference
-- between them. That makes the two comparable on one scale.
--
-- Restricted to products with >= 50 reviews: below that, avg_rating is noise,
-- and a "worst offender" list built on 3 reviews is a list of accidents.
CREATE OR REPLACE VIEW dw.vw_hype_vs_reality AS
WITH product_stats AS (
    SELECT
        p.product_key,
        p.product_id,
        p.product_name,
        b.brand_name,
        p.primary_category,
        p.secondary_category,
        p.price_usd,
        p.price_band,
        p.loves_count,
        count(*)                                            AS review_count,
        round(avg(f.rating)::numeric, 4)                    AS avg_rating,
        round(avg(f.is_recommended::int)::numeric * 100, 2) AS recommend_pct
    FROM dw.fact_reviews f
    JOIN dw.dim_product p ON p.product_key = f.product_key
    JOIN dw.dim_brand   b ON b.brand_key   = p.brand_key
    GROUP BY p.product_key, p.product_id, p.product_name, b.brand_name,
             p.primary_category, p.secondary_category, p.price_usd,
             p.price_band, p.loves_count
    HAVING count(*) >= 50
)
SELECT
    product_key,
    product_id,
    product_name,
    brand_name,
    primary_category,
    secondary_category,
    price_usd,
    price_band,
    loves_count,
    review_count,
    avg_rating,
    recommend_pct,
    round(percent_rank() OVER (ORDER BY loves_count)::numeric, 4) AS loves_percentile,
    round(percent_rank() OVER (ORDER BY avg_rating)::numeric, 4)  AS rating_percentile,
    -- Positive = more loved than its rating justifies (overhyped).
    -- Negative = better than its love count suggests (a sleeper hit).
    round((percent_rank() OVER (ORDER BY loves_count)
           - percent_rank() OVER (ORDER BY avg_rating))::numeric, 4) AS hype_gap
FROM product_stats;

COMMENT ON VIEW dw.vw_hype_vs_reality IS
    'BQ2: loves_count vs avg_rating as percentile ranks. hype_gap > 0 = overhyped, < 0 = sleeper hit. Min 50 reviews.';
