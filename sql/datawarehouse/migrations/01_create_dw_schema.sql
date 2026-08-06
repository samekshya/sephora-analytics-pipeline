-- =====================================================================
-- sephora_dw — star schema
-- Grain of the fact table: one row per review.
--
-- Deliberately NOT normalized. dim_product repeats brand_name and all three
-- category levels on every row; that redundancy is the point — it buys single
-- joins for the dashboard. The normalized version of the same data lives in
-- sephora_oltp."3nf". Two layers, two different jobs.
--
-- Run against sephora_dw.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS dw;
