-- The KPI row on dashboard page 1. One row, computed in SQL rather than as
-- Power BI measures, so the headline numbers cannot disagree with the detail
-- visuals beneath them.
--
-- products_reviewed vs products_in_catalogue is stated deliberately: only 2,351
-- of 8,494 catalogue products have any reviews at all. A dashboard that shows
-- "8,494 products" next to rating averages implies a coverage it does not have.
CREATE OR REPLACE VIEW dw.vw_kpi_summary AS
SELECT
    count(*)                                                    AS total_reviews,
    count(DISTINCT f.customer_key)                              AS total_reviewers,
    count(DISTINCT f.product_key)                               AS products_reviewed,
    (SELECT count(*) FROM dw.dim_product)                       AS products_in_catalogue,
    (SELECT count(*) FROM dw.dim_brand)                         AS total_brands,
    round(avg(f.rating)::numeric, 4)                            AS avg_rating,
    round(avg(f.is_recommended::int)::numeric * 100, 2)         AS recommend_pct,
    -- Helpfulness is undefined where nobody voted (D5), so it is averaged only
    -- over reviews that actually received feedback rather than imputed to 0.
    round(avg(f.helpfulness) FILTER
          (WHERE f.total_feedback_count > 0)::numeric, 4)       AS avg_helpfulness,
    count(*) FILTER (WHERE f.total_feedback_count > 0)          AS reviews_with_feedback,
    min(f.submission_date)                                      AS earliest_review,
    max(f.submission_date)                                      AS latest_review
FROM dw.fact_reviews f;

COMMENT ON VIEW dw.vw_kpi_summary IS
    'Dashboard KPI row. Helpfulness averaged only over reviews that received feedback (D5).';
