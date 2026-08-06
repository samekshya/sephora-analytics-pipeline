"""
quality.py
----------
Quality gate — runs structural/referential checks on transformed DataFrames
BEFORE load. Raises DataQualityError to halt the pipeline on failure; logs a
summary when all checks pass.

This is a gate, not a fixer. A check that quietly repairs what it finds makes
itself unfalsifiable — it can never fail, so it can never tell you anything.
Cleaning belongs in clean.py, where it is logged and counted.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


class DataQualityError(Exception):
  """Raised when a data quality check fails. Halts the pipeline."""
  pass


def check_row_count(df: pd.DataFrame, min_rows: int = 1) -> dict:
  count = len(df)
  return {
      "check": "row_count",
      "passed": count >= min_rows,
      "detail": f"{count} rows (min: {min_rows})"
  }


def check_no_null_keys(df: pd.DataFrame, key_columns: list) -> dict:
  """Fail if any surrogate key column contains nulls.

  A null FK means a merge in transform.py didn't resolve and _drop_unmatched
  missed it — the row would violate NOT NULL at load time, but failing here
  names the column instead of surfacing a constraint error.
  """
  details = []
  total_bad = 0

  for col in key_columns:
    bad = int(df[col].isna().sum())
    total_bad += bad
    details.append(f"{col}: {bad} nulls")

  return {
    "check": "no_null_keys",
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
    "passed": bad == 0,
    "detail": f"{bad} rows with {key_column} not found in {label}"
  }


def check_unique_key(df: pd.DataFrame, key_columns: list) -> dict:
  """Fail if the business key isn't unique.

  Duplicates here wouldn't corrupt the warehouse — ON CONFLICT DO NOTHING would
  absorb them — but they would mean the loaded count silently disagrees with the
  extracted count, which is exactly the kind of gap the reconciliation is
  supposed to make visible.
  """
  bad = int(df.duplicated(subset=key_columns).sum())
  return {
    "check": "unique_key",
    "passed": bad == 0,
    "detail": f"{bad} duplicate row(s) on {tuple(key_columns)}"
  }


def run_quality_checks(df: pd.DataFrame, table_name: str,
                       key_columns: list = None,
                       non_negative_columns: list = None,
                       unique_columns: list = None,
                       rating_column: str = None) -> dict:
  """Run the applicable checks for one table. Raises on the first failure.

  An empty frame skips the gate rather than failing it — an incremental run with
  nothing new is a valid outcome, not a fault.
  """
  if df.empty:
    logger.info(f"No rows to check for {table_name} — skipping quality gate")
    return {"passed": True, "checks": [], "row_count": 0}

  checks = [check_row_count(df)]

  if key_columns:
    checks.append(check_no_null_keys(df, key_columns))

  if non_negative_columns:
    checks.append(check_no_negative_values(df, non_negative_columns))

  if unique_columns:
    checks.append(check_unique_key(df, unique_columns))

  if rating_column:
    checks.append(check_value_range(df, rating_column, 1, 5))

  failed = [c for c in checks if not c["passed"]]
  if failed:
    first = failed[0]
    raise DataQualityError(
      f"Quality check failed on {table_name}: {first['check']} — {first['detail']}"
    )

  summary = {
    "passed": True,
    "checks": checks,
    "row_count": len(df)
  }

  logger.info(f"Quality gate passed for {table_name}: {len(df):,} rows, "
              f"{len(checks)} checks")
  for c in checks:
    logger.info(f"  {c['check']}: {c['detail']}")

  return summary
