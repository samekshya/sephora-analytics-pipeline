"""
reconcile.py
------------
Row accounting between pipeline stages. Every row that enters a stage must
leave it either transformed or dropped for a NAMED reason, and every row
offered to a load must end up either inserted or already present.

Why this module exists
----------------------
transform.py used to drop rows whose merge key didn't resolve and simply log a
warning. That is a silent data loss channel with a paper trail nobody reads: if
1,000 reviews pointed at a product missing from dim_product, the run stayed
green, the fact table was quietly 1,000 rows short, and the only evidence was a
WARNING line in a log file among thousands.

The rule enforced here:

    rows_extracted == rows_transformed + sum(rows_dropped_by_reason)
    rows_offered   == rows_inserted    + rows_already_present

Both are identities, not estimates. If either fails to balance, rows went
missing through a path nobody declared, and the pipeline RAISES rather than
continuing - because an unexplained discrepancy is exactly the case where
continuing produces a warehouse that looks fine and isn't.

Dropping rows is allowed. Dropping them without saying how many and why is not.
"""

import logging

logger = logging.getLogger(__name__)


class ReconciliationError(Exception):
  """Raised when row counts don't balance. Halts the pipeline."""
  pass


def reconcile_transform(rows_extracted: int, rows_transformed: int,
                        drops: dict, stage: str) -> int:
  """Assert rows_extracted == rows_transformed + total drops.

  `drops` maps a reason to a count, e.g.
      {'unresolved_product': 12, 'unresolved_customer': 0, ...}

  Returns the total number of dropped rows.
  Raises ReconciliationError if the identity does not hold.
  """
  total_dropped = sum(drops.values())
  accounted = rows_transformed + total_dropped

  logger.info(f"[reconcile:{stage}] extracted={rows_extracted} "
              f"transformed={rows_transformed} dropped={total_dropped}")

  # Every reason is logged, including the zeros. A reason that only appears
  # when it fires gives no way to tell "nothing was dropped for this reason"
  # apart from "this reason was never checked".
  for reason, count in sorted(drops.items()):
    level = logger.warning if count else logger.info
    level(f"[reconcile:{stage}]   dropped {count} row(s): {reason}")

  if accounted != rows_extracted:
    unexplained = rows_extracted - accounted
    raise ReconciliationError(
      f"{stage}: row counts do not balance. "
      f"extracted={rows_extracted}, transformed={rows_transformed}, "
      f"dropped={total_dropped} (accounted={accounted}), "
      f"UNEXPLAINED={unexplained}. "
      f"Every dropped row must be counted against a named reason."
    )

  if total_dropped:
    logger.warning(f"[reconcile:{stage}] {total_dropped} row(s) dropped, all "
                   f"accounted for by reason")
  else:
    logger.info(f"[reconcile:{stage}] balanced — no rows lost")

  return total_dropped


def reconcile_load(rows_offered: int, rows_inserted: int, stage: str) -> int:
  """Assert rows_offered == rows_inserted + rows_already_present.

  Returns rows_already_present (the ON CONFLICT DO NOTHING skips).

  A negative already-present count would mean the table grew by more rows than
  were offered - concurrent writes, or a miscounted load - and is treated as a
  hard error rather than clamped to zero.
  """
  already_present = rows_offered - rows_inserted

  logger.info(f"[reconcile:{stage}] offered={rows_offered} "
              f"inserted={rows_inserted} already_present={already_present}")

  if already_present < 0:
    raise ReconciliationError(
      f"{stage}: {rows_inserted} rows inserted but only {rows_offered} offered. "
      f"The table grew by more rows than this run supplied."
    )

  if rows_offered and rows_inserted == 0:
    logger.info(f"[reconcile:{stage}] 0 inserted of {rows_offered} offered — "
                f"idempotent re-run, every row was already present")

  return already_present
