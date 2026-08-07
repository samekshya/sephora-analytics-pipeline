"""
transform.py
------------
Turns extracted DataFrames into the exact shape each warehouse table expects:
renames business keys, resolves natural keys to surrogate keys via lookup
merges, and computes derived columns.

Every build_* function that can drop rows returns a (DataFrame, drops) PAIR,
where `drops` maps a NAMED REASON to a count:

    {'unresolved_product': 12, 'unresolved_customer': 0,
     'unresolved_reviewer_profile': 0, 'unresolved_date': 3}

This is the difference between "some rows went missing" and "12 reviews pointed
at a product that isn't in dim_product". The caller feeds those counts to
etl.reconcile, which enforces extracted == transformed + dropped and raises if
they don't balance. A drop that isn't counted here becomes an unexplained
discrepancy there, which fails the run - so the two halves keep each other
honest.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# Price bands are computed here, once, so every visual that groups by price uses
# identical boundaries. Computing them per-visual in the dashboard is how two
# charts end up disagreeing about the same products.
PRICE_BAND_EDGES = [0, 15, 30, 50, 100, float('inf')]
PRICE_BAND_LABELS = ['Under $15', '$15-30', '$30-50', '$50-100', '$100+']


def _drop_unmatched(df: pd.DataFrame, key_col: str, reason: str, drops: dict):
  """Drop rows whose merge key didn't resolve, recording HOW MANY and WHY.

  Records the count under `reason` unconditionally - including when it is zero.
  A reason key that only appears when it fires makes "nothing was dropped" and
  "this was never checked" indistinguishable in the logs.
  """
  missing = df[key_col].isna()
  count = int(missing.sum())
  drops[reason] = drops.get(reason, 0) + count

  if count:
    logger.warning(f"Dropping {count} row(s): {reason} (null {key_col})")

  return df[~missing]


# --------------------------------------------------------------------------
# Dimensions
# --------------------------------------------------------------------------

def build_dim_brand(brand_df: pd.DataFrame) -> pd.DataFrame:
  df = brand_df.copy()
  df = df.drop_duplicates(subset=['brand_id']).reset_index(drop=True)
  logger.info(f"Built brand dimension with {len(df)} rows")
  return df


def build_dim_customer(customer_df: pd.DataFrame) -> pd.DataFrame:
  df = customer_df.copy()
  df = df.rename(columns={"author_id": "customer_id"})
  df = df.drop_duplicates(subset=['customer_id']).reset_index(drop=True)
  logger.info(f"Built customer dimension with {len(df)} rows")
  return df


def build_dim_reviewer_profile(profile_df: pd.DataFrame) -> pd.DataFrame:
  df = profile_df.copy()
  df = df[['skin_tone', 'skin_type', 'eye_color', 'hair_color']]
  df = df.drop_duplicates().reset_index(drop=True)
  logger.info(f"Built reviewer profile dimension with {len(df)} rows")
  return df


DIM_PRODUCT_COLUMNS = [
    "product_id",
    "product_name",
    "brand_key",
    "primary_category",
    "secondary_category",
    "tertiary_category",
    "price_usd",
    "price_band",
    "size",
    "loves_count",
    "limited_edition",
    "new",
    "online_only",
    "out_of_stock",
    "sephora_exclusive",
]

DIM_PRODUCT_DROP_REASONS = ['unresolved_brand']


def build_dim_product(product_df: pd.DataFrame, brand_lookup: pd.DataFrame):
  """Resolve brand_id -> brand_key and band the price.

  Needs dim_brand loaded first, which is why product waits on brand in both
  pipeline.py and the DAG.

  Returns (DataFrame, drops).
  """
  drops = {reason: 0 for reason in DIM_PRODUCT_DROP_REASONS}

  if product_df.empty:
    logger.info("No products extracted - nothing to transform")
    return pd.DataFrame(columns=DIM_PRODUCT_COLUMNS), drops

  df = product_df.copy()

  df = df.merge(brand_lookup, on="brand_id", how="left")
  df = _drop_unmatched(df, 'brand_key', 'unresolved_brand', drops)

  df["price_band"] = pd.cut(
    df["price_usd"],
    bins=PRICE_BAND_EDGES,
    labels=PRICE_BAND_LABELS,
    right=False,
  ).astype(str)

  result = df[DIM_PRODUCT_COLUMNS].reset_index(drop=True)
  logger.info(f"Built product dimension with {len(result)} rows, "
              f"dropped {sum(drops.values())}")
  return result, drops


# --------------------------------------------------------------------------
# Fact
# --------------------------------------------------------------------------

FACT_COLUMNS = [
    "source_row_id",
    "product_id",
    "product_key",
    "customer_key",
    "reviewer_profile_key",
    "date_key",
    "rating",
    "is_recommended",
    "helpfulness",
    "total_feedback_count",
    "total_pos_feedback_count",
    "total_neg_feedback_count",
    "review_length",
    "submission_date",
]

PROFILE_KEYS = ['skin_tone', 'skin_type', 'eye_color', 'hair_color']

# Declared up front so every reason is present in the drops dict with a zero,
# even on a run where nothing is dropped at all.
FACT_DROP_REASONS = [
    'unresolved_product',
    'unresolved_customer',
    'unresolved_reviewer_profile',
    'out_of_range_date',
]


def build_fact_reviews(reviews_df: pd.DataFrame, lookups: dict):
  """Resolve every natural key to its surrogate key.

  Four merges: product, customer, reviewer profile (on all four attributes at
  once — that is what makes it a junk dimension), and date.

  Returns (DataFrame, drops) where drops is keyed by FACT_DROP_REASONS.
  """
  drops = {reason: 0 for reason in FACT_DROP_REASONS}

  if reviews_df.empty:
    logger.info("No reviews extracted - nothing to transform")
    return pd.DataFrame(columns=FACT_COLUMNS), drops

  initial_count = len(reviews_df)
  df = reviews_df.copy()

  df = df.merge(lookups["product"], on="product_id", how="left")
  df = _drop_unmatched(df, 'product_key', 'unresolved_product', drops)

  df = df.merge(
    lookups["customer"],
    left_on="author_id",
    right_on="customer_id",
    how="left",
  )
  df = _drop_unmatched(df, 'customer_key', 'unresolved_customer', drops)

  # The junk dimension merges on all four attributes together — one lookup, not
  # four. Every combination present in the data is present in the dimension,
  # because both come from the same DISTINCT over staging.review.
  df = df.merge(lookups["reviewer_profile"], on=PROFILE_KEYS, how="left")
  df = _drop_unmatched(df, 'reviewer_profile_key',
                       'unresolved_reviewer_profile', drops)

  # A review whose date falls outside dim_date's range. dim_date is generated
  # from the data with 30 days of padding, so this should be structurally
  # impossible - which is exactly why it is worth counting rather than
  # assuming.
  df = df.merge(
    lookups["date"],
    left_on="submission_date",
    right_on="full_date",
    how="left",
  )
  df = _drop_unmatched(df, 'date_key', 'out_of_range_date', drops)

  # Surrogate keys arrive as float64 whenever a merge produced any NaN, and a
  # float in an INTEGER column is a type error, not a formatting one.
  for col in ["product_key", "customer_key", "reviewer_profile_key", "date_key"]:
    df[col] = df[col].astype('int64')

  result = df[FACT_COLUMNS].reset_index(drop=True)
  total_dropped = sum(drops.values())
  logger.info(f"Transformed {len(result)} of {initial_count} rows, "
              f"dropped {total_dropped}")
  return result, drops
