-- review: one row per review (1,093,371 expected after deduplication).
--
-- The four reviewer attributes sit here, as FKs to the lookup tables, because
-- this is the grain at which they were recorded (D2). All four are nullable —
-- between 10% and 21% of reviews leave each one blank, and a blank answer is
-- not the same as an answer.
--
-- Columns dropped at this boundary (D14):
--   product_name / brand_name / price_usd   repeated from product_info on every
--                                           review row; verified to agree on
--                                           0 of 2,351 products, so pure
--                                           redundancy — a textbook 3NF removal
--
-- review_text and review_title are kept HERE and go no further (D6). 350 MB of
-- free text has no place in a fact table, but dropping it entirely would break
-- the traceability requirement.
--
-- helpfulness is nullable and never imputed (D5): it is NULL exactly when
-- total_feedback_count = 0, verified across all 1.09M rows. Undefined, not
-- missing.
CREATE TABLE IF NOT EXISTS "3nf".review (
    review_id                 BIGSERIAL PRIMARY KEY,

    -- natural key from the source, verified unique across all five files (D13)
    source_row_id             BIGINT NOT NULL,
    source_file               TEXT   NOT NULL,

    author_id                 TEXT NOT NULL REFERENCES "3nf".author (author_id),
    product_id                TEXT NOT NULL REFERENCES "3nf".product (product_id),

    submission_date           DATE NOT NULL,

    rating                    SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    is_recommended            BOOLEAN,
    helpfulness               NUMERIC(18,16) CHECK (helpfulness BETWEEN 0 AND 1),
    total_feedback_count      INTEGER NOT NULL CHECK (total_feedback_count >= 0),
    total_pos_feedback_count  INTEGER NOT NULL CHECK (total_pos_feedback_count >= 0),
    total_neg_feedback_count  INTEGER NOT NULL CHECK (total_neg_feedback_count >= 0),

    review_text               TEXT,
    review_title              TEXT,
    review_length             INTEGER CHECK (review_length >= 0),

    skin_tone_id              INTEGER REFERENCES "3nf".skin_tone (skin_tone_id),
    skin_type_id              INTEGER REFERENCES "3nf".skin_type (skin_type_id),
    eye_color_id              INTEGER REFERENCES "3nf".eye_color (eye_color_id),
    hair_color_id             INTEGER REFERENCES "3nf".hair_color (hair_color_id),

    CONSTRAINT uq_review_source UNIQUE (source_row_id, product_id),

    -- Verified to hold on every one of the 1,094,411 source rows. Encoded as a
    -- constraint so a future load that breaks it fails here rather than
    -- producing quietly wrong feedback totals downstream.
    CONSTRAINT ck_review_feedback_split
        CHECK (total_pos_feedback_count + total_neg_feedback_count = total_feedback_count),

    -- The D5 invariant, likewise made unbreakable rather than merely observed.
    CONSTRAINT ck_review_helpfulness_defined
        CHECK ((helpfulness IS NULL) = (total_feedback_count = 0))
);

CREATE INDEX IF NOT EXISTS idx_3nf_review_product ON "3nf".review (product_id);
CREATE INDEX IF NOT EXISTS idx_3nf_review_author ON "3nf".review (author_id);

-- The incremental watermark column — every incremental extract filters on it.
CREATE INDEX IF NOT EXISTS idx_3nf_review_submission ON "3nf".review (submission_date);
