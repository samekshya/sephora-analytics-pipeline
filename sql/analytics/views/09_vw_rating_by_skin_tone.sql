-- Q4, second half: do reviewers of different SKIN TONES rate differently?
--
-- Separate from vw_rating_by_skin_type rather than crossed with it. Crossing
-- 13 tones x 4 types gives 52 cells whose smaller members carry too few
-- reviews to compare honestly, and a heatmap of mostly-noise invites exactly
-- the over-reading this project is trying to avoid. Two clean one-dimensional
-- views say more than one dirty two-dimensional one.
--
-- Like the skin_type view, this is only trustworthy because the four reviewer
-- attributes live on a junk dimension at review grain. Held on dim_customer
-- they would have been forced to one value per person, mis-tagging 13.69% of
-- reviews — and this is precisely the query that would have been wrong (D2).
--
-- 'Unknown' is kept, not filtered. It means the reviewer declined to say,
-- which is a real answer and a large share of the data; dropping it would
-- quietly overstate how much is actually known.
CREATE OR REPLACE VIEW dw.vw_rating_by_skin_tone AS
SELECT
    rp.skin_tone,
    p.primary_category,
    p.secondary_category,
    count(*)                                             AS review_count,
    count(DISTINCT p.product_key)                        AS product_count,
    count(DISTINCT f.customer_key)                       AS reviewer_count,
    round(avg(f.rating)::numeric, 4)                     AS avg_rating,
    round(avg(f.is_recommended::int)::numeric * 100, 2)  AS recommend_pct,
    round(stddev_pop(f.rating)::numeric, 4)              AS rating_stddev
FROM dw.fact_reviews f
JOIN dw.dim_reviewer_profile rp ON rp.reviewer_profile_key = f.reviewer_profile_key
JOIN dw.dim_product p           ON p.product_key = f.product_key
GROUP BY rp.skin_tone, p.primary_category, p.secondary_category;

COMMENT ON VIEW dw.vw_rating_by_skin_tone IS
    'Q4: skin tone vs rating. Trustworthy only because of the junk dimension (D2). Unknown retained deliberately.';
