-- brand: one row per brand (304 expected).
--
-- Keyed on the source's own brand_id rather than a surrogate, because it is
-- already a stable integer key and brand_id -> brand_name was verified 1:1
-- across all 8,494 products (asserted in clean.py, so a violation stops the
-- pipeline rather than silently creating a second brand row).
--
-- This table is the reason brand_name does not belong on product: it depends
-- on brand_id, not on product_id — a transitive dependency, which is exactly
-- what 3NF removes.
CREATE TABLE IF NOT EXISTS "3nf".brand (
    brand_id    INTEGER PRIMARY KEY,
    brand_name  TEXT NOT NULL,
    CONSTRAINT uq_brand_name UNIQUE (brand_name)
);
