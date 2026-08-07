"""
conftest.py
-----------
Shared fixtures. Repo root goes on sys.path so `import etl...` works whether
pytest is invoked from the root or from inside tests/.
"""

import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
  sys.path.insert(0, ROOT)


@pytest.fixture
def good_fact_frame():
  """A minimal VALID fact frame.

  Every quality test starts from this and breaks exactly one thing, so a
  failure names the defect rather than leaving you to guess which of six
  differences mattered.
  """
  return pd.DataFrame({
    "source_row_id": [1, 2, 3],
    "product_id": ["P1", "P2", "P3"],
    "product_key": [1, 2, 3],
    "customer_key": [1, 2, 3],
    "reviewer_profile_key": [1, 1, 2],
    "date_key": [20230101, 20230102, 20230103],
    "rating": [5, 4, 3],
    "is_recommended": [True, True, False],
    "helpfulness": [0.5, 0.75, None],
    "total_feedback_count": [2, 4, 0],
    "total_pos_feedback_count": [1, 3, 0],
    "total_neg_feedback_count": [1, 1, 0],
    "review_length": [100, 250, 80],
    "submission_date": pd.to_datetime(
      ["2023-01-01", "2023-01-02", "2023-01-03"]).date,
  })


FACT_KEYS = ['product_key', 'customer_key', 'reviewer_profile_key', 'date_key']
FACT_COUNTS = ['total_feedback_count', 'total_pos_feedback_count',
               'total_neg_feedback_count']


@pytest.fixture
def fact_check_kwargs():
  """The exact quality-gate arguments the pipeline uses for fact_reviews.

  Tests call the gate the same way production does; a test that passed
  different arguments would be proving something nothing else runs.
  """
  return dict(
    key_columns=FACT_KEYS,
    non_negative_columns=FACT_COUNTS,
    unique_columns=['source_row_id', 'product_id'],
    rating_column='rating',
  )


@pytest.fixture
def dim_lookups():
  """Minimal warehouse key lookups for transform tests."""
  return {
    "product": pd.DataFrame({"product_id": ["P1", "P2"],
                             "product_key": [10, 20]}),
    "customer": pd.DataFrame({"customer_id": ["A1", "A2"],
                              "customer_key": [100, 200]}),
    "reviewer_profile": pd.DataFrame({
      "skin_tone": ["light"], "skin_type": ["dry"],
      "eye_color": ["blue"], "hair_color": ["blonde"],
      "reviewer_profile_key": [7],
    }),
    "date": pd.DataFrame({
      "date_key": [20230101, 20230102],
      "full_date": pd.to_datetime(["2023-01-01", "2023-01-02"]).date,
    }),
  }


@pytest.fixture
def raw_review_frame():
  """Two reviews that fully resolve against dim_lookups."""
  return pd.DataFrame({
    "source_row_id": [1, 2],
    "product_id": ["P1", "P2"],
    "author_id": ["A1", "A2"],
    "submission_date": pd.to_datetime(["2023-01-01", "2023-01-02"]).date,
    "rating": [5, 4],
    "is_recommended": [True, False],
    "helpfulness": [0.5, 0.25],
    "total_feedback_count": [2, 4],
    "total_pos_feedback_count": [1, 1],
    "total_neg_feedback_count": [1, 3],
    "review_length": [100, 200],
    "skin_tone": ["light", "light"],
    "skin_type": ["dry", "dry"],
    "eye_color": ["blue", "blue"],
    "hair_color": ["blonde", "blonde"],
  })
