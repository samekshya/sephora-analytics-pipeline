"""
load.py
-------
Writes transformed DataFrames into sephora_dw.

Every insert targets a business key with ON CONFLICT ... DO NOTHING, so
re-running against already-loaded data is a no-op rather than a duplicate.
That, not a flag or a checked timestamp, is what makes the pipeline idempotent:
the constraint enforces it, so it holds whether or not the caller remembered.

execute_values rather than executemany - at 1.09M fact rows the difference is
minutes versus tens of minutes, because it sends one multi-row INSERT per page
instead of one round trip per row.
"""

import logging

import pandas as pd
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)

# Rows per INSERT statement. Large enough that round trips stop dominating,
# small enough that a failed page doesn't mean re-sending everything.
PAGE_SIZE = 5000


def _records(df: pd.DataFrame, columns: list) -> list:
  """DataFrame -> list[tuple] in `columns` order, turning NaN/NaT/pd.NA into
  None so psycopg2 writes SQL NULL instead of the literal string 'nan'."""
  sub = df[columns]
  return list(sub.astype(object).where(pd.notnull(sub), None).itertuples(
    index=False, name=None))


def _execute(conn, sql, df: pd.DataFrame, columns: list, table_name: str):
  """Load df into table_name (schema-qualified), returning rows actually inserted.

  The count comes from COUNT(*) before and after, not from cursor.rowcount:
  execute_values sends one statement per page, so rowcount reports only the
  LAST page. On the first 1.09M-row load with PAGE_SIZE 5000 that reported
  3,868 inserted instead of 1,043,868 - the data was correct but the number was
  nonsense, which is worse than no number at all in a reconciliation.

  Reporting `already present` separately is what makes an idempotent re-run
  legible: offered stays the same, inserted drops to 0.
  """
  if df.empty:
    logger.info(f"No rows to load - skipping {table_name}")
    return 0
  try:
    with conn.cursor() as curr:
      curr.execute(f"SELECT count(*) FROM {table_name}")
      before = curr.fetchone()[0]

      execute_values(curr, sql, _records(df, columns), page_size=PAGE_SIZE)

      curr.execute(f"SELECT count(*) FROM {table_name}")
      after = curr.fetchone()[0]
    conn.commit()

    inserted = after - before
    skipped = len(df) - inserted
    logger.info(f"{inserted} inserted to {table_name} "
                f"({len(df)} offered, {skipped} already present)")
    return inserted
  except Exception as e:
    conn.rollback()
    logger.error(str(e))
    raise


DIM_BRAND_COLUMNS = ['brand_id', 'brand_name']


def load_dim_brand(conn, brand_df):
  sql = """
    INSERT INTO dw.dim_brand (brand_id, brand_name)
    VALUES %s
    ON CONFLICT (brand_id) DO NOTHING;
  """
  return _execute(conn, sql, brand_df, DIM_BRAND_COLUMNS, 'dw.dim_brand')


DIM_CUSTOMER_COLUMNS = ['customer_id']


def load_dim_customer(conn, customer_df):
  sql = """
    INSERT INTO dw.dim_customer (customer_id)
    VALUES %s
    ON CONFLICT (customer_id) DO NOTHING;
  """
  return _execute(conn, sql, customer_df, DIM_CUSTOMER_COLUMNS, 'dw.dim_customer')


DIM_REVIEWER_PROFILE_COLUMNS = ['skin_tone', 'skin_type', 'eye_color', 'hair_color']


def load_dim_reviewer_profile(conn, profile_df):
  sql = """
    INSERT INTO dw.dim_reviewer_profile (skin_tone, skin_type, eye_color, hair_color)
    VALUES %s
    ON CONFLICT (skin_tone, skin_type, eye_color, hair_color) DO NOTHING;
  """
  return _execute(conn, sql, profile_df, DIM_REVIEWER_PROFILE_COLUMNS,
                  'dw.dim_reviewer_profile')


DIM_PRODUCT_LOAD_COLUMNS = [
  'product_id', 'product_name', 'brand_key',
  'primary_category', 'secondary_category', 'tertiary_category',
  'price_usd', 'price_band', 'size', 'loves_count',
  'limited_edition', 'new', 'online_only', 'out_of_stock', 'sephora_exclusive',
]


def load_dim_product(conn, product_df):
  sql = """
    INSERT INTO dw.dim_product (
      product_id, product_name, brand_key,
      primary_category, secondary_category, tertiary_category,
      price_usd, price_band, size, loves_count,
      limited_edition, new, online_only, out_of_stock, sephora_exclusive
    )
    VALUES %s
    ON CONFLICT (product_id) DO NOTHING;
  """
  return _execute(conn, sql, product_df, DIM_PRODUCT_LOAD_COLUMNS, 'dw.dim_product')


FACT_LOAD_COLUMNS = [
  'source_row_id', 'product_id', 'product_key', 'customer_key',
  'reviewer_profile_key', 'date_key', 'rating', 'is_recommended', 'helpfulness',
  'total_feedback_count', 'total_pos_feedback_count', 'total_neg_feedback_count',
  'review_length', 'submission_date',
]


def load_fact_reviews(conn, reviews_df):
  sql = """
    INSERT INTO dw.fact_reviews (
      source_row_id, product_id, product_key, customer_key,
      reviewer_profile_key, date_key, rating, is_recommended, helpfulness,
      total_feedback_count, total_pos_feedback_count, total_neg_feedback_count,
      review_length, submission_date
    )
    VALUES %s
    ON CONFLICT (source_row_id, product_id) DO NOTHING;
  """
  return _execute(conn, sql, reviews_df, FACT_LOAD_COLUMNS, 'dw.fact_reviews')


def load_dim_date(conn, start_date, end_date):
  """Generate and load the calendar for [start_date, end_date] (D12).

  Generated in SQL rather than pandas because generate_series already does
  exactly this, and Postgres knows its own week/ISO-day rules better than a
  hand-rolled version would. ON CONFLICT makes it safe to re-run and lets the
  dimension extend as newer data arrives.
  """
  sql = """
    INSERT INTO dw.dim_date (
      date_key, full_date, year, quarter, month, month_name,
      week, day, day_of_week, day_name, is_weekend
    )
    SELECT
      TO_CHAR(d, 'YYYYMMDD')::INTEGER,
      d::date,
      EXTRACT(YEAR FROM d)::int,
      EXTRACT(QUARTER FROM d)::int,
      EXTRACT(MONTH FROM d)::int,
      TRIM(TO_CHAR(d, 'Month')),
      EXTRACT(WEEK FROM d)::int,
      EXTRACT(DAY FROM d)::int,
      EXTRACT(ISODOW FROM d)::int,
      TRIM(TO_CHAR(d, 'Day')),
      EXTRACT(ISODOW FROM d) IN (6, 7)
    FROM generate_series(%(start_date)s::date, %(end_date)s::date, '1 day') AS d
    ON CONFLICT (date_key) DO NOTHING;
  """
  try:
    with conn.cursor() as curr:
      curr.execute(sql, {"start_date": start_date, "end_date": end_date})
      inserted = curr.rowcount
    conn.commit()
    logger.info(f"{inserted} inserted to dim_date ({start_date} to {end_date})")
    return inserted
  except Exception as e:
    conn.rollback()
    logger.error(str(e))
    raise
