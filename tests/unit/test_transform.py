"""
test_transform.py
-----------------
Surrogate key resolution and the reconciliation identity.

Two things are proven here:

  1. Natural keys resolve to the right surrogate keys — a fact row must point
     at the dimension member it actually belongs to, not merely at *some*
     member. A merge that silently mis-joins produces a warehouse that is
     internally consistent and completely wrong.

  2. Every dropped row is COUNTED AND CATEGORIZED, and an unexplained gap
     raises rather than shipping a short table.
"""

import pandas as pd
import pytest

from etl.reconcile import ReconciliationError, reconcile_load, reconcile_transform
from etl.transform import (
  FACT_DROP_REASONS, build_dim_product, build_fact_reviews,
)


# --------------------------------------------------------------------------
# Surrogate key resolution
# --------------------------------------------------------------------------

def test_resolves_surrogate_keys_to_correct_members(raw_review_frame,
                                                    dim_lookups):
  fact, drops = build_fact_reviews(raw_review_frame, dim_lookups)

  assert len(fact) == 2
  assert sum(drops.values()) == 0

  # P1 -> 10 and P2 -> 20, not merely "some key"
  by_product = dict(zip(fact["product_id"], fact["product_key"]))
  assert by_product == {"P1": 10, "P2": 20}

  assert list(fact["customer_key"]) == [100, 200]
  assert list(fact["date_key"]) == [20230101, 20230102]
  # The junk dimension matches on all four attributes at once
  assert list(fact["reviewer_profile_key"]) == [7, 7]


def test_surrogate_keys_are_integers_not_floats(raw_review_frame, dim_lookups):
  """A merge producing any NaN upgrades the column to float64, and a float in
  an INTEGER column is a type error, not a formatting one."""
  fact, _ = build_fact_reviews(raw_review_frame, dim_lookups)

  for col in ["product_key", "customer_key", "reviewer_profile_key", "date_key"]:
    assert fact[col].dtype == "int64", f"{col} is {fact[col].dtype}, not int64"


def test_all_drop_reasons_present_even_when_zero(raw_review_frame, dim_lookups):
  """A reason that only appears when it fires makes 'nothing was dropped'
  indistinguishable from 'this was never checked'."""
  _, drops = build_fact_reviews(raw_review_frame, dim_lookups)

  assert set(drops) == set(FACT_DROP_REASONS)
  assert all(v == 0 for v in drops.values())


# --------------------------------------------------------------------------
# Categorized drops — one test per reason
# --------------------------------------------------------------------------

def test_unresolved_product_is_counted(raw_review_frame, dim_lookups):
  df = raw_review_frame.copy()
  df.loc[1, "product_id"] = "GHOST"

  fact, drops = build_fact_reviews(df, dim_lookups)

  assert len(fact) == 1
  assert drops["unresolved_product"] == 1
  assert drops["unresolved_customer"] == 0


def test_unresolved_customer_is_counted(raw_review_frame, dim_lookups):
  df = raw_review_frame.copy()
  df.loc[0, "author_id"] = "NOBODY"

  fact, drops = build_fact_reviews(df, dim_lookups)

  assert len(fact) == 1
  assert drops["unresolved_customer"] == 1


def test_unresolved_reviewer_profile_is_counted(raw_review_frame, dim_lookups):
  df = raw_review_frame.copy()
  df.loc[0, "skin_type"] = "combination"  # not in the junk dimension

  fact, drops = build_fact_reviews(df, dim_lookups)

  assert len(fact) == 1
  assert drops["unresolved_reviewer_profile"] == 1


def test_out_of_range_date_is_counted(raw_review_frame, dim_lookups):
  """dim_date is generated from the data with 30 days of padding, so this
  should be structurally impossible — which is why it is counted rather than
  assumed."""
  df = raw_review_frame.copy()
  df.loc[1, "submission_date"] = pd.Timestamp("1999-01-01").date()

  fact, drops = build_fact_reviews(df, dim_lookups)

  assert len(fact) == 1
  assert drops["out_of_range_date"] == 1


