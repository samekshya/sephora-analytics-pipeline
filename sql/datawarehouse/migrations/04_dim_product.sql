-- dim_product: one row per product (8,494 expected).
--
-- The three category levels are flattened onto the dimension rather than
-- snowflaked out to a dim_category. In the OLTP layer they are a separate table
-- keyed on the triple (3NF); here they are three plain columns, because the
-- dashboard filters and groups on them constantly and a star schema pays for
-- that with redundancy, not joins.
--
-- brand IS snowflaked (FK to dim_brand) rather than flattened, because brand is
-- a genuine analytic entity in its own right — "rating by brand" is business
-- question 1 — and 304 brands against 8,494 products makes the join cheap.
--
-- price_band is a derived attribute computed in etl/transform.py, not stored in
-- the source. Banding happens once, in the ETL, so every visual that groups by
-- price uses identical boundaries; computing it per-visual in Power BI is how
-- two charts end up disagreeing.
CREATE TABLE IF NOT EXISTS dw.dim_product (
    product_key         SERIAL PRIMARY KEY,
    product_id          TEXT NOT NULL,          -- business key (traceability)
    product_name        TEXT NOT NULL,
    brand_key           INTEGER NOT NULL REFERENCES dw.dim_brand (brand_key),

    primary_category    TEXT NOT NULL,
    secondary_category  TEXT,
    tertiary_category   TEXT,

    price_usd           NUMERIC(10,2) NOT NULL,
    price_band          TEXT NOT NULL,
    size                TEXT,
    loves_count         INTEGER NOT NULL,

    limited_edition     BOOLEAN NOT NULL,
    new                 BOOLEAN NOT NULL,
    online_only         BOOLEAN NOT NULL,
    out_of_stock        BOOLEAN NOT NULL,
    sephora_exclusive   BOOLEAN NOT NULL,

    CONSTRAINT uq_dim_product_id UNIQUE (product_id)
);

CREATE INDEX IF NOT EXISTS idx_dim_product_brand ON dw.dim_product (brand_key);
CREATE INDEX IF NOT EXISTS idx_dim_product_primary_cat ON dw.dim_product (primary_category);
