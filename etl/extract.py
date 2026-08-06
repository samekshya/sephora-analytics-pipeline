"""
extract.py
----------
Reads sephora_oltp (the staging schema) into DataFrames, and reads back the
warehouse's own key lookups.

Dimension extracts have no time axis and always pull in full (D10) — a review
arriving in an incremental batch for a newly-catalogued product must find its
product key already present, or transform.py drops it silently.

Fact extracts come in a _full variant (bounded by the demo cutoff) and an
_incremental variant (everything after the watermark).
"""

import logging
from datetime import date

import pandas as pd

logger = logging.getLogger(__name__)

# The full/incremental boundary (D8). Reviews before this date are the initial
# load; everything from it onward is held back as the incremental batch.
INCREMENTAL_CUTOFF = '2023-01-01'

# Falls back to this on an empty fact table so the first incremental run behaves
# as a full load without special-casing. Comfortably before the earliest review
# (2008-08-28).
WATERMARK_FLOOR = date(2000, 1, 1)


def extract(conn, sql, params=None):
  try:
    df = pd.read_sql_query(sql, conn, params=params)
    logger.info(f"Extracted {len(df)} rows from table")
    return df
  except Exception as e:
    logger.error(str(e))
    raise


# --------------------------------------------------------------------------
# Dimension extracts — always full, no time axis (D10)
# --------------------------------------------------------------------------

def extract_brands(conn):
  sql = """
    SELECT DISTINCT brand_id, brand_name
    FROM staging.product;
  """
  return extract(conn, sql)


def extract_products(conn):
  sql = """
    SELECT
      product_id,
      product_name,
      brand_id,
      primary_category,
      secondary_category,
      tertiary_category,
      price_usd,
      size,
      loves_count,
      limited_edition,
      new,
      online_only,
      out_of_stock,
      sephora_exclusive
    FROM staging.product;
  """
  return extract(conn, sql)


def extract_customers(conn):
  """Every author, regardless of when they reviewed — 503,216 rows."""
  sql = """
    SELECT DISTINCT author_id
    FROM staging.review;
  """
  return extract(conn, sql)


def extract_reviewer_profiles(conn):
  """Distinct four-attribute combinations — 2,003 rows for the junk dimension.

  DISTINCT in SQL rather than drop_duplicates in pandas: the database can do it
  against an index without shipping 1.09M rows over the wire first.
  """
  sql = """
    SELECT DISTINCT skin_tone, skin_type, eye_color, hair_color
    FROM staging.review;
  """
  return extract(conn, sql)


def extract_date_bounds(conn):
  """Min/max review date, for generating dim_date (D12).

  Padded by 30 days either side so the dimension never ends exactly on the last
  fact row.
  """
  sql = """
    SELECT
      MIN(submission_date) - 30 AS start_date,
      MAX(submission_date) + 30 AS end_date
    FROM staging.review;
  """
  df = extract(conn, sql)
  start, end = df['start_date'].iloc[0], df['end_date'].iloc[0]
  logger.info(f"dim_date range: {start} to {end}")
  return start, end


# --------------------------------------------------------------------------
# Fact extracts — full and incremental
# --------------------------------------------------------------------------

REVIEW_COLUMNS_SQL = """
  SELECT
    source_row_id,
    product_id,
    author_id,
    submission_date,
    rating,
    is_recommended,
    helpfulness,
    total_feedback_count,
    total_pos_feedback_count,
    total_neg_feedback_count,
    review_length,
    skin_tone,
    skin_type,
    eye_color,
    hair_color
  FROM staging.review
"""


def extract_reviews(conn, start_date, end_date):
  sql = REVIEW_COLUMNS_SQL + """
    WHERE submission_date >= %(start_date)s AND submission_date < %(end_date)s
    ORDER BY submission_date;
  """
  return extract(conn, sql, {"start_date": start_date, "end_date": end_date})


def extract_reviews_full(conn):
  """The initial load — everything before the incremental cutoff (1,043,868 rows)."""
  return extract_reviews(conn, '2000-01-01', INCREMENTAL_CUTOFF)


def extract_reviews_incremental(oltp_conn, watermark):
  """Everything after the watermark — the held-back 2023 batch on first run."""
  sql = REVIEW_COLUMNS_SQL + """
    WHERE submission_date > %(watermark)s
    ORDER BY submission_date;
  """
  return extract(oltp_conn, sql, {"watermark": watermark})


def get_watermark(conn):
  """The most recent submission_date already in the warehouse.

  Read from the fact table itself rather than a separate control table: the
  fact table is the thing whose state actually matters, so it cannot disagree
  with its own watermark. Falls back to WATERMARK_FLOOR on an empty table so
  the first incremental run behaves as a full load.
  """
  sql = """
    SELECT COALESCE(MAX(submission_date), %(floor)s::date) AS watermark
    FROM dw.fact_reviews;
  """
  df = pd.read_sql_query(sql, conn, params={"floor": WATERMARK_FLOOR})
  watermark = df['watermark'].iloc[0]
  logger.info(f"Watermark : {watermark}")
  return watermark


# --------------------------------------------------------------------------
# Warehouse key lookups — read back after the dimensions are loaded (D9)
# --------------------------------------------------------------------------

def extract_lookup_dim(conn):
  logger.info("Loading lookup tables in memory")
  lookup = {
    "brand": pd.read_sql_query(
      "SELECT brand_id, brand_key FROM dw.dim_brand", conn),
    "product": pd.read_sql_query(
      "SELECT product_id, product_key FROM dw.dim_product", conn),
    "customer": pd.read_sql_query(
      "SELECT customer_id, customer_key FROM dw.dim_customer", conn),
    "reviewer_profile": pd.read_sql_query(
      "SELECT skin_tone, skin_type, eye_color, hair_color, reviewer_profile_key "
      "FROM dw.dim_reviewer_profile", conn),
    "date": pd.read_sql_query(
      "SELECT date_key, full_date FROM dw.dim_date", conn),
  }
  for name, df in lookup.items():
    logger.info(f"  {name}: {len(df)} rows")
  return lookup


def extract_brand_lookup(conn):
  """Brand keys only — needed by build_dim_product before products can load."""
  return pd.read_sql_query("SELECT brand_id, brand_key FROM dw.dim_brand", conn)
