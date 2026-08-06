-- raw -> 3nf: author (503,216 expected) and the four attribute lookups.
--
-- Loaded together because they are all simple DISTINCT projections off
-- raw.reviews with no interdependency, and all four lookups must exist before
-- review can be loaded.
--
-- WHERE ... IS NOT NULL matters: a NULL would otherwise become a lookup row
-- meaning "unknown", which is exactly the kind of sentinel this schema avoids.
-- Unknown is represented by a NULL FK on review, not by a row here.

INSERT INTO "3nf".author (author_id)
SELECT DISTINCT author_id
FROM raw.reviews
ON CONFLICT (author_id) DO NOTHING;

INSERT INTO "3nf".skin_tone (skin_tone)
SELECT DISTINCT skin_tone FROM raw.reviews WHERE skin_tone IS NOT NULL
ON CONFLICT (skin_tone) DO NOTHING;

INSERT INTO "3nf".skin_type (skin_type)
SELECT DISTINCT skin_type FROM raw.reviews WHERE skin_type IS NOT NULL
ON CONFLICT (skin_type) DO NOTHING;

INSERT INTO "3nf".eye_color (eye_color)
SELECT DISTINCT eye_color FROM raw.reviews WHERE eye_color IS NOT NULL
ON CONFLICT (eye_color) DO NOTHING;

INSERT INTO "3nf".hair_color (hair_color)
SELECT DISTINCT hair_color FROM raw.reviews WHERE hair_color IS NOT NULL
ON CONFLICT (hair_color) DO NOTHING;
