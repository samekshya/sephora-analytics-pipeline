-- The staging layer: the analytics-ready shape the etl package actually reads.
--
-- 3nf is correct but awkward to extract from — every dimension attribute is one
-- or two joins away. Staging pre-joins them once, in SQL, so extract.py stays a
-- simple SELECT per table rather than carrying the join logic in Python.
--
-- This is also where review_text stops (D6): staging.review has review_length
-- but no text, which is what keeps the warehouse load reading megabytes instead
-- of hundreds of megabytes.
CREATE SCHEMA IF NOT EXISTS staging;

-- staging.product: product with brand and category flattened back in.
-- Denormalized on purpose — it feeds dim_product, which is denormalized by
-- design. Normalizing in 3nf and flattening again here is not wasted work: it
-- is what proves the two layers have different jobs.
CREATE TABLE IF NOT EXISTS staging.product (
    product_id          TEXT PRIMARY KEY,
    product_name        TEXT NOT NULL,
    brand_id            INTEGER NOT NULL,
    brand_name          TEXT NOT NULL,
    primary_category    TEXT NOT NULL,
    secondary_category  TEXT,
    tertiary_category   TEXT,
    price_usd           NUMERIC(10,2) NOT NULL,
    size                TEXT,
    loves_count         INTEGER NOT NULL,
    limited_edition     BOOLEAN NOT NULL,
    new                 BOOLEAN NOT NULL,
    online_only         BOOLEAN NOT NULL,
    out_of_stock        BOOLEAN NOT NULL,
    sephora_exclusive   BOOLEAN NOT NULL
);

-- staging.review: review with the four attributes resolved back to their text
-- values, NULLs collapsed to 'Unknown'.
--
-- The 'Unknown' mapping happens HERE, not in 3nf. In the normalized layer a
-- missing answer is correctly a NULL FK; in the warehouse it has to be a real
-- dimension member, because a junk dimension with NULL columns cannot be joined
-- to or filtered on in Power BI. Two layers, two correct answers.
CREATE TABLE IF NOT EXISTS staging.review (
    review_id                 BIGINT PRIMARY KEY,
    source_row_id             BIGINT NOT NULL,
    author_id                 TEXT NOT NULL,
    product_id                TEXT NOT NULL,
    submission_date           DATE NOT NULL,
    rating                    SMALLINT NOT NULL,
    is_recommended            BOOLEAN,
    helpfulness               NUMERIC(18,16),
    total_feedback_count      INTEGER NOT NULL,
    total_pos_feedback_count  INTEGER NOT NULL,
    total_neg_feedback_count  INTEGER NOT NULL,
    review_length             INTEGER,
    skin_tone                 TEXT NOT NULL,
    skin_type                 TEXT NOT NULL,
    eye_color                 TEXT NOT NULL,
    hair_color                TEXT NOT NULL
);

-- The incremental extract filters on submission_date; the warehouse load joins
-- on product_id and author_id.
CREATE INDEX IF NOT EXISTS idx_stg_review_submission ON staging.review (submission_date);
CREATE INDEX IF NOT EXISTS idx_stg_review_product ON staging.review (product_id);
CREATE INDEX IF NOT EXISTS idx_stg_review_author ON staging.review (author_id);
