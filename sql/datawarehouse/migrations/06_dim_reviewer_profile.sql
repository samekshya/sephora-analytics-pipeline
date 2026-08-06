-- dim_reviewer_profile: a JUNK DIMENSION — one row per distinct combination of
-- the four reviewer attributes (2,003 expected, of 4,200 theoretically possible).
--
-- Four low-cardinality, correlated attributes that each describe the reviewer as
-- they described themselves on one particular review. Four separate dimensions
-- would mean four more FK columns on a 1.09M-row fact table for no analytic
-- gain; four text columns on the fact itself would mean 1.09M repeated strings.
-- Bundling them into one dimension is the standard Kimball answer, and 2,003
-- rows is nothing to join against.
--
-- No NULLs: missing answers became 'Unknown' at the staging boundary. A junk
-- dimension with NULL members cannot be filtered on in Power BI, and 'Unknown'
-- is a real and meaningful answer here — it means the reviewer chose not to say.
CREATE TABLE IF NOT EXISTS dw.dim_reviewer_profile (
    reviewer_profile_key  SERIAL PRIMARY KEY,
    skin_tone             TEXT NOT NULL,
    skin_type             TEXT NOT NULL,
    eye_color             TEXT NOT NULL,
    hair_color            TEXT NOT NULL,
    CONSTRAINT uq_dim_reviewer_profile
        UNIQUE (skin_tone, skin_type, eye_color, hair_color)
);
