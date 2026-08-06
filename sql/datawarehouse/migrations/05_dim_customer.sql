-- dim_customer: one row per reviewer (503,216 expected).
--
-- IDENTITY ONLY — no skin_tone, skin_type, eye_color or hair_color. This is the
-- correction to the earlier hand-written schema, and the single most important
-- decision in this warehouse (D2).
--
-- Measured on the source: 22,503 authors (4.47%) recorded more than one
-- distinct value for at least one of those four attributes, across 149,788
-- reviews (13.69% of the dataset). Holding them here, behind a UNIQUE customer
-- key, would force one profile per person and mis-tag roughly one review in
-- seven — silently, with no constraint violation and nothing downstream to
-- notice. It would corrupt business question 4 specifically, which is the
-- question those attributes exist to answer.
--
-- They live in dw.dim_reviewer_profile instead, joined from the fact table at
-- the grain they were actually recorded: per review.
CREATE TABLE IF NOT EXISTS dw.dim_customer (
    customer_key  SERIAL PRIMARY KEY,
    customer_id   TEXT NOT NULL,
    CONSTRAINT uq_dim_customer_id UNIQUE (customer_id)
);
