-- Business question 4: do reviewers with different skin types rate the same
-- skincare products differently?
--
-- This is the view the junk dimension exists for, and the one that would have
-- been quietly wrong under the earlier design: holding skin_type on the
-- customer would have mis-tagged 13.69% of reviews (D2).
--
-- Restricted to Skincare, because skin type is not a meaningful lens on
-- fragrance or brushes. 'Unknown' is retained rather than filtered out — it is
-- 10% of reviews and hiding it would overstate how much is actually known.
CREATE OR REPLACE VIEW dw.vw_rating_by_skin_type AS
SELECT
    rp.skin_type,
    p.primary_category,
    p.secondary_category,
    count(*)                                             AS review_count,
    count(DISTINCT p.product_key)                        AS product_count,
    round(avg(f.rating)::numeric, 4)                     AS avg_rating,
    round(avg(f.is_recommended::int)::numeric * 100, 2)  AS recommend_pct
FROM dw.fact_reviews f
JOIN dw.dim_reviewer_profile rp ON rp.reviewer_profile_key = f.reviewer_profile_key
JOIN dw.dim_product p           ON p.product_key = f.product_key
WHERE p.primary_category = 'Skincare'
GROUP BY rp.skin_type, p.primary_category, p.secondary_category;

COMMENT ON VIEW dw.vw_rating_by_skin_type IS
    'BQ4: skin type vs rating on skincare. Trustworthy only because of the junk dimension (D2).';
