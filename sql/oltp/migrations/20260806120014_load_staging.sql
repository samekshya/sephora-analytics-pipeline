-- 3nf -> staging.
--
-- Both loads are truncate-and-reload: staging is a derived view of 3nf, not a
-- system of record, so rebuilding it should reproduce it exactly rather than
-- merge into it. Incremental logic lives downstream, between staging and the
-- warehouse.

TRUNCATE staging.product;

INSERT INTO staging.product (
    product_id, product_name, brand_id, brand_name,
    primary_category, secondary_category, tertiary_category,
    price_usd, size, loves_count,
    limited_edition, new, online_only, out_of_stock, sephora_exclusive
)
SELECT
    p.product_id,
    p.product_name,
    b.brand_id,
    b.brand_name,
    c.primary_category,
    c.secondary_category,
    c.tertiary_category,
    p.price_usd,
    p.size,
    p.loves_count,
    p.limited_edition,
    p.new,
    p.online_only,
    p.out_of_stock,
    p.sephora_exclusive
FROM "3nf".product p
JOIN "3nf".brand b    ON b.brand_id = p.brand_id
JOIN "3nf".category c ON c.category_id = p.category_id;

TRUNCATE staging.review;

INSERT INTO staging.review (
    review_id, source_row_id, author_id, product_id, submission_date,
    rating, is_recommended, helpfulness,
    total_feedback_count, total_pos_feedback_count, total_neg_feedback_count,
    review_length, skin_tone, skin_type, eye_color, hair_color
)
SELECT
    r.review_id,
    r.source_row_id,
    r.author_id,
    r.product_id,
    r.submission_date,
    r.rating,
    r.is_recommended,
    r.helpfulness,
    r.total_feedback_count,
    r.total_pos_feedback_count,
    r.total_neg_feedback_count,
    r.review_length,
    -- NULL -> 'Unknown' so the junk dimension has no NULL members (see the
    -- schema comment on staging.review for why this belongs here, not in 3nf)
    COALESCE(st.skin_tone,   'Unknown'),
    COALESCE(sty.skin_type,  'Unknown'),
    COALESCE(ec.eye_color,   'Unknown'),
    COALESCE(hc.hair_color,  'Unknown')
FROM "3nf".review r
LEFT JOIN "3nf".skin_tone  st  ON st.skin_tone_id  = r.skin_tone_id
LEFT JOIN "3nf".skin_type  sty ON sty.skin_type_id = r.skin_type_id
LEFT JOIN "3nf".eye_color  ec  ON ec.eye_color_id  = r.eye_color_id
LEFT JOIN "3nf".hair_color hc  ON hc.hair_color_id = r.hair_color_id;
