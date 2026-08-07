"""
pipeline.py
-----------
Local orchestration of the ETL package: sephora_oltp (staging) -> sephora_dw.

  py pipeline.py --mode full          # every review, no date bound
  py pipeline.py --mode historical    # demo baseline: reviews before 2023-01-01
  py pipeline.py --mode incremental   # only reviews after the watermark

The Airflow DAG runs the same etl/ functions in the same order; this script
exists so the pipeline can be run and debugged without a scheduler in the way.

run_pipeline() is deliberately separate from parse_args() so the three modes
have exactly one implementation, callable from a CLI, a test, or a DAG task.

Stage order is forced by foreign keys, not preference:
  1. dim_brand           (dim_product references it)
  2. dim_product, dim_customer, dim_reviewer_profile, dim_date
  3. fact_reviews        (references all four)
"""

import argparse
import logging
import os
import time
from datetime import datetime

import psycopg2
from dotenv import load_dotenv

from etl.extract import (
  extract_brands, extract_products, extract_customers,
  extract_reviewer_profiles, extract_date_bounds,
  extract_reviews_for_mode, extract_lookup_dim, extract_brand_lookup,
  get_watermark, LOAD_MODES, FULL, HISTORICAL, INCREMENTAL,
)
from etl.transform import (
  build_dim_brand, build_dim_product, build_dim_customer,
  build_dim_reviewer_profile, build_fact_reviews,
)
from etl.load import (
  load_dim_brand, load_dim_product, load_dim_customer,
  load_dim_reviewer_profile, load_dim_date, load_fact_reviews,
)
from etl.quality import run_quality_checks
from etl.reconcile import (
  reconcile_transform, reconcile_load, ReconciliationError,
)


def parse_args():
  parser = argparse.ArgumentParser(description="Sephora DW ETL pipeline")
  parser.add_argument(
    "--mode",
    choices=list(LOAD_MODES),
    default=INCREMENTAL,
    help="full: every review, no date bound. "
         "historical: reviews before 2023-01-01 (demo baseline). "
         "incremental: only reviews after the watermark (default).",
  )
  return parser.parse_args()


LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_filename = os.path.join(LOG_DIR, f"pipeline_{timestamp}.log")

logging.basicConfig(
  level=logging.INFO,
  format="%(asctime)s  %(levelname)s [%(filename)s:%(lineno)d] %(message)s",
  handlers=[
    logging.FileHandler(log_filename, encoding="utf-8"),
    logging.StreamHandler()
  ]
)
logger = logging.getLogger(__name__)

load_dotenv()

OLTP_DB_CONFIG = dict(
  host=os.getenv("OLTP_DB_HOST"),
  port=os.getenv("OLTP_DB_PORT"),
  dbname=os.getenv("OLTP_DB_NAME"),
  user=os.getenv("OLTP_DB_USER"),
  password=os.getenv("OLTP_DB_PASSWORD"),
)
DW_DB_CONFIG = dict(
  host=os.getenv("DW_DB_HOST"),
  port=os.getenv("DW_DB_PORT"),
  dbname=os.getenv("DW_DB_NAME"),
  user=os.getenv("DW_DB_USER"),
  password=os.getenv("DW_DB_PASSWORD"),
)


