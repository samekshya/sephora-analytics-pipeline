-- The normalized layer. Third normal form: every non-key attribute depends on
-- the key, the whole key, and nothing but the key.
--
-- This is where the raw layer's redundancy is removed — brand_name repeated on
-- 8,494 product rows and again on 1.09M review rows, category repeated the same
-- way, and the reviewer attributes carried as free text on every review.
CREATE SCHEMA IF NOT EXISTS "3nf";
