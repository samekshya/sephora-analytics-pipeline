-- Does how MUCH someone writes tell you anything about their rating?
--
-- review_length is the one measure on fact_reviews carried across the OLTP
-- boundary purely as a summary: the full review text stops at the OLTP (D6),
-- and the character count comes with it so questions like this stay answerable
-- without moving 350 MB of prose into the warehouse. This view is what that
-- decision was for.
--
-- The obvious hypothesis is that unhappy customers write longer reviews. On
-- this data that is FALSE, and the view is built to show it rather than to
-- confirm it. avg_rating is nearly flat across every length bucket (a spread of
-- about 0.06 of a star, smaller than the price effect), so a chart of length
-- against average rating alone would honestly read as "no relationship".
--
-- The relationship that IS there is in the SHAPE of the distribution, not its
-- mean, which is why pct_1_star / pct_5_star / pct_extreme are computed here
-- rather than left to the dashboard. Short reviews are polarised - they are
-- disproportionately 1s AND disproportionately 5s. Long reviews are moderate.
-- Both extremes shrink together as length rises, which is exactly why the mean
-- barely moves: the two effects cancel in the average and are only visible
-- once the tails are counted separately.
--
-- Bucket boundaries are set from the measured distribution, not round numbers
-- chosen by eye: p25 = 172, median = 263, p75 = 402, p95 = 752 characters.
--
-- Reviews with no recorded length are kept as their own bucket rather than
-- dropped. That is 1,444 rows - immaterial to any average, but keeping them
-- means this view still sums to the full fact table and can sit in the
-- reconciliation block of dashboard_checks.sql alongside the others. A view
-- that silently drops rows is a view that cannot be reconciled.
CREATE OR REPLACE VIEW dw.vw_rating_by_review_length AS
SELECT
    CASE
        WHEN f.review_length IS NULL      THEN 'Unknown'
        WHEN f.review_length < 100        THEN 'Very short (<100)'
        WHEN f.review_length < 250        THEN 'Short (100-249)'
        WHEN f.review_length < 500        THEN 'Medium (250-499)'
        WHEN f.review_length < 1000       THEN 'Long (500-999)'
        ELSE                                   'Very long (1000+)'
    END                                                      AS length_bucket,
    -- Explicit sort key: the bucket labels do not sort into reading order
    -- alphabetically, and leaving the dashboard to re-derive the order would be
    -- a second definition of the same thing.
    CASE
        WHEN f.review_length IS NULL      THEN 0
        WHEN f.review_length < 100        THEN 1
        WHEN f.review_length < 250        THEN 2
        WHEN f.review_length < 500        THEN 3
        WHEN f.review_length < 1000       THEN 4
        ELSE                                   5
    END                                                      AS bucket_order,
    count(*)                                                 AS review_count,
    round(avg(f.review_length)::numeric, 1)                  AS avg_review_length,
    round(avg(f.rating)::numeric, 4)                         AS avg_rating,
    round(avg(f.is_recommended::int)::numeric * 100, 2)      AS recommend_pct,
    round(stddev_pop(f.rating)::numeric, 4)                  AS rating_stddev,
    -- The actual finding lives in these three columns.
    round(100.0 * count(*) FILTER (WHERE f.rating = 1) / count(*), 2)
                                                             AS pct_1_star,
    round(100.0 * count(*) FILTER (WHERE f.rating = 5) / count(*), 2)
                                                             AS pct_5_star,
    round(100.0 * count(*) FILTER (WHERE f.rating IN (1, 5)) / count(*), 2)
                                                             AS pct_extreme
FROM dw.fact_reviews f
GROUP BY 1, 2;

COMMENT ON VIEW dw.vw_rating_by_review_length IS
    'Rating by review length bucket. Mean rating is flat (~0.06 spread); the real signal is pct_extreme - short reviews are polarised, long ones moderate. Unknown-length rows retained so the view reconciles to fact_reviews.';
