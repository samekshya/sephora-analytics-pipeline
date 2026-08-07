"""
quality.py
----------
Quality gate — runs structural/referential checks on transformed DataFrames
BEFORE load. Raises DataQualityError to halt the pipeline on a hard failure;
logs and continues on a warning.

This is a gate, not a fixer. A check that quietly repairs what it finds makes
itself unfalsifiable — it can never fail, so it can never tell you anything.
Cleaning belongs in clean.py, where it is logged and counted.

SEVERITY
--------
Every check declares a severity, and the two are treated differently:

  hard_failure  The row could not be loaded, or would load wrong. A null
                surrogate key violates NOT NULL; a rating of 7 violates a CHECK
                constraint; a duplicate idempotency key means the loaded count
                will silently disagree with the extracted count. These halt the
                pipeline before a single row is written.

  warning       The data is loadable and correct, but something is worth
                knowing — e.g. a nullable measure is more sparsely populated
                than expected. These are logged with full detail and the
                pipeline continues.

The distinction matters operationally: in Airflow a hard failure raises
AirflowFailException so the task fails immediately rather than burning its
retry budget on something that will never pass on a retry, whereas a warning
must never fail a run at all.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

HARD_FAILURE = "hard_failure"
WARNING = "warning"


class DataQualityError(Exception):
  """Raised when a hard-failure quality check fails. Halts the pipeline."""
  pass


def check_row_count(df: pd.DataFrame, min_rows: int = 1) -> dict:
  count = len(df)
  return {
      "check": "row_count",
      "severity": HARD_FAILURE,
      "passed": count >= min_rows,
      "detail": f"{count} rows (min: {min_rows})"
  }


def check_no_null_keys(df: pd.DataFrame, key_columns: list) -> dict:
  """Fail if any surrogate key column contains nulls.

  A null FK means a merge in transform.py didn't resolve and the drop tracking
  missed it — the row would violate NOT NULL at load time, but failing here
  names the column instead of surfacing a bare constraint error.
  """
  details = []
  total_bad = 0

  for col in key_columns:
    bad = int(df[col].isna().sum())
    total_bad += bad
    details.append(f"{col}: {bad} nulls")

  return {
    "check": "no_null_keys",
    "severity": HARD_FAILURE,
    "passed": total_bad == 0,
    "detail": ", ".join(details)
  }


def check_no_negative_values(df: pd.DataFrame, columns: list) -> dict:
  """Fail if any column holds a negative value.

  Feedback counts and review lengths are counts — a negative one means the
  transform corrupted something.
  """
  details = []
  total_bad = 0

  for col in columns:
    bad = int((df[col] < 0).sum())
    total_bad += bad
    details.append(f"{col}: {bad} negative values")

  return {
    "check": "no_negative_values",
    "severity": HARD_FAILURE,
    "passed": total_bad == 0,
    "detail": ", ".join(details)
  }


def check_value_range(df: pd.DataFrame, column: str, low, high) -> dict:
  """Fail if any non-null value falls outside [low, high].

  Ratings are 1-5 by definition; anything else means the source changed or the
  transform mangled the column.
  """
  values = df[column].dropna()
  bad = int(((values < low) | (values > high)).sum())
  return {
    "check": "value_range",
    "severity": HARD_FAILURE,
    "passed": bad == 0,
    "detail": f"{column}: {bad} value(s) outside [{low}, {high}]"
  }


def check_referential_integrity(df: pd.DataFrame, key_column: str,
                                valid_keys: pd.Series, label: str) -> dict:
  """Fail if any key in df is absent from the dimension it points at."""
  missing = ~df[key_column].isin(valid_keys)
  bad = int(missing.sum())

  return {
    "check": "referential_integrity",
    "severity": HARD_FAILURE,
    "passed": bad == 0,
    "detail": f"{bad} rows with {key_column} not found in {label}"
  }


def check_unique_key(df: pd.DataFrame, key_columns: list) -> dict:
  """Fail if the business key isn't unique.

  Hard failure, despite duplicates being survivable: ON CONFLICT DO NOTHING
  would absorb them without corrupting the warehouse, but the loaded count
  would then silently disagree with the extracted count — exactly the gap the
  STEP 3 reconciliation exists to make impossible.
  """
  bad = int(df.duplicated(subset=key_columns).sum())
  return {
    "check": "unique_key",
    "severity": HARD_FAILURE,
    "passed": bad == 0,
    "detail": f"{bad} duplicate row(s) on {tuple(key_columns)}"
  }


def check_null_rate(df: pd.DataFrame, column: str, max_null_pct: float) -> dict:
  """Warn when a nullable measure is emptier than expected.

  A WARNING, not a hard failure, and the distinction is real rather than
  decorative. Both nullable measures on fact_reviews are legitimately null in
  bulk: is_recommended is unanswered on ~15% of reviews, and helpfulness is
  undefined (never imputed — D5) wherever total_feedback_count = 0. Neither
  blocks a load and neither is wrong.

  What this catches is a SHIFT — if is_recommended suddenly arrives 90% null,
  the source or the transform changed, and that is worth seeing in the logs
  before it quietly flattens a dashboard number. Failing the run over it would
  be wrong; saying nothing would be worse.
  """
  if df.empty:
    null_pct = 0.0
  else:
    null_pct = float(df[column].isna().sum()) / len(df) * 100

  return {
    "check": "null_rate",
    "severity": WARNING,
    "passed": null_pct <= max_null_pct,
    "detail": f"{column}: {null_pct:.2f}% null (expected <= {max_null_pct:.2f}%)"
  }


def run_quality_checks(df: pd.DataFrame, table_name: str,
                       key_columns: list = None,
                       non_negative_columns: list = None,
                       unique_columns: list = None,
                       rating_column: str = None,
                       null_rate_checks: list = None) -> dict:
  """Run the applicable checks for one table.

  Raises DataQualityError on the first HARD FAILURE. Warnings are logged and
  do not stop the pipeline.

  null_rate_checks is a list of (column, max_null_pct) tuples.

  An empty frame skips the gate rather than failing it — an incremental run
  with nothing new is a valid outcome, not a fault.
  """
  if df.empty:
    logger.info(f"No rows to check for {table_name} — skipping quality gate")
    return {"passed": True, "checks": [], "warnings": [], "row_count": 0}

  checks = [check_row_count(df)]

  if key_columns:
    checks.append(check_no_null_keys(df, key_columns))

  if non_negative_columns:
    checks.append(check_no_negative_values(df, non_negative_columns))

  if unique_columns:
    checks.append(check_unique_key(df, unique_columns))

  if rating_column:
    checks.append(check_value_range(df, rating_column, 1, 5))

  for column, max_null_pct in (null_rate_checks or []):
    checks.append(check_null_rate(df, column, max_null_pct))

  failed = [c for c in checks if not c["passed"]]
  hard_failures = [c for c in failed if c["severity"] == HARD_FAILURE]
  warnings = [c for c in failed if c["severity"] == WARNING]

  # Warnings are logged BEFORE the hard-failure raise, so a run that dies on a
  # hard failure still leaves its warnings in the log rather than losing them.
  for w in warnings:
    logger.warning(f"Quality warning on {table_name}: {w['check']} — {w['detail']}")

  if hard_failures:
    first = hard_failures[0]
    raise DataQualityError(
      f"Quality check failed on {table_name}: {first['check']} — {first['detail']}"
    )

  summary = {
    "passed": True,
    "checks": checks,
    "warnings": warnings,
    "row_count": len(df)
  }

  logger.info(f"Quality gate passed for {table_name}: {len(df):,} rows, "
              f"{len(checks)} checks, {len(warnings)} warning(s)")
  for c in checks:
    status = "ok" if c["passed"] else f"WARN[{c['severity']}]"
    logger.info(f"  {c['check']}: {c['detail']} [{status}]")

  return summary
