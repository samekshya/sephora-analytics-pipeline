-- product: one row per product (8,494 expected).
--
-- brand_name and the three category columns are gone — they live in brand and
-- category, reached by FK. That is the 3NF change: those attributes depended on
-- brand_id / the category triple, not on product_id.
--
-- Columns dropped at this boundary (D14), all deliberately:
--   highlights        stringified list, breaks 1NF, descoped (D3)
--   ingredients       long free text, no locked business question needs it
--   value_price_usd   94.7% null
--   sale_price_usd    96.8% null
--   child_max_price   67.6% null
--   child_min_price   67.6% null
--   variation_desc    85.3% null, free text
--
-- 'reviews' is the source's own review count. It is kept for reconciliation
-- (does the catalogue's count agree with the reviews we actually loaded?) but
-- is never used as a measure — fact_reviews is the authority on that.
CREATE TABLE IF NOT EXISTS "3nf".product (
    product_id         TEXT PRIMARY KEY,
    product_name       TEXT NOT NULL,
    brand_id           INTEGER NOT NULL REFERENCES "3nf".brand (brand_id),
    category_id        INTEGER NOT NULL REFERENCES "3nf".category (category_id),
    price_usd          NUMERIC(10,2) NOT NULL CHECK (price_usd > 0),
    size               TEXT,
    variation_type     TEXT,
    variation_value    TEXT,
    loves_count        INTEGER NOT NULL CHECK (loves_count >= 0),
    rating             NUMERIC(6,4) CHECK (rating BETWEEN 1 AND 5),
    reviews            INTEGER CHECK (reviews >= 0),
    child_count        INTEGER NOT NULL CHECK (child_count >= 0),
    limited_edition    BOOLEAN NOT NULL,
    new                BOOLEAN NOT NULL,
    online_only        BOOLEAN NOT NULL,
    out_of_stock       BOOLEAN NOT NULL,
    sephora_exclusive  BOOLEAN NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_3nf_product_brand ON "3nf".product (brand_id);
CREATE INDEX IF NOT EXISTS idx_3nf_product_category ON "3nf".product (category_id);
