"""
test_quality.py
---------------
Fault injection for the quality gate.

The point is NOT that clean data passes — every pipeline run proves that. The
point is that dirty data FAILS. A gate that has never been observed to fail is
indistinguishable from a gate that cannot fail.

Each test starts from a valid frame and breaks exactly one thing, so a failure
names the defect instead of leaving you to guess which difference mattered.
"""

import pandas as pd
import pytest

from etl.quality import (
  DataQualityError, HARD_FAILURE, WARNING,
  check_null_rate, check_referential_integrity, run_quality_checks,
)


# --------------------------------------------------------------------------
# The baseline: valid data must pass, or every failure below proves nothing
# --------------------------------------------------------------------------

def test_valid_frame_passes(good_fact_frame, fact_check_kwargs):
  result = run_quality_checks(good_fact_frame, 'fact_reviews', **fact_check_kwargs)
  assert result["passed"] is True
  assert result["row_count"] == 3


# --------------------------------------------------------------------------
# Hard failures — each must HALT the pipeline
# --------------------------------------------------------------------------

@pytest.mark.parametrize("key_column", [
  "product_key", "customer_key", "reviewer_profile_key", "date_key",
])
def test_null_foreign_key_halts(good_fact_frame, fact_check_kwargs, key_column):
  """A null surrogate key would violate NOT NULL at load time.

  Caught here so the error names the column instead of surfacing as a bare
  Postgres constraint violation halfway through a 1M-row insert.
  """
  df = good_fact_frame.copy()
  df.loc[0, key_column] = None

  with pytest.raises(DataQualityError, match="no_null_keys"):
    run_quality_checks(df, 'fact_reviews', **fact_check_kwargs)


def test_rating_below_one_halts(good_fact_frame, fact_check_kwargs):
  df = good_fact_frame.copy()
  df.loc[0, "rating"] = 0

  with pytest.raises(DataQualityError, match="value_range"):
    run_quality_checks(df, 'fact_reviews', **fact_check_kwargs)


def test_rating_above_five_halts(good_fact_frame, fact_check_kwargs):
  df = good_fact_frame.copy()
  df.loc[1, "rating"] = 6

  with pytest.raises(DataQualityError, match="value_range"):
    run_quality_checks(df, 'fact_reviews', **fact_check_kwargs)


def test_negative_feedback_count_halts(good_fact_frame, fact_check_kwargs):
  """Feedback counts are counts. A negative one means the transform corrupted
  something upstream."""
  df = good_fact_frame.copy()
  df.loc[2, "total_feedback_count"] = -1

  with pytest.raises(DataQualityError, match="no_negative_values"):
    run_quality_checks(df, 'fact_reviews', **fact_check_kwargs)


def test_duplicate_source_key_halts(good_fact_frame, fact_check_kwargs):
  """Duplicate (source_row_id, product_id) is survivable but must still halt.

  ON CONFLICT DO NOTHING would absorb the duplicate without corrupting the
  warehouse — but then the loaded count silently disagrees with the extracted
  count, which is precisely the gap reconciliation exists to make impossible.
  """
  df = good_fact_frame.copy()
  df.loc[1, "source_row_id"] = df.loc[0, "source_row_id"]
  df.loc[1, "product_id"] = df.loc[0, "product_id"]

  with pytest.raises(DataQualityError, match="unique_key"):
    run_quality_checks(df, 'fact_reviews', **fact_check_kwargs)


def test_unresolved_product_reference_is_detected(good_fact_frame):
  """A product_key absent from dim_product must be flagged, not loaded.

  This is the check that catches a fact row pointing at a dimension member
  that does not exist — the FK would reject it at load time anyway, but only
  after the run has already spent its time.
  """
  valid_product_keys = pd.Series([1, 2])  # dim_product has no key 3

  result = check_referential_integrity(
    good_fact_frame, 'product_key', valid_product_keys, 'dim_product')

  assert result["passed"] is False
  assert result["severity"] == HARD_FAILURE
  assert "1 rows" in result["detail"]


# --------------------------------------------------------------------------
# Warnings — must be reported but must NOT halt
# --------------------------------------------------------------------------

def test_high_null_rate_warns_but_does_not_halt(good_fact_frame,
                                                fact_check_kwargs):
  """is_recommended is legitimately null in bulk (~15% of real reviews).

  Failing a run over that would be wrong. Saying nothing would be worse. So it
  warns: the run completes, and the shift is visible in the log.
  """
  df = good_fact_frame.copy()
  df["is_recommended"] = None

  result = run_quality_checks(
    df, 'fact_reviews',
    null_rate_checks=[('is_recommended', 30.0)],
    **fact_check_kwargs)

  assert result["passed"] is True, "a warning must not halt the pipeline"
  assert len(result["warnings"]) == 1
  assert result["warnings"][0]["severity"] == WARNING
  assert "100.00% null" in result["warnings"][0]["detail"]


def test_null_rate_within_threshold_does_not_warn(good_fact_frame,
                                                  fact_check_kwargs):
  result = run_quality_checks(
    good_fact_frame, 'fact_reviews',
    null_rate_checks=[('is_recommended', 30.0)],
    **fact_check_kwargs)

  assert result["warnings"] == []


def test_hard_failure_wins_over_warning(good_fact_frame, fact_check_kwargs):
  """When both fire, the hard failure must still halt the run.

  Guards against a regression where warnings are collected in a way that
  swallows the raise.
  """
  df = good_fact_frame.copy()
  df["is_recommended"] = None       # warning
  df.loc[0, "rating"] = 99          # hard failure

  with pytest.raises(DataQualityError):
    run_quality_checks(df, 'fact_reviews',
                       null_rate_checks=[('is_recommended', 1.0)],
                       **fact_check_kwargs)


# --------------------------------------------------------------------------
# Empty frames — a no-op incremental run is valid, not a fault
# --------------------------------------------------------------------------

def test_empty_frame_skips_gate_without_failing(fact_check_kwargs):
  """An incremental run with nothing new must be a clean no-op.

  If this raised, every quiet Tuesday would page somebody.
  """
  empty = pd.DataFrame(columns=['product_key', 'customer_key',
                                'reviewer_profile_key', 'date_key', 'rating',
                                'source_row_id', 'product_id',
                                'total_feedback_count',
                                'total_pos_feedback_count',
                                'total_neg_feedback_count'])

  result = run_quality_checks(empty, 'fact_reviews', **fact_check_kwargs)

  assert result["passed"] is True
  assert result["row_count"] == 0
  assert result["checks"] == []


def test_null_rate_on_empty_frame_is_zero():
  result = check_null_rate(pd.DataFrame({"c": []}), "c", 10.0)
  assert result["passed"] is True
