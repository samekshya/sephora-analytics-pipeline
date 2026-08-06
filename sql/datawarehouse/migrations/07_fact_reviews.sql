-- ============================================================================
-- fact_reviews — the single fact table.
-- Grain: ONE ROW PER REVIEW. 1,093,371 expected once fully loaded
--        (1,043,868 from the full load + 49,503 from the incremental batch).
-- ============================================================================
--
-- No brand_key here (D11). Brand is functionally determined by product, so a
-- copy on the fact would add no information while creating a way for the two to
-- disagree after a bad load. Brand analysis joins through dim_product.
--
-- No review_text (D6). 350 MB of free text has no place at this grain;
-- review_length carries the one analytically useful property in 4 bytes.
--
-- submission_date is kept alongside date_key even though the two are redundant.
-- The watermark needs MAX() of a real date, and deriving that by unpacking an
-- integer key on every incremental run is the kind of cleverness that breaks
-- quietly.
CREATE TABLE IF NOT EXISTS dw.fact_reviews (
    review_key                SERIAL PRIMARY KEY,

    -- Business key from the source. Verified unique across all five review
    -- files (D13) — the CSV row index restarts per file, but each product
    -- appears in exactly one file, so the pair cannot collide.
    source_row_id             BIGINT NOT NULL,
    product_id                TEXT   NOT NULL,

    -- dimension FKs
    product_key               INTEGER NOT NULL REFERENCES dw.dim_product (product_key),
    customer_key              INTEGER NOT NULL REFERENCES dw.dim_customer (customer_key),
    reviewer_profile_key      INTEGER NOT NULL REFERENCES dw.dim_reviewer_profile (reviewer_profile_key),
    date_key                  INTEGER NOT NULL REFERENCES dw.dim_date (date_key),

    -- measures
    rating                    SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    is_recommended            BOOLEAN,            -- nullable: 167,988 reviews don't say
    helpfulness               NUMERIC(18,16),     -- nullable and never imputed (D5)
    total_feedback_count      INTEGER NOT NULL CHECK (total_feedback_count >= 0),
    total_pos_feedback_count  INTEGER NOT NULL CHECK (total_pos_feedback_count >= 0),
    total_neg_feedback_count  INTEGER NOT NULL CHECK (total_neg_feedback_count >= 0),
    review_length             INTEGER CHECK (review_length >= 0),

    -- degenerate: the review's own date, kept for the incremental watermark
    submission_date           DATE NOT NULL,

    -- Drives ON CONFLICT ... DO NOTHING, which is what makes the load idempotent
    CONSTRAINT uq_fact_reviews_source UNIQUE (source_row_id, product_id),

    -- Same invariant enforced in 3nf.review — restated here so a fault in the
    -- transform cannot land wrong totals in the warehouse
    CONSTRAINT ck_fact_feedback_split
        CHECK (total_pos_feedback_count + total_neg_feedback_count = total_feedback_count)
);

-- One index per dimension FK. At 1.09M rows every dashboard visual is a join
-- through one of these, and the star schema's whole performance argument
-- depends on them existing.
CREATE INDEX IF NOT EXISTS idx_fact_reviews_product ON dw.fact_reviews (product_key);
CREATE INDEX IF NOT EXISTS idx_fact_reviews_customer ON dw.fact_reviews (customer_key);
CREATE INDEX IF NOT EXISTS idx_fact_reviews_profile ON dw.fact_reviews (reviewer_profile_key);
CREATE INDEX IF NOT EXISTS idx_fact_reviews_date ON dw.fact_reviews (date_key);

-- The watermark query is MAX(submission_date) on every incremental run.
CREATE INDEX IF NOT EXISTS idx_fact_reviews_submission ON dw.fact_reviews (submission_date);
