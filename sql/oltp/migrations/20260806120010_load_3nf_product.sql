-- raw -> 3nf: product (8,494 expected)
--
-- The join back to category resolves the surrogate key. It has to be
-- NULL-tolerant: 8 products have no secondary_category and 990 none tertiary,
-- and a plain `=` would drop every one of them silently. IS NOT DISTINCT FROM
-- treats NULL as a matchable value.
--
-- This is the point where the descoped columns disappear (D14): highlights,
-- ingredients, value_price_usd, sale_price_usd, child_max_price,
-- child_min_price and variation_desc are simply not selected.
INSERT INTO "3nf".product (
    product_id, product_name, brand_id, category_id, price_usd,
    size, variation_type, variation_value, loves_count, rating, reviews,
    child_count, limited_edition, new, online_only, out_of_stock, sephora_exclusive
)
SELECT
    p.product_id,
    p.product_name,
    p.brand_id,
    c.category_id,
    p.price_usd,
    p.size,
    p.variation_type,
    p.variation_value,
    p.loves_count,
    p.rating,
    p.reviews,
    p.child_count,
    p.limited_edition,
    p.new,
    p.online_only,
    p.out_of_stock,
    p.sephora_exclusive
FROM raw.product_info p
JOIN "3nf".category c
  ON  c.primary_category   IS NOT DISTINCT FROM p.primary_category
  AND c.secondary_category IS NOT DISTINCT FROM p.secondary_category
  AND c.tertiary_category  IS NOT DISTINCT FROM p.tertiary_category
ON CONFLICT (product_id) DO NOTHING;