def test_empty_input_returns_typed_empty_frame(dim_lookups):
  """An empty incremental batch must be a no-op, not a crash."""
  fact, drops = build_fact_reviews(pd.DataFrame(), dim_lookups)

  assert fact.empty
  assert set(drops) == set(FACT_DROP_REASONS)
  assert sum(drops.values()) == 0


def test_dim_product_counts_unresolved_brand():
  products = pd.DataFrame({
    "product_id": ["P1", "P2"],
    "product_name": ["A", "B"],
    "brand_id": [1, 999],           # 999 is not in dim_brand
    "primary_category": ["Skincare"] * 2,
    "secondary_category": ["Moisturizers"] * 2,
    "tertiary_category": [None, None],
    "price_usd": [20.0, 60.0],
    "size": ["1 oz", "2 oz"],
    "loves_count": [10, 20],
    "limited_edition": [False, False],
    "new": [False, False],
    "online_only": [False, False],
    "out_of_stock": [False, False],
    "sephora_exclusive": [False, False],
  })
  brand_lookup = pd.DataFrame({"brand_id": [1], "brand_key": [5]})

  dim, drops = build_dim_product(products, brand_lookup)

  assert len(dim) == 1
  assert drops["unresolved_brand"] == 1
  assert dim.iloc[0]["brand_key"] == 5


def test_price_bands_use_shared_boundaries():
  """Bands are computed once here so every visual agrees. Boundaries are
  left-closed: $30.00 belongs to $30-50, not $15-30."""
  products = pd.DataFrame({
    "product_id": [f"P{i}" for i in range(5)],
    "product_name": list("ABCDE"),
    "brand_id": [1] * 5,
    "primary_category": ["Skincare"] * 5,
    "secondary_category": ["Moisturizers"] * 5,
    "tertiary_category": [None] * 5,
    "price_usd": [9.99, 15.00, 30.00, 50.00, 250.00],
    "size": [None] * 5,
    "loves_count": [0] * 5,
    "limited_edition": [False] * 5,
    "new": [False] * 5,
    "online_only": [False] * 5,
    "out_of_stock": [False] * 5,
    "sephora_exclusive": [False] * 5,
  })
  brand_lookup = pd.DataFrame({"brand_id": [1], "brand_key": [5]})

  dim, _ = build_dim_product(products, brand_lookup)

  assert list(dim["price_band"]) == [
    "Under $15", "$15-30", "$30-50", "$50-100", "$100+"]


# --------------------------------------------------------------------------
# The reconciliation identity itself
# --------------------------------------------------------------------------

def test_reconcile_transform_balances():
  dropped = reconcile_transform(100, 95, {"unresolved_product": 5}, "t")
  assert dropped == 5


def test_reconcile_transform_raises_on_unexplained_loss():
  """5 rows vanished with no reason attached. This is the whole point of the
  module: the run must die rather than quietly ship a short table."""
  with pytest.raises(ReconciliationError, match="UNEXPLAINED=5"):
    reconcile_transform(100, 90, {"unresolved_product": 5}, "t")


def test_reconcile_transform_raises_when_counts_exceed_input():
  with pytest.raises(ReconciliationError):
    reconcile_transform(10, 20, {"unresolved_product": 0}, "t")


def test_extracted_vs_transformed_mismatch_is_caught(raw_review_frame,
                                                     dim_lookups):
  """End-to-end: a real drop reconciles, but lying about the extracted count
  does not."""
  df = raw_review_frame.copy()
  df.loc[1, "product_id"] = "GHOST"
  fact, drops = build_fact_reviews(df, dim_lookups)

  # Honest accounting balances.
  assert reconcile_transform(len(df), len(fact), drops, "fact_reviews") == 1

  # Claiming 10 rows came in when 2 did must not pass.
  with pytest.raises(ReconciliationError):
    reconcile_transform(10, len(fact), drops, "fact_reviews")


def test_reconcile_load_reports_already_present():
  assert reconcile_load(100, 40, "fact_reviews") == 60


def test_reconcile_load_idempotent_rerun():
  """The idempotency signature: everything offered, nothing inserted."""
  assert reconcile_load(1000, 0, "fact_reviews") == 1000


def test_reconcile_load_raises_if_table_grew_more_than_offered():
  with pytest.raises(ReconciliationError):
    reconcile_load(10, 50, "fact_reviews")
