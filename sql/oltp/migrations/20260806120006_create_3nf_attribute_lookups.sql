-- The four reviewer-attribute lookup tables.
--
-- Small closed vocabularies (13 / 4 / 5 / 7 values after cleaning), referenced
-- by review rather than repeated as free text on 1.09M rows. Normalising them
-- is what makes the casing defect impossible to reintroduce: with 'Grey' and
-- 'gray' collapsed in clean.py and a UNIQUE constraint here, a second spelling
-- cannot appear without a new lookup row and an FK failure.
--
-- skin_tone is 13 rather than 14 values because 'notSureST' was a placeholder,
-- mapped to NULL during cleaning.

CREATE TABLE IF NOT EXISTS "3nf".skin_tone (
    skin_tone_id  SERIAL PRIMARY KEY,
    skin_tone     TEXT NOT NULL,
    CONSTRAINT uq_skin_tone UNIQUE (skin_tone)
);

CREATE TABLE IF NOT EXISTS "3nf".skin_type (
    skin_type_id  SERIAL PRIMARY KEY,
    skin_type     TEXT NOT NULL,
    CONSTRAINT uq_skin_type UNIQUE (skin_type)
);

CREATE TABLE IF NOT EXISTS "3nf".eye_color (
    eye_color_id  SERIAL PRIMARY KEY,
    eye_color     TEXT NOT NULL,
    CONSTRAINT uq_eye_color UNIQUE (eye_color)
);

CREATE TABLE IF NOT EXISTS "3nf".hair_color (
    hair_color_id  SERIAL PRIMARY KEY,
    hair_color     TEXT NOT NULL,
    CONSTRAINT uq_hair_color UNIQUE (hair_color)
);
