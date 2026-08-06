-- author: one row per reviewer (503,216 expected).
--
-- Identity ONLY. No skin_tone, skin_type, eye_color or hair_color here — see D2.
--
-- Those four attributes are NOT functionally dependent on author_id: 22,503
-- authors (4.47%) recorded more than one distinct value across their reviews,
-- covering 149,788 reviews (13.69%). Storing them here would force one value
-- per person and silently discard the rest. They belong on review, because that
-- is the grain at which they were actually recorded.
CREATE TABLE IF NOT EXISTS "3nf".author (
    author_id  TEXT PRIMARY KEY
);
