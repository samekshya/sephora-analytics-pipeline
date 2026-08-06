"""
staging.py
----------
Staging-table helpers for the Airflow DAG.

Each dimension gets its own staging table in sephora_dw, scoped per-run by
batch_id (the Airflow run_id), so that:
  - extract_<dim>_to_staging and load_<dim>_from_staging are independently
    retryable; a load-only failure doesn't re-hit the OLTP source.
  - No row-level data crosses task boundaries via XCom. XCom is metadata
    storage, not a data channel - 503,216 customer rows through it would be
    an abuse of the metadata database.

The tables live in the WAREHOUSE, not the OLTP database, because that is where
the loading half of each pair runs. Keeping both halves' target in one database
means neither task needs two connections.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)

STAGING_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS dw.stg_dim_brand (
    batch_id    TEXT NOT NULL,
    brand_id    INTEGER,
    brand_name  TEXT
);
CREATE INDEX IF NOT EXISTS idx_stg_dim_brand_batch ON dw.stg_dim_brand(batch_id);

CREATE TABLE IF NOT EXISTS dw.stg_dim_product (
    batch_id            TEXT NOT NULL,
    product_id          TEXT,
    product_name        TEXT,
    brand_key           INTEGER,
    primary_category    TEXT,
    secondary_category  TEXT,
    tertiary_category   TEXT,
    price_usd           NUMERIC(10,2),
    price_band          TEXT,
    size                TEXT,
    loves_count         INTEGER,
    limited_edition     BOOLEAN,
    new                 BOOLEAN,
    online_only         BOOLEAN,
    out_of_stock        BOOLEAN,
    sephora_exclusive   BOOLEAN
);
CREATE INDEX IF NOT EXISTS idx_stg_dim_product_batch ON dw.stg_dim_product(batch_id);

CREATE TABLE IF NOT EXISTS dw.stg_dim_customer (
    batch_id     TEXT NOT NULL,
    customer_id  TEXT
);
CREATE INDEX IF NOT EXISTS idx_stg_dim_customer_batch ON dw.stg_dim_customer(batch_id);

CREATE TABLE IF NOT EXISTS dw.stg_dim_reviewer_profile (
    batch_id    TEXT NOT NULL,
    skin_tone   TEXT,
    skin_type   TEXT,
    eye_color   TEXT,
    hair_color  TEXT
);
CREATE INDEX IF NOT EXISTS idx_stg_dim_reviewer_profile_batch
    ON dw.stg_dim_reviewer_profile(batch_id);

-- Reviews as extracted from OLTP (full or incremental range), before any
-- dimension key lookups have been applied.
CREATE TABLE IF NOT EXISTS dw.stg_fact_extract (
    batch_id                  TEXT NOT NULL,
    source_row_id             BIGINT,
    product_id                TEXT,
    author_id                 TEXT,
    submission_date           DATE,
    rating                    SMALLINT,
    is_recommended            BOOLEAN,
    helpfulness               NUMERIC(18,16),
    total_feedback_count      INTEGER,
    total_pos_feedback_count  INTEGER,
    total_neg_feedback_count  INTEGER,
    review_length             INTEGER,
    skin_tone                 TEXT,
    skin_type                 TEXT,
    eye_color                 TEXT,
    hair_color                TEXT
);
CREATE INDEX IF NOT EXISTS idx_stg_fact_extract_batch ON dw.stg_fact_extract(batch_id);

-- Reviews after build_fact_reviews - dimension keys resolved, ready for the
-- quality gate and then load_fact_reviews. Column set mirrors FACT_COLUMNS.
CREATE TABLE IF NOT EXISTS dw.stg_fact_transformed (
    batch_id                  TEXT NOT NULL,
    source_row_id             BIGINT,
    product_id                TEXT,
    product_key               INTEGER,
    customer_key              INTEGER,
    reviewer_profile_key      INTEGER,
    date_key                  INTEGER,
    rating                    SMALLINT,
    is_recommended            BOOLEAN,
    helpfulness               NUMERIC(18,16),
    total_feedback_count      INTEGER,
    total_pos_feedback_count  INTEGER,
    total_neg_feedback_count  INTEGER,
    review_length             INTEGER,
    submission_date           DATE
);
CREATE INDEX IF NOT EXISTS idx_stg_fact_transformed_batch
    ON dw.stg_fact_transformed(batch_id);
"""

# Every staging table this DAG owns - used by cleanup_staging_rows.
ALL_STAGING_TABLES = [
    "dw.stg_dim_brand",
    "dw.stg_dim_product",
    "dw.stg_dim_customer",
    "dw.stg_dim_reviewer_profile",
    "dw.stg_fact_extract",
    "dw.stg_fact_transformed",
]

PAGE_SIZE = 5000


