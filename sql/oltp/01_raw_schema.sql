-- =====================================================================
-- sephora_oltp database — RAW schema
-- Mirrors data/processed/*.csv 1:1 (every column, nothing dropped)
-- Purpose: traceability / audit trail — every warehouse row must trace
-- back to a raw record here.
--
-- Cleaning already happened in clean.py (dedup, type coercion, whitespace,
-- value normalisation). Column trims happen LATER, at the raw -> 3nf
-- boundary, so this layer stays complete — see D14.
--
-- Run against sephora_oltp.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS raw;

-- ---------------------------------------------------------------------
-- raw.product_info — one row per product (8,494 expected)
-- Column order matches data/processed/products.csv exactly, so COPY can
-- load it without a column list.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.product_info (
    product_id          TEXT PRIMARY KEY,
    product_name        TEXT,
    brand_id            INTEGER,
    brand_name          TEXT,
    loves_count         INTEGER,
    rating              NUMERIC(6,4),      -- source carries 4 dp, e.g. 3.6364
    reviews             INTEGER,           -- source's own review count; NOT the loaded count
    size                TEXT,              -- free text: "3.4 oz/ 100 mL"
    variation_type      TEXT,
    variation_value     TEXT,
    variation_desc      TEXT,
    ingredients         TEXT,              -- long free text; dropped at the 3nf boundary
    price_usd           NUMERIC(10,2),
    value_price_usd     NUMERIC(10,2),     -- 94.7% null; dropped at the 3nf boundary
    sale_price_usd      NUMERIC(10,2),     -- 96.8% null; dropped at the 3nf boundary
    limited_edition     BOOLEAN,
    new                 BOOLEAN,
    online_only         BOOLEAN,
    out_of_stock        BOOLEAN,
    sephora_exclusive   BOOLEAN,
    highlights          TEXT,              -- stringified list; descoped, see D3
    primary_category    TEXT,
    secondary_category  TEXT,
    tertiary_category   TEXT,
    child_count         INTEGER,
    child_max_price     NUMERIC(10,2),     -- 67.6% null; dropped at the 3nf boundary
    child_min_price     NUMERIC(10,2)      -- 67.6% null; dropped at the 3nf boundary
);

-- ---------------------------------------------------------------------
-- raw.reviews — one row per review (1,093,371 expected after dedup)
--
-- No FK to raw.product_info: the raw layer is a landing zone, and adding a
-- constraint here would make a bulk COPY fail on the first bad row instead
-- of letting the reconciliation query report exactly how many are bad.
-- Referential integrity is enforced at the 3nf layer, where it belongs.
--
-- (source_row_id, product_id) is the natural key — verified unique across
-- all five source files, see D13.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.reviews (
    source_row_id             BIGINT NOT NULL,   -- CSV row index; restarts per file
    author_id                 TEXT   NOT NULL,
    rating                    SMALLINT,
    is_recommended            BOOLEAN,
    helpfulness               NUMERIC(18,16),    -- source carries full float precision
    total_feedback_count      INTEGER,
    total_neg_feedback_count  INTEGER,
    total_pos_feedback_count  INTEGER,
    submission_time           DATE,              -- date-only in the source, verified (D12)
    review_text               TEXT,              -- 350 MB total; stops here, see D6
    review_title              TEXT,
    skin_tone                 TEXT,
    eye_color                 TEXT,
    skin_type                 TEXT,
    hair_color                TEXT,
    product_id                TEXT   NOT NULL,
    product_name              TEXT,              -- redundant with product_info; dropped at 3nf
    brand_name                TEXT,              -- redundant with product_info; dropped at 3nf
    price_usd                 NUMERIC(10,2),     -- redundant with product_info; dropped at 3nf
    source_file               TEXT   NOT NULL,   -- which CSV this row came from (traceability)
    review_length             INTEGER,           -- derived in clean.py from review_text
    CONSTRAINT pk_raw_reviews PRIMARY KEY (source_row_id, product_id)
);

-- Supports the raw -> 3nf loads and the reconciliation queries.
CREATE INDEX IF NOT EXISTS idx_raw_reviews_product ON raw.reviews (product_id);
CREATE INDEX IF NOT EXISTS idx_raw_reviews_author ON raw.reviews (author_id);
CREATE INDEX IF NOT EXISTS idx_raw_reviews_submission ON raw.reviews (submission_time);
