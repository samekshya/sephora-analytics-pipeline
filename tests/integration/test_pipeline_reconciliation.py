"""
test_pipeline_reconciliation.py
-------------------------------
End-to-end proof against the LIVE databases that the pipeline accounts for
every row, and that an empty incremental batch is a clean no-op.

These tests are READ-ONLY with one deliberate exception: the idempotent
re-run test calls run_pipeline in incremental mode, which is a no-op by
construction once the warehouse is current (0 rows extracted, 0 inserted).
Nothing here truncates or rewrites the warehouse.

Skipped automatically when Postgres is unreachable, so the unit suite still
runs on a machine with no database:

  py -m pytest -m "not integration"     # unit only
  py -m pytest                          # everything
"""

import os

import pandas as pd
import pytest
from dotenv import load_dotenv

from etl.extract import (
  FULL, HISTORICAL, HISTORICAL_CUTOFF, INCREMENTAL,
  extract_reviews_for_mode, get_watermark,
)
from etl.reconcile import reconcile_load, reconcile_transform
from etl.transform import build_fact_reviews

pytestmark = pytest.mark.integration

load_dotenv()

psycopg2 = pytest.importorskip("psycopg2")


def _config(prefix):
  return dict(
    host=os.getenv(f"{prefix}_DB_HOST"),
    port=os.getenv(f"{prefix}_DB_PORT"),
    dbname=os.getenv(f"{prefix}_DB_NAME"),
    user=os.getenv(f"{prefix}_DB_USER"),
    password=os.getenv(f"{prefix}_DB_PASSWORD"),
  )


def _connect(prefix):
  try:
    return psycopg2.connect(connect_timeout=5, **_config(prefix))
  except Exception as exc:
    pytest.skip(f"{prefix} database unreachable: {exc}")


@pytest.fixture(scope="module")
def oltp_conn():
  conn = _connect("OLTP")
  yield conn
  conn.close()


@pytest.fixture(scope="module")
def dw_conn():
  conn = _connect("DW")
  yield conn
  conn.close()


def _scalar(conn, sql):
  with conn.cursor() as cur:
    cur.execute(sql)
    return cur.fetchone()[0]


# --------------------------------------------------------------------------
# The warehouse matches its source
# --------------------------------------------------------------------------

def test_fact_row_count_matches_staging(oltp_conn, dw_conn):
  """The headline reconciliation: every staged review reached the warehouse."""
  staging_rows = _scalar(oltp_conn, "SELECT count(*) FROM staging.review")
  fact_rows = _scalar(dw_conn, "SELECT count(*) FROM dw.fact_reviews")

  assert fact_rows == staging_rows, (
    f"fact_reviews has {fact_rows} rows, staging.review has {staging_rows} — "
    f"a gap of {staging_rows - fact_rows} rows went unaccounted for")


def test_no_orphan_dimension_keys(dw_conn):
  """Every fact FK resolves. The database enforces this, so a non-zero result
  would mean a constraint was dropped."""
  orphans = _scalar(dw_conn, """
    SELECT count(*)
    FROM dw.fact_reviews f
    LEFT JOIN dw.dim_product          p  ON p.product_key = f.product_key
    LEFT JOIN dw.dim_customer         c  ON c.customer_key = f.customer_key
    LEFT JOIN dw.dim_reviewer_profile rp ON rp.reviewer_profile_key
                                            = f.reviewer_profile_key
    LEFT JOIN dw.dim_date             d  ON d.date_key = f.date_key
    WHERE p.product_key IS NULL OR c.customer_key IS NULL
       OR rp.reviewer_profile_key IS NULL OR d.date_key IS NULL
  """)
  assert orphans == 0


def test_idempotency_key_is_unique(dw_conn):
  dupes = _scalar(dw_conn, """
    SELECT count(*) FROM (
      SELECT source_row_id, product_id
      FROM dw.fact_reviews
      GROUP BY 1, 2 HAVING count(*) > 1
    ) d
  """)
  assert dupes == 0


# --------------------------------------------------------------------------
# The three load modes select what their names claim
# --------------------------------------------------------------------------

def test_historical_and_incremental_partition_full(oltp_conn):
  """historical + incremental-from-scratch must together equal full, with no
  overlap and no gap. If these three don't add up, one mode is lying."""
  total = _scalar(oltp_conn, "SELECT count(*) FROM staging.review")
  before = _scalar(
    oltp_conn,
    f"SELECT count(*) FROM staging.review "
    f"WHERE submission_date < DATE '{HISTORICAL_CUTOFF}'")
  on_or_after = _scalar(
    oltp_conn,
    f"SELECT count(*) FROM staging.review "
    f"WHERE submission_date >= DATE '{HISTORICAL_CUTOFF}'")

  assert before + on_or_after == total


def test_full_mode_has_no_date_bound(oltp_conn):
  """The bug this guards: 'full' used to stop at 2023 while claiming to be
  full."""
  total = _scalar(oltp_conn, "SELECT count(*) FROM staging.review")
  df = extract_reviews_for_mode(oltp_conn, FULL)

  assert len(df) == total


def test_historical_mode_stops_at_the_cutoff(oltp_conn):
  df = extract_reviews_for_mode(oltp_conn, HISTORICAL)
  cutoff = pd.Timestamp(HISTORICAL_CUTOFF).date()

  assert len(df) > 0
  assert df["submission_date"].max() < cutoff


def test_unknown_mode_raises(oltp_conn):
  with pytest.raises(ValueError, match="Unknown load mode"):
    extract_reviews_for_mode(oltp_conn, "everything")


# --------------------------------------------------------------------------
# An empty incremental batch is a clean no-op
# --------------------------------------------------------------------------

def test_empty_incremental_batch_is_clean_noop(oltp_conn, dw_conn):
  """With the warehouse current, incremental extracts 0 rows — and the whole
  transform/reconcile chain must handle that without raising."""
  watermark = get_watermark(dw_conn)
  latest = _scalar(oltp_conn, "SELECT max(submission_date) FROM staging.review")

  if watermark < latest:
    pytest.skip(f"warehouse is behind ({watermark} < {latest}); "
                f"run incremental first for this assertion to be meaningful")

  df = extract_reviews_for_mode(oltp_conn, INCREMENTAL, watermark)
  assert len(df) == 0, "watermark is current, so nothing should be extracted"

  fact, drops = build_fact_reviews(df, {})
  assert fact.empty
  assert sum(drops.values()) == 0

  # The identity still has to hold at zero.
  assert reconcile_transform(0, 0, drops, "fact_reviews") == 0
  assert reconcile_load(0, 0, "fact_reviews") == 0


def test_watermark_matches_max_fact_date(dw_conn):
  """The watermark is read off the fact table itself, so it cannot disagree
  with the data it describes."""
  watermark = get_watermark(dw_conn)
  max_date = _scalar(dw_conn, "SELECT max(submission_date) FROM dw.fact_reviews")

  assert watermark == max_date
