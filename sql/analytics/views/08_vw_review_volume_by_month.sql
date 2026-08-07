-- Review volume over time with a RUNNING AVERAGE RATING — the window-function
-- view.
--
-- Why a window function rather than a plain GROUP BY:
--
-- A monthly average rating is jumpy. Early months have a few hundred reviews,
-- so one unhappy cohort swings the line, and the chart ends up showing sampling
-- noise that looks like a trend. Three window functions fix that without
-- hiding the raw data:
--
--   rolling_3m_avg_rating   AVG over the 3 months ending at this one. Smooths
--                           month-to-month noise while still reacting quickly.
--   cumulative_avg_rating   AVG over every month up to this one — the
--                           warehouse's lifetime average as it stood back then.
--                           The gap between this and the monthly line is what
--                           tells you whether a month was better or worse than
--                           the product's own history.
--   prev_month_reviews /    Month-over-month growth, computed in SQL with LAG
--   mom_growth_pct          rather than in the dashboard, so every chart that
--                           shows growth shows the same number.
--
-- All of them are computed over the monthly aggregate, not over 1.09M raw fact
-- rows — the window runs across ~175 monthly buckets, which is why this view is
-- cheap despite the ORDER BY inside each OVER clause.
--
-- NOTE for the dashboard: the final month is PARTIAL (data ends 2023-03-21),
-- so its volume is not comparable to a full month. is_partial_month flags it
-- rather than leaving a viewer to notice the cliff and mistake it for a crash.
CREATE OR REPLACE VIEW dw.vw_review_volume_by_month AS
WITH monthly AS (
    SELECT
        d.year,
        d.month,
        make_date(d.year, d.month, 1)                       AS month_start,
        count(*)                                            AS review_count,
        count(DISTINCT f.customer_key)                      AS reviewer_count,
        count(DISTINCT f.product_key)                       AS product_count,
        avg(f.rating)                                       AS avg_rating,
        avg(f.is_recommended::int) * 100                    AS recommend_pct,
        max(f.submission_date)                              AS last_review_date
    FROM dw.fact_reviews f
    JOIN dw.dim_date d ON d.date_key = f.date_key
    GROUP BY d.year, d.month
),
bounds AS (
    SELECT max(submission_date) AS max_date FROM dw.fact_reviews
)
SELECT
    m.year,
    m.month,
    m.month_start,
    m.review_count,
    m.reviewer_count,
    m.product_count,
    round(m.avg_rating::numeric, 4)      AS avg_rating,
    round(m.recommend_pct::numeric, 2)   AS recommend_pct,

    -- 3-month rolling average: this month plus the two before it.
    round(avg(m.avg_rating) OVER (
        ORDER BY m.month_start
        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    )::numeric, 4) AS rolling_3m_avg_rating,

    -- Lifetime average as of this month.
    round(avg(m.avg_rating) OVER (
        ORDER BY m.month_start
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    )::numeric, 4) AS cumulative_avg_rating,

    -- Running total of reviews ever written.
    sum(m.review_count) OVER (
        ORDER BY m.month_start
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cumulative_reviews,

    lag(m.review_count) OVER (ORDER BY m.month_start) AS prev_month_reviews,

    -- NULLIF guards the first month, where the lag is NULL, and any month
    -- following a zero-volume gap.
    round(
        (m.review_count - lag(m.review_count) OVER (ORDER BY m.month_start))
        * 100.0
        / NULLIF(lag(m.review_count) OVER (ORDER BY m.month_start), 0)
    , 2) AS mom_growth_pct,

    -- The data ends mid-March 2023; that month is not a full month.
    (date_trunc('month', b.max_date)::date = m.month_start) AS is_partial_month
FROM monthly m
CROSS JOIN bounds b;

COMMENT ON VIEW dw.vw_review_volume_by_month IS
    'BQ5: monthly volume with rolling 3-month and cumulative average rating (window functions). is_partial_month flags the incomplete final month.';
