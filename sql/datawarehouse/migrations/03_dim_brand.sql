-- dim_brand: one row per brand (304 expected).
--
-- brand_id is the business key carried from the source, so ON CONFLICT has a
-- target and re-running the load is a no-op rather than a duplicate.
CREATE TABLE IF NOT EXISTS dw.dim_brand (
    brand_key   SERIAL PRIMARY KEY,
    brand_id    INTEGER NOT NULL,
    brand_name  TEXT NOT NULL,
    CONSTRAINT uq_dim_brand_id UNIQUE (brand_id)
);
