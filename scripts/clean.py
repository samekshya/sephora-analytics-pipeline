"""
clean.py
--------
Cleans the raw Sephora CSVs into data/processed/, ready for ingest.py to COPY
into the raw schema of sephora_oltp.

Scope of this step is deliberately narrow — structural cleaning only:
  - deduplication
  - type coercion (dates as dates, numerics as numerics, flags as booleans)
  - whitespace trimming
  - value normalisation of known defects ('Grey'/'gray', 'notSureST')
  - one derived column (review_length) so review_text never has to reach the
    warehouse (D6)

What this step does NOT do is drop columns. Every source column survives into
the raw layer for traceability; column trims happen once, explicitly, at the
raw -> 3nf boundary (see D3 and D14). A cleaning step that also drops columns
makes it impossible to tell later which was which.

Every rule logs rows in / rows out / rows dropped so the reconciliation in
docs/00_project_checkpoint.md is measured rather than assumed.
"""

import glob
import logging
import os
from datetime import datetime

import pandas as pd

# Anchored on this file, not the working directory: the script lives in
# scripts/ and the data lives at the repository root, so a cwd-relative path
# would resolve differently depending on where it was launched from.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(REPO_ROOT, 'data', 'raw')
PROCESSED_DIR = os.path.join(REPO_ROOT, 'data', 'processed')
LOG_DIR = os.path.join(REPO_ROOT, 'logs')

# Dedup key per D4 — the date is part of it, because the same author reviewing
# the same product on different dates is a legitimate re-review, not a duplicate.
REVIEW_DEDUP_KEY = ['author_id', 'product_id', 'submission_time']

REVIEWER_ATTRS = ['skin_tone', 'skin_type', 'eye_color', 'hair_color']

# Stored 0/1 in the source; real booleans in the processed output.
PRODUCT_FLAGS = ['limited_edition', 'new', 'online_only', 'out_of_stock',
                 'sephora_exclusive']

# Integer and float columns are coerced separately, and integers use pandas'
# nullable Int64 rather than float64. A nullable int column read as float64
# writes back as "11.0", which COPY rejects against an INTEGER column — the
# decimal point is not a formatting detail, it changes the type.
PRODUCT_INTEGERS = ['brand_id', 'loves_count', 'reviews', 'child_count']

PRODUCT_FLOATS = ['rating', 'price_usd', 'value_price_usd', 'sale_price_usd',
                  'child_max_price', 'child_min_price']

REVIEW_INTEGERS = ['source_row_id', 'rating', 'total_feedback_count',
                   'total_neg_feedback_count', 'total_pos_feedback_count']

REVIEW_FLOATS = ['helpfulness', 'price_usd']

