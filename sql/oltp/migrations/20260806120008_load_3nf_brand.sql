-- raw -> 3nf: brand (304 expected)
-- ON CONFLICT DO NOTHING so the migration is safe to re-run.
INSERT INTO "3nf".brand (brand_id, brand_name)
SELECT DISTINCT brand_id, brand_name
FROM raw.product_info
ON CONFLICT (brand_id) DO NOTHING;
