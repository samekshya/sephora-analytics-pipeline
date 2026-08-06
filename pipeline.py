"""
pipeline.py
-----------
Local orchestration of the ETL package: sephora_oltp (staging) -> sephora_dw.

  python pipeline.py --full-reload   # everything before the 2023-01-01 cutoff
  python pipeline.py                 # incremental — everything after the watermark

The Airflow DAG runs the same etl/ functions with the same ordering; this script
exists so the pipeline can be run and debugged without a scheduler in the way.

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
  extract_reviews_full, extract_reviews_incremental,
  extract_lookup_dim, extract_brand_lookup, get_watermark,
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


def parse_args():
  parser = argparse.ArgumentParser(description="Sephora DW ETL pipeline")
  parser.add_argument(
    "--full-reload",
    action="store_true",
    help="Full load (everything before 2023-01-01) instead of incremental "
         "(default: incremental)"
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


def main():
  args = parse_args()
  mode = 'FULL' if args.full_reload else 'INCREMENTAL'
  logger.info(f"Running pipeline in {mode} mode")

  oltp_conn = psycopg2.connect(**OLTP_DB_CONFIG)
  dw_conn = psycopg2.connect(**DW_DB_CONFIG)
  try:
    # --- Stage 1: brand (dim_product depends on it) ---
    t0 = time.time()
    brand_df = extract_brands(oltp_conn)
    brand_dim = build_dim_brand(brand_df)
    load_dim_brand(dw_conn, brand_dim)
    logger.info(f"Brand load completed in {time.time() - t0:.2f}s")

    # --- Stage 2: remaining dimensions ---
    t0 = time.time()
    brand_lookup = extract_brand_lookup(dw_conn)
    product_df = extract_products(oltp_conn)
    product_dim = build_dim_product(product_df, brand_lookup)
    run_quality_checks(
      product_dim, 'dim_product',
      key_columns=['brand_key'],
      non_negative_columns=['price_usd', 'loves_count'],
      unique_columns=['product_id'],
    )
    load_dim_product(dw_conn, product_dim)

    customer_df = extract_customers(oltp_conn)
    customer_dim = build_dim_customer(customer_df)
    load_dim_customer(dw_conn, customer_dim)

    profile_df = extract_reviewer_profiles(oltp_conn)
    profile_dim = build_dim_reviewer_profile(profile_df)
    load_dim_reviewer_profile(dw_conn, profile_dim)

    # dim_date's range is derived from the OLTP data, not hardcoded (D12)
    start_date, end_date = extract_date_bounds(oltp_conn)
    load_dim_date(dw_conn, start_date, end_date)

    logger.info(f"Dim load completed in {time.time() - t0:.2f}s")

    # --- Stage 3: fact ---
    t0 = time.time()
    lookups = extract_lookup_dim(dw_conn)

    if mode == 'INCREMENTAL':
      # Captured before any write to fact_reviews happens in this run, so it
      # cannot advance past rows this same run is about to load.
      watermark = get_watermark(dw_conn)
      logger.info(f"Running incremental load from {watermark}")
      batch_reviews_df = extract_reviews_incremental(oltp_conn, watermark)
    else:
      batch_reviews_df = extract_reviews_full(oltp_conn)

    fact_reviews = build_fact_reviews(batch_reviews_df, lookups)
    run_quality_checks(
      fact_reviews, 'fact_reviews',
      key_columns=['product_key', 'customer_key', 'reviewer_profile_key', 'date_key'],
      non_negative_columns=['total_feedback_count', 'total_pos_feedback_count',
                            'total_neg_feedback_count'],
      unique_columns=['source_row_id', 'product_id'],
      rating_column='rating',
    )
    load_fact_reviews(dw_conn, fact_reviews)
    logger.info(f"Fact load completed in {time.time() - t0:.2f}s")

    logger.info(f"Done. Log written to {log_filename}")

  finally:
    oltp_conn.close()
    dw_conn.close()


if __name__ == "__main__":
  main()