os.makedirs(LOG_DIR, exist_ok=True)

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
log_filename = os.path.join(LOG_DIR, f'clean_{timestamp}.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)s [%(filename)s:%(lineno)d] %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def _trim_text_columns(df):
    """Strip leading/trailing whitespace from every text column in place."""
    trimmed = 0
    for col in df.columns:
        if df[col].dtype == object or str(df[col].dtype) == 'str':
            before = df[col]
            after = before.str.strip() if hasattr(before, 'str') else before
            trimmed += int((before != after).sum())
            df[col] = after
    logger.info(f'Trimmed whitespace on {trimmed} cell(s)')
    return df


def _empty_to_null(df, columns):
    """Turn empty strings into real nulls so Postgres gets NULL, not ''."""
    for col in columns:
        if col in df.columns:
            df[col] = df[col].replace('', None)
    return df


def clean_products():
    """Clean product_info.csv -> data/processed/products.csv."""
    path = os.path.join(RAW_DIR, 'product_info.csv')
    df = pd.read_csv(path, dtype={'product_id': str})
    rows_in = len(df)
    logger.info(f'products: read {rows_in} rows from {path}')

    df = _trim_text_columns(df)

    # Exact duplicate rows
    before = len(df)
    df = df.drop_duplicates()
    logger.info(f'products: dropped {before - len(df)} exact duplicate row(s)')

    # product_id must be unique — it is the primary key of 3nf.product
    dupe_ids = int(df['product_id'].duplicated().sum())
    if dupe_ids:
        raise ValueError(f'products: {dupe_ids} duplicate product_id values — '
                         f'cannot be a primary key')
    logger.info('products: product_id is unique — 0 duplicates')

    # brand_id -> brand_name must be 1:1 for 3nf.brand to be keyed on brand_id
    per_brand = df.groupby('brand_id')['brand_name'].nunique().max()
    if per_brand > 1:
        raise ValueError(f'products: a brand_id maps to {per_brand} brand_names — '
                         f'brand cannot be keyed on brand_id')
    logger.info('products: brand_id -> brand_name is 1:1')

    for col in PRODUCT_FLOATS:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    for col in PRODUCT_INTEGERS:
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')

    for col in PRODUCT_FLAGS:
        df[col] = df[col].astype('boolean')

    df = _empty_to_null(df, ['size', 'variation_type', 'variation_value',
                             'variation_desc', 'ingredients', 'highlights',
                             'secondary_category', 'tertiary_category'])

    logger.info(f'products: {rows_in} rows in -> {len(df)} rows out '
                f'({rows_in - len(df)} dropped)')
    return df


def _read_review_file(path):
    """Read one review CSV, naming the unnamed index column and tagging its source."""
    df = pd.read_csv(path, dtype={'author_id': str, 'product_id': str})
    df = df.rename(columns={df.columns[0]: 'source_row_id'})
    df['source_file'] = os.path.basename(path)
    return df


def clean_reviews():
    """Clean the five review CSVs -> data/processed/reviews.csv."""
    paths = sorted(glob.glob(os.path.join(RAW_DIR, 'reviews_*.csv')))
    frames = []
    for path in paths:
        part = _read_review_file(path)
        logger.info(f'reviews: read {len(part)} rows from {os.path.basename(path)}')
        frames.append(part)
    df = pd.concat(frames, ignore_index=True)
    rows_in = len(df)
    logger.info(f'reviews: {rows_in} rows read across {len(paths)} files')

    df = _trim_text_columns(df)

    # --- deduplication (D4) ---
    before = len(df)
    df = df.drop_duplicates(subset=REVIEW_DEDUP_KEY, keep='first')
    dropped = before - len(df)
    logger.info(f'reviews: dropped {dropped} duplicate row(s) on '
                f'{tuple(REVIEW_DEDUP_KEY)}')

    # --- idempotency key must survive deduplication (D13) ---
    key_dupes = int(df.duplicated(subset=['source_row_id', 'product_id']).sum())
    if key_dupes:
        raise ValueError(f'reviews: {key_dupes} duplicate (source_row_id, product_id) '
                         f'pairs — the fact table idempotency key would collide')
    logger.info('reviews: (source_row_id, product_id) is unique — 0 collisions')

    # --- value normalisation of the two defects found during exploration ---
    before_grey = int((df['eye_color'] == 'Grey').sum())
    df['eye_color'] = df['eye_color'].replace('Grey', 'gray')
    logger.info(f"reviews: normalised {before_grey} eye_color 'Grey' -> 'gray'")

    before_notsure = int((df['skin_tone'] == 'notSureST').sum())
    df['skin_tone'] = df['skin_tone'].replace('notSureST', None)
    logger.info(f"reviews: mapped {before_notsure} skin_tone 'notSureST' -> null "
                f'(a placeholder, not a skin tone)')

    # --- type coercion ---
    for col in REVIEW_FLOATS:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    for col in REVIEW_INTEGERS:
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')

    df['submission_time'] = pd.to_datetime(df['submission_time'], errors='coerce')
    unparseable = int(df['submission_time'].isna().sum())
    if unparseable:
        raise ValueError(f'reviews: {unparseable} unparseable submission_time values')
    logger.info('reviews: all submission_time values parsed — 0 failures')
    df['submission_time'] = df['submission_time'].dt.date

    # is_recommended arrives as 1.0/0.0/NaN
    df['is_recommended'] = df['is_recommended'].astype('boolean')

    # --- derived column (D6): keeps review_text out of the warehouse ---
    df['review_length'] = df['review_text'].str.len().astype('Int64')
    logger.info('reviews: derived review_length from review_text')

    df = _empty_to_null(df, ['review_text', 'review_title'] + REVIEWER_ATTRS)

    logger.info(f'reviews: {rows_in} rows in -> {len(df)} rows out '
                f'({rows_in - len(df)} dropped)')
    return df


def write(df, filename):
    """Write a cleaned frame to data/processed/."""
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    path = os.path.join(PROCESSED_DIR, filename)
    df.to_csv(path, index=False, encoding='utf-8')
    size_mb = os.path.getsize(path) / 1_000_000
    logger.info(f'Wrote {len(df)} rows to {path} ({size_mb:.1f} MB)')


def main():
    logger.info('=' * 60)
    logger.info('Cleaning products')
    logger.info('=' * 60)
    products = clean_products()
    write(products, 'products.csv')

    logger.info('=' * 60)
    logger.info('Cleaning reviews')
    logger.info('=' * 60)
    reviews = clean_reviews()
    write(reviews, 'reviews.csv')

    logger.info('=' * 60)
    logger.info(f'Done. Log written to {log_filename}')


if __name__ == '__main__':
    main()
