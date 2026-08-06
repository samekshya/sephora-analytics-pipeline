-- raw -> 3nf: category (174 expected)
-- The triple is the natural key; category_id is assigned by the sequence.
INSERT INTO "3nf".category (primary_category, secondary_category, tertiary_category)
SELECT DISTINCT primary_category, secondary_category, tertiary_category
FROM raw.product_info
ON CONFLICT (primary_category, secondary_category, tertiary_category) DO NOTHING;