def run_pipeline(mode=INCREMENTAL, oltp_conn=None, dw_conn=None):
  """Run one pipeline pass in `mode`. Returns a dict of run statistics.

  Connections can be injected (tests, Airflow); otherwise they are opened from
  the environment and closed on the way out.

  Raises ReconciliationError if any stage loses rows it cannot account for, and
  DataQualityError if the gate finds a hard failure. Neither is caught here —
  a pipeline that swallows its own alarms is worse than one with none.
  """
  if mode not in LOAD_MODES:
    raise ValueError(f"Unknown load mode {mode!r} — expected one of {LOAD_MODES}")

  logger.info("=" * 70)
  logger.info(f"Running pipeline in {mode.upper()} mode")
  logger.info("=" * 70)

  owns_connections = oltp_conn is None and dw_conn is None
  if owns_connections:
    oltp_conn = psycopg2.connect(**OLTP_DB_CONFIG)
    dw_conn = psycopg2.connect(**DW_DB_CONFIG)

  stats = {"mode": mode}

  try:
    # --- Stage 1: brand (dim_product depends on it) ---
    t0 = time.time()
    brand_df = extract_brands(oltp_conn)
    brand_dim = build_dim_brand(brand_df)
    stats["brand_inserted"] = load_dim_brand(dw_conn, brand_dim)
    logger.info(f"Brand load completed in {time.time() - t0:.2f}s")

    # --- Stage 2: remaining dimensions ---
    t0 = time.time()
    brand_lookup = extract_brand_lookup(dw_conn)
    product_df = extract_products(oltp_conn)
    product_dim, product_drops = build_dim_product(product_df, brand_lookup)
    reconcile_transform(len(product_df), len(product_dim), product_drops,
                        'dim_product')
    run_quality_checks(
      product_dim, 'dim_product',
      key_columns=['brand_key'],
      non_negative_columns=['price_usd', 'loves_count'],
      unique_columns=['product_id'],
    )
    stats["product_inserted"] = load_dim_product(dw_conn, product_dim)

    customer_df = extract_customers(oltp_conn)
    customer_dim = build_dim_customer(customer_df)
    stats["customer_inserted"] = load_dim_customer(dw_conn, customer_dim)

    profile_df = extract_reviewer_profiles(oltp_conn)
    profile_dim = build_dim_reviewer_profile(profile_df)
    stats["profile_inserted"] = load_dim_reviewer_profile(dw_conn, profile_dim)

    # dim_date's range is derived from the OLTP data, not hardcoded (D12)
    start_date, end_date = extract_date_bounds(oltp_conn)
    stats["date_inserted"] = load_dim_date(dw_conn, start_date, end_date)

    logger.info(f"Dim load completed in {time.time() - t0:.2f}s")

    # --- Stage 3: fact ---
    t0 = time.time()
    lookups = extract_lookup_dim(dw_conn)

    watermark = None
    if mode == INCREMENTAL:
      # Captured before any write to fact_reviews happens in this run, so it
      # cannot advance past rows this same run is about to load.
      watermark = get_watermark(dw_conn)
    stats["watermark"] = str(watermark) if watermark else None

    batch_df = extract_reviews_for_mode(oltp_conn, mode, watermark)
    stats["rows_extracted"] = len(batch_df)

    fact_df, fact_drops = build_fact_reviews(batch_df, lookups)
    stats["rows_transformed"] = len(fact_df)
    stats["rows_dropped"] = reconcile_transform(
      len(batch_df), len(fact_df), fact_drops, 'fact_reviews')

    run_quality_checks(
      fact_df, 'fact_reviews',
      key_columns=['product_key', 'customer_key', 'reviewer_profile_key',
                   'date_key'],
      non_negative_columns=['total_feedback_count', 'total_pos_feedback_count',
                            'total_neg_feedback_count'],
      unique_columns=['source_row_id', 'product_id'],
      rating_column='rating',
      null_rate_checks=[('is_recommended', 30.0), ('helpfulness', 80.0)],
    )

    inserted = load_fact_reviews(dw_conn, fact_df)
    stats["rows_inserted"] = inserted
    stats["rows_already_present"] = reconcile_load(
      len(fact_df), inserted, 'fact_reviews')

    logger.info(f"Fact load completed in {time.time() - t0:.2f}s")

    # The watermark AFTER this run — proves it advanced (or correctly did not).
    stats["watermark_after"] = str(get_watermark(dw_conn))

    logger.info("=" * 70)
    logger.info(f"{mode.upper()} run complete: "
                f"{stats['rows_extracted']} extracted, "
                f"{stats['rows_transformed']} transformed, "
                f"{stats['rows_inserted']} inserted, "
                f"{stats['rows_already_present']} already present. "
                f"Watermark now {stats['watermark_after']}")
    logger.info(f"Log written to {log_filename}")
    logger.info("=" * 70)

    return stats

  finally:
    if owns_connections:
      oltp_conn.close()
      dw_conn.close()


def main():
  args = parse_args()
  run_pipeline(mode=args.mode)


if __name__ == "__main__":
  main()