def _records(df: pd.DataFrame, columns: list) -> list:
    """DataFrame -> list[tuple] restricted to `columns`, NaN/NaT -> None."""
    sub = df[columns]
    return list(sub.astype(object).where(pd.notnull(sub), None).itertuples(
        index=False, name=None))


def stage_rows(dst_conn, staging_table: str, columns: list, df: pd.DataFrame,
               batch_id: str):
    """Write df into staging_table under batch_id.

    Deletes any existing rows for this batch_id first, so a task RETRY (same
    run_id, same batch_id) replaces its previous attempt rather than doubling
    it. Without that delete, a retry after a partial write would silently
    duplicate everything the first attempt managed to stage.
    """
    from psycopg2.extras import execute_values

    col_list = ", ".join(columns)
    del_sql = f"DELETE FROM {staging_table} WHERE batch_id = %(batch_id)s"
    ins_sql = (f"INSERT INTO {staging_table} (batch_id, {col_list}) VALUES %s")

    try:
        with dst_conn.cursor() as cur:
            cur.execute(del_sql, {"batch_id": batch_id})

            if df.empty:
                logger.info(f"No rows to stage for {staging_table} (batch {batch_id})")
                dst_conn.commit()
                return 0

            records = [(batch_id,) + row for row in _records(df, columns)]
            execute_values(cur, ins_sql, records, page_size=PAGE_SIZE)

            cur.execute(
                f"SELECT count(*) FROM {staging_table} WHERE batch_id = %(batch_id)s",
                {"batch_id": batch_id})
            staged = cur.fetchone()[0]
        dst_conn.commit()
        logger.info(f"{staged} rows staged to {staging_table} (batch {batch_id})")
        return staged
    except Exception as e:
        dst_conn.rollback()
        logger.error(str(e))
        raise


def read_staged_rows(dst_conn, staging_table: str, columns: list,
                     batch_id: str) -> pd.DataFrame:
    """Read this batch's staged rows back out as a DataFrame with exactly `columns`."""
    col_list = ", ".join(columns)
    sql = f"SELECT {col_list} FROM {staging_table} WHERE batch_id = %(batch_id)s"
    df = pd.read_sql_query(sql, dst_conn, params={"batch_id": batch_id})
    logger.info(f"Read {len(df)} staged rows from {staging_table} (batch {batch_id})")
    return df


def iter_staged_rows(read_conn, staging_table: str, columns: list, batch_id: str,
                     chunk_size: int = 100_000):
    """Yield this batch's staged rows as DataFrames of at most chunk_size rows.

    Why this exists: read_staged_rows materialises the whole result, and
    _execute then builds a list of tuples on top of it. At 1,043,868 fact rows
    that is two full copies in memory at once, and the Airflow task worker was
    SIGKILLed part-way through the first full-reload run. The local runner
    survived it; the containerised worker did not.

    Uses a NAMED (server-side) cursor so Postgres streams the result instead of
    shipping all of it before the first row is available.

    IMPORTANT: pass a dedicated read connection. A named cursor holds its
    transaction open for the life of the iteration, so committing writes on the
    same connection mid-loop would invalidate it.
    """
    import re

    col_list = ", ".join(columns)
    # Cursor names are identifiers; run_ids contain colons and plus signs.
    cursor_name = "stg_" + re.sub(r'[^0-9a-zA-Z]', '_', batch_id)[:48]

    sql = f"SELECT {col_list} FROM {staging_table} WHERE batch_id = %s"
    total = 0
    with read_conn.cursor(name=cursor_name) as cur:
        cur.itersize = chunk_size
        cur.execute(sql, (batch_id,))
        while True:
            rows = cur.fetchmany(chunk_size)
            if not rows:
                break
            total += len(rows)
            logger.info(f"Read chunk of {len(rows)} from {staging_table} "
                        f"({total} so far, batch {batch_id})")
            yield pd.DataFrame(rows, columns=columns)
    logger.info(f"Read {total} staged rows from {staging_table} in chunks "
                f"(batch {batch_id})")


def cleanup_staging_rows(dst_conn, batch_id: str, staging_tables: list = None):
    """Delete this run's rows from every staging table.

    Called with trigger_rule='all_done' so it runs even when an earlier task
    failed - otherwise a failed run would leave its rows behind forever.
    """
    tables = staging_tables or ALL_STAGING_TABLES
    try:
        total = 0
        with dst_conn.cursor() as cur:
            for t in tables:
                cur.execute(f"DELETE FROM {t} WHERE batch_id = %(batch_id)s",
                            {"batch_id": batch_id})
                total += cur.rowcount
        dst_conn.commit()
        logger.info(f"Cleaned {total} staging rows for batch {batch_id} "
                    f"across {len(tables)} tables")
    except Exception as e:
        dst_conn.rollback()
        logger.error(str(e))
        raise
