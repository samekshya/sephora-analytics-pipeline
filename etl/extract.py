"""
extract.py
----------
Reads sephora_oltp (the staging schema) into DataFrames, and reads back the
warehouse's own key lookups.

Dimension extracts have no time axis and always pull in full (D10) — a review
arriving in an incremental batch for a newly-catalogued product must find its
product key already present, or transform.py drops it silently.

Fact extracts come in three variants, one per load mode (see LOAD_MODES).
"""

import logging
from datetime import date

import pandas as pd

logger = logging.getLogger(__name__)

# The three load modes (D17). The names are the whole point of the distinction:
#
#   full         EVERY review in staging, no date bound at all. What you run to
#                build or rebuild the warehouse for real.
#   historical   Reviews before HISTORICAL_CUTOFF only. A DEMO BASELINE, not a
#                full load - it deliberately holds the 2023 rows back so the
#                incremental run afterwards has something real to pick up.
#   incremental  Only reviews after the warehouse's own watermark.
#
# This replaces a two-mode design whose "full-reload" actually stopped at 2023.
# That name claimed something the code did not do: anyone reading it would
# reasonably believe the warehouse held everything, when a quarter of a year was
# missing by design. A mode that silently withholds data must say so in its name.
FULL = 'full'
HISTORICAL = 'historical'
INCREMENTAL = 'incremental'
LOAD_MODES = (FULL, HISTORICAL, INCREMENTAL)

# The historical/incremental boundary (D8). Reviews before this date form the
# demo baseline; everything from it onward is the held-back incremental batch.
HISTORICAL_CUTOFF = '2023-01-01'

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
  """FULL mode — every review in staging, no date bound (1,093,371 rows).

  No WHERE clause at all. Idempotency is what makes this safe to run against an
  already-populated warehouse: ON CONFLICT (source_row_id, product_id) DO
  NOTHING means re-offering rows that are already there inserts 0.
  """
  sql = REVIEW_COLUMNS_SQL + " ORDER BY submission_date;"
  return extract(conn, sql)


def extract_reviews_historical(conn):
  """HISTORICAL mode — the demo baseline, everything before the 2023 cutoff
  (1,043,868 rows), leaving 49,503 rows for incremental to pick up."""
  return extract_reviews(conn, '2000-01-01', HISTORICAL_CUTOFF)


def extract_reviews_incremental(oltp_conn, watermark):
  """INCREMENTAL mode — everything after the watermark.

  Strictly greater than, not >=, because the watermark is a date the warehouse
  has already loaded in full. Using >= would re-offer every row from that day
  on every single run; ON CONFLICT would absorb them, but the run would report
  thousands of rows extracted and zero loaded, forever.
  """
  sql = REVIEW_COLUMNS_SQL + """
    WHERE submission_date > %(watermark)s
    ORDER BY submission_date;
  """
  return extract(oltp_conn, sql, {"watermark": watermark})


def extract_reviews_for_mode(oltp_conn, mode, watermark=None):
  """Dispatch to the right extract for `mode`.

  One place where a mode string becomes a query, so pipeline.py and the DAG
  cannot drift into disagreeing about what a mode means.
  """
  if mode not in LOAD_MODES:
    raise ValueError(f"Unknown load mode {mode!r} — expected one of {LOAD_MODES}")

  if mode == FULL:
    logger.info("FULL mode — extracting every review, no date bound")
    return extract_reviews_full(oltp_conn)

  if mode == HISTORICAL:
    logger.info(f"HISTORICAL mode — extracting reviews before {HISTORICAL_CUTOFF} "
                f"(demo baseline; later rows held back for incremental)")
    return extract_reviews_historical(oltp_conn)

  logger.info(f"INCREMENTAL mode — extracting reviews after watermark {watermark}")
  return extract_reviews_incremental(oltp_conn, watermark)


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
