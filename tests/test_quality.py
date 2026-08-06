"""
test_quality.py
---------------
Fault injection for the quality gate. Feeds it data that is deliberately broken
in one specific way per case and asserts it refuses to pass.

The point is not that clean data passes - that is proven by every pipeline run.
The point is that dirty data FAILS. A gate that has never been seen to fail is
indistinguishable from a gate that cannot fail.

  python tests/test_quality.py
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd

from etl.quality import DataQualityError, run_quality_checks

FACT_KEYS = ['product_key', 'customer_key', 'reviewer_profile_key', 'date_key']
FACT_COUNTS = ['total_feedback_count', 'total_pos_feedback_count',
               'total_neg_feedback_count']

passed = 0
failed = 0


def good_frame():
  """A minimal, valid fact frame. Each test breaks exactly one thing in it."""
  return pd.DataFrame({
    "source_row_id": [1, 2, 3],
    "product_id": ["P1", "P2", "P3"],
    "product_key": [1, 2, 3],
    "customer_key": [1, 2, 3],
    "reviewer_profile_key": [1, 1, 2],
    "date_key": [20230101, 20230102, 20230103],
    "rating": [5, 4, 3],
    "total_feedback_count": [2, 0, 5],
    "total_pos_feedback_count": [2, 0, 3],
    "total_neg_feedback_count": [0, 0, 2],
  })


def check(name, df, should_raise=True):
  """Run the gate on df and report whether it behaved as expected."""
  global passed, failed
  try:
    run_quality_checks(
      df, 'test_fact_reviews',
      key_columns=FACT_KEYS,
      non_negative_columns=FACT_COUNTS,
      unique_columns=['source_row_id', 'product_id'],
      rating_column='rating',
    )
    raised = False
    message = ''
  except DataQualityError as e:
    raised = True
    message = str(e)

  if raised == should_raise:
    passed += 1
    detail = f' -> {message}' if raised else ''
    print(f'PASS  {name}{detail}')
  else:
    failed += 1
    expected = 'to raise' if should_raise else 'to pass'
    print(f'FAIL  {name}: expected the gate {expected}, it did not')


print('=' * 70)
print('Quality gate fault injection')
print('=' * 70)

# Baseline: valid data must get through, or every other case proves nothing.
check('clean data passes', good_frame(), should_raise=False)

# A null surrogate key means a merge in transform.py silently failed to resolve.
df = good_frame()
df.loc[1, 'customer_key'] = None
check('null surrogate key is caught', df)

# Negative counts cannot occur naturally - they mean the transform corrupted it.
df = good_frame()
df.loc[2, 'total_neg_feedback_count'] = -5
check('negative feedback count is caught', df)

# Ratings are 1-5 by definition.
df = good_frame()
df.loc[0, 'rating'] = 9
check('out-of-range rating is caught', df)

df = good_frame()
df.loc[0, 'rating'] = 0
check('zero rating is caught', df)

# A duplicated business key would be absorbed by ON CONFLICT, making the loaded
# count silently disagree with the extracted count.
df = good_frame()
df.loc[2, 'source_row_id'] = 1
df.loc[2, 'product_id'] = 'P1'
check('duplicate business key is caught', df)

# Several faults at once must still fail (and name one of them).
df = good_frame()
df.loc[0, 'product_key'] = None
df.loc[1, 'rating'] = 11
df.loc[2, 'total_feedback_count'] = -1
check('multiple faults are caught', df)

# An empty frame is a valid outcome, not a fault: an incremental run with
# nothing new past the watermark must not fail the pipeline.
check('empty frame skips the gate', good_frame().iloc[0:0], should_raise=False)

print('=' * 70)
print(f'{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
