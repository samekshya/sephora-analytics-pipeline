-- raw -> 3nf: review (1,093,371 expected)
--
-- The four attribute joins are LEFT JOINs, not inner: an inner join would drop
-- every review that left an attribute blank — between 111K and 227K rows each,
-- and the majority of the table once combined. A blank answer is still a review.
--
-- The three redundant columns (product_name, brand_name, price_usd) are not
-- selected — this is where that redundancy is removed (D14).
INSERT INTO "3nf".review (
    source_row_id, source_file, author_id, product_id, submission_date,
    rating, is_recommended, helpfulness,
    total_feedback_count, total_pos_feedback_count, total_neg_feedback_count,
    review_text, review_title, review_length,
    skin_tone_id, skin_type_id, eye_color_id, hair_color_id
)
SELECT
    r.source_row_id,
    r.source_file,
    r.author_id,
    r.product_id,
    r.submission_time,
    r.rating,
    r.is_recommended,
    r.helpfulness,
    r.total_feedback_count,
    r.total_pos_feedback_count,
    r.total_neg_feedback_count,
    r.review_text,
    r.review_title,
    r.review_length,
    st.skin_tone_id,
    sty.skin_type_id,
    ec.eye_color_id,
    hc.hair_color_id
FROM raw.reviews r
LEFT JOIN "3nf".skin_tone  st  ON st.skin_tone   = r.skin_tone
LEFT JOIN "3nf".skin_type  sty ON sty.skin_type  = r.skin_type
LEFT JOIN "3nf".eye_color  ec  ON ec.eye_color   = r.eye_color
LEFT JOIN "3nf".hair_color hc  ON hc.hair_color  = r.hair_color
ON CONFLICT (source_row_id, product_id) DO NOTHING;
