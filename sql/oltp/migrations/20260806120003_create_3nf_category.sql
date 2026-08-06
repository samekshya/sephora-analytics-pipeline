-- category: one row per distinct (primary, secondary, tertiary) combination
-- (174 expected).
--
-- Keyed on the full triple, NOT modelled as three nested levels — see D1.
-- One secondary_category appears under as many as 7 different primaries
-- ('Value & Gift Sets'), so a parent-child hierarchy would assert a
-- relationship the data does not have, and any rollup built on it would
-- produce wrong totals.
--
-- secondary_category and tertiary_category are nullable (8 and 990 products
-- respectively have none), so the UNIQUE constraint alone would not prevent
-- duplicate rows — NULL is not equal to NULL. NULLS NOT DISTINCT closes that.
CREATE TABLE IF NOT EXISTS "3nf".category (
    category_id         SERIAL PRIMARY KEY,
    primary_category    TEXT NOT NULL,
    secondary_category  TEXT,
    tertiary_category   TEXT,
    CONSTRAINT uq_category_triple
        UNIQUE NULLS NOT DISTINCT (primary_category, secondary_category, tertiary_category)
);
