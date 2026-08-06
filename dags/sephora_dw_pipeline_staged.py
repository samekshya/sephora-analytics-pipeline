"""
sephora_dw_pipeline_staged.py
-----------------------------
Orchestrates the etl/ package: sephora_oltp (staging schema) -> sephora_dw.

Same functions pipeline.py calls, arranged as retryable tasks:

  create_staging_tables
        |
        +--> extract_brand -> load_brand -----+---> extract_product -> load_product --+
        |                                     |                                       |
        +--> extract_customer -> load_customer +--------------------------------------+
        |                                     |                                       |
        +--> extract_profile -> load_profile -+                                       |
        |                                                                             |
        +--> load_dim_date -----------------------------------------------------------+
        |                                                                             |
        +--> extract_fact_to_staging --> transform_fact --> quality_fact --> load_fact
                                                                                  |
                                                                            cleanup_staging

Three dimension branches run in parallel. product waits on brand because of the
FK; the fact transform waits on all of them because it needs their keys.

Why staged rather than one task per dimension: each extract/load pair is
independently retryable, a load failure doesn't re-hit OLTP, and the Graph view
names the stage that failed instead of showing one red box.

The watermark is captured in extract_fact_to_staging, BEFORE this run writes
anything to fact_reviews, and travels forward as a single small XCom. Re-reading
it later in the run would read a value the same run had already advanced.
"""

from datetime import datetime, timedelta

import logging
import time

from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from airflow.sdk import dag, task, Param
from airflow.sdk.exceptions import AirflowFailException

from etl.extract import (
    extract_brands, extract_products, extract_customers,
    extract_reviewer_profiles, extract_date_bounds,
    extract_reviews_full, extract_reviews_incremental,
    extract_lookup_dim, extract_brand_lookup, get_watermark,
)
from etl.transform import (
    build_dim_brand, build_dim_product, build_dim_customer,
    build_dim_reviewer_profile, build_fact_reviews, FACT_COLUMNS,
)
from etl.load import (
    load_dim_brand, load_dim_product, load_dim_customer,
    load_dim_reviewer_profile, load_dim_date, load_fact_reviews,
)
from etl.quality import run_quality_checks, DataQualityError
from etl.staging import (
    STAGING_TABLES_SQL,
    stage_rows,
    read_staged_rows,
    iter_staged_rows,
    cleanup_staging_rows,
)

# Rows held in memory at once by the chunked fact tasks. The containerised task
# worker was SIGKILLed loading 1,043,868 rows in one pass; this caps peak memory
# independently of batch size.
CHUNK_SIZE = 100_000

logger = logging.getLogger(__name__)

SRC_CONN_ID = "sephora_oltp"
DEST_CONN_ID = "sephora_dw"

# The three dimensions with no dependency on another dimension. Generated from
# config rather than hand-copied three times, so they cannot drift apart; each
# still gets its own distinct, independently retryable task_id in the UI.
DIM_CONFIGS = [
    {
        "key": "brand",
        "staging_table": "dw.stg_dim_brand",
        "columns": ["brand_id", "brand_name"],
        "extract_fn": extract_brands,
        "build_fn": build_dim_brand,
        "load_fn": load_dim_brand,
    },
    {
        "key": "customer",
        "staging_table": "dw.stg_dim_customer",
        "columns": ["customer_id"],
        "extract_fn": extract_customers,
        "build_fn": build_dim_customer,
        "load_fn": load_dim_customer,
    },
    {
        "key": "reviewer_profile",
        "staging_table": "dw.stg_dim_reviewer_profile",
        "columns": ["skin_tone", "skin_type", "eye_color", "hair_color"],
        "extract_fn": extract_reviewer_profiles,
        "build_fn": build_dim_reviewer_profile,
        "load_fn": load_dim_reviewer_profile,
    },
]

# Raw review columns as returned by extract_reviews_full/incremental - must
# match stg_fact_extract's DDL in etl/staging.py.
FACT_EXTRACT_COLUMNS = [
    "source_row_id", "product_id", "author_id", "submission_date", "rating",
    "is_recommended", "helpfulness", "total_feedback_count",
    "total_pos_feedback_count", "total_neg_feedback_count", "review_length",
    "skin_tone", "skin_type", "eye_color", "hair_color",
]

# Reuse transform.py's own constant so this cannot drift out of sync with
# build_fact_reviews.
FACT_TRANSFORMED_COLUMNS = FACT_COLUMNS

DIM_PRODUCT_COLUMNS = [
    "product_id", "product_name", "brand_key",
    "primary_category", "secondary_category", "tertiary_category",
    "price_usd", "price_band", "size", "loves_count",
    "limited_edition", "new", "online_only", "out_of_stock", "sephora_exclusive",
]


@dag(
    dag_id="sephora_dw_pipeline_staged",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
    },
    tags=["sephora", "dw", "staging-pattern"],
    params={
        "full_reload": Param(
            False,
            type="boolean",
            description="Run full historical load instead of incremental"
        )
    },
)
def sephora_dw_pipeline_staged():

    create_staging_tables = SQLExecuteQueryOperator(
        task_id="create_staging_tables",
        conn_id=DEST_CONN_ID,
        sql=STAGING_TABLES_SQL,
    )

    def make_dim_staging_tasks(cfg):
        """Build the extract-to-staging / load-from-staging pair for one dimension.

        A function call rather than a bare loop body so each pair closes over its
        own cfg - avoids the late-binding closure bug with loop variables in
        nested functions.
        """
        staging_table = cfg["staging_table"]
        columns = cfg["columns"]
        extract_fn = cfg["extract_fn"]
        build_fn = cfg["build_fn"]
        load_fn = cfg["load_fn"]

        @task(task_id=f"extract_{cfg['key']}_to_staging")
        def extract_dim_to_staging(**context):
            batch_id = context["run_id"]
            src_conn = PostgresHook(postgres_conn_id=SRC_CONN_ID).get_conn()
            dst_conn = PostgresHook(postgres_conn_id=DEST_CONN_ID).get_conn()
            try:
                t0 = time.time()
                raw_df = extract_fn(src_conn)
                dim_df = build_fn(raw_df)
                stage_rows(dst_conn, staging_table, columns, dim_df, batch_id)
                logger.info(f"{cfg['key']} staged in {time.time() - t0:.2f}s")
            finally:
                src_conn.close()
                dst_conn.close()

        @task(task_id=f"load_{cfg['key']}_from_staging")
        def load_dim_from_staging(**context):
            batch_id = context["run_id"]
            dst_conn = PostgresHook(postgres_conn_id=DEST_CONN_ID).get_conn()
            try:
                t0 = time.time()
                df = read_staged_rows(dst_conn, staging_table, columns, batch_id)
                load_fn(dst_conn, df)
                logger.info(f"{cfg['key']} loaded from staging in "
                            f"{time.time() - t0:.2f}s")
            finally:
                dst_conn.close()

        extract_task = extract_dim_to_staging()
        load_task = load_dim_from_staging()
        create_staging_tables >> extract_task >> load_task
        return load_task

    dim_load_tasks = {cfg["key"]: make_dim_staging_tasks(cfg) for cfg in DIM_CONFIGS}

    # --- dim_product: its own pair, because it depends on dim_brand ---

    @task
    def extract_product_to_staging(**context):
        """Needs brand keys, so it runs after load_brand_from_staging."""
        batch_id = context["run_id"]
        src_conn = PostgresHook(postgres_conn_id=SRC_CONN_ID).get_conn()
        dst_conn = PostgresHook(postgres_conn_id=DEST_CONN_ID).get_conn()
        try:
            t0 = time.time()
            brand_lookup = extract_brand_lookup(dst_conn)
            raw_df = extract_products(src_conn)
            product_df = build_dim_product(raw_df, brand_lookup)
            stage_rows(dst_conn, "dw.stg_dim_product", DIM_PRODUCT_COLUMNS,
                       product_df, batch_id)
            logger.info(f"product staged in {time.time() - t0:.2f}s")
        finally:
            src_conn.close()
            dst_conn.close()

    @task
    def load_product_from_staging(**context):
        batch_id = context["run_id"]
        dst_conn = PostgresHook(postgres_conn_id=DEST_CONN_ID).get_conn()
        try:
            df = read_staged_rows(dst_conn, "dw.stg_dim_product",
                                  DIM_PRODUCT_COLUMNS, batch_id)
            run_quality_checks(
                df, 'dim_product',
                key_columns=['brand_key'],
                non_negative_columns=['price_usd', 'loves_count'],
                unique_columns=['product_id'],
            )
            load_dim_product(dst_conn, df)
        finally:
            dst_conn.close()

    # --- dim_date: no source table, generated from the OLTP date range ---

    @task
    def load_date_dimension():
        """Range derived from the data, not hardcoded (D12)."""
        src_conn = PostgresHook(postgres_conn_id=SRC_CONN_ID).get_conn()
        dst_conn = PostgresHook(postgres_conn_id=DEST_CONN_ID).get_conn()
        try:
            start_date, end_date = extract_date_bounds(src_conn)
            load_dim_date(dst_conn, start_date, end_date)
        finally:
            src_conn.close()
            dst_conn.close()

    # --- fact: 4 staged tasks (extract / transform / quality / load) ---

    @task
    def extract_fact_to_staging(**context):
        """Captures the watermark BEFORE any write happens this run, extracts the
        review batch, stages it, and returns {watermark, full_reload} as a small
        XCom consumed by nothing else - the value is recorded so the run's own
        logs show which watermark it used."""
        batch_id = context["run_id"]
        full_reload = context["params"]["full_reload"]
        mode = "FULL" if full_reload else "INCREMENTAL"
        logger.info(f"Extracting fact in {mode} mode")

        oltp_conn = PostgresHook(postgres_conn_id=SRC_CONN_ID).get_conn()
        dw_conn = PostgresHook(postgres_conn_id=DEST_CONN_ID).get_conn()
        try:
            t0 = time.time()
            watermark = None
            if full_reload:
                df = extract_reviews_full(oltp_conn)
            else:
                watermark = get_watermark(dw_conn)
                df = extract_reviews_incremental(oltp_conn, watermark)

            stage_rows(dw_conn, "dw.stg_fact_extract", FACT_EXTRACT_COLUMNS,
                       df, batch_id)
            logger.info(f"Fact extract staged in {time.time() - t0:.2f}s")

            return {
                "watermark": str(watermark) if watermark else None,
                "full_reload": full_reload,
                "rows_extracted": len(df),
            }
        except Exception:
            logger.exception("Fact extract failed")
            raise
        finally:
            oltp_conn.close()
            dw_conn.close()

    @task
    def transform_fact_staged(extract_context, **context):
        batch_id = context["run_id"]
        dw_conn = PostgresHook(postgres_conn_id=DEST_CONN_ID).get_conn()
        try:
            t0 = time.time()
            raw_df = read_staged_rows(dw_conn, "dw.stg_fact_extract",
                                      FACT_EXTRACT_COLUMNS, batch_id)
            lookups = extract_lookup_dim(dw_conn)
            fact_df = build_fact_reviews(raw_df, lookups)
            stage_rows(dw_conn, "dw.stg_fact_transformed",
                       FACT_TRANSFORMED_COLUMNS, fact_df, batch_id)
            logger.info(f"Fact transform staged in {time.time() - t0:.2f}s")
        except Exception:
            logger.exception("Fact transform failed")
            raise
        finally:
            dw_conn.close()

    @task
    def quality_check_fact_staged(**context):
        batch_id = context["run_id"]
        dw_conn = PostgresHook(postgres_conn_id=DEST_CONN_ID).get_conn()
        try:
            fact_df = read_staged_rows(dw_conn, "dw.stg_fact_transformed",
                                       FACT_TRANSFORMED_COLUMNS, batch_id)
        finally:
            dw_conn.close()

        try:
            run_quality_checks(
                fact_df, 'fact_reviews',
                key_columns=['product_key', 'customer_key',
                             'reviewer_profile_key', 'date_key'],
                non_negative_columns=['total_feedback_count',
                                      'total_pos_feedback_count',
                                      'total_neg_feedback_count'],
                unique_columns=['source_row_id', 'product_id'],
                rating_column='rating',
            )
        except DataQualityError as e:
            # Bad data will not pass on retry - fail fast instead of burning the
            # DAG's 2-retry budget on a non-transient error.
            raise AirflowFailException(str(e)) from e

    @task
    def load_fact_from_staging(**context):
        """Loads in chunks rather than one pass.

        The first full-reload run SIGKILLed here: reading 1,043,868 rows as one
        DataFrame and then building a list of tuples from it meant two full
        copies resident at once. Chunking caps peak memory at CHUNK_SIZE rows
        regardless of how large the batch is, which is what makes this task
        survive a full reload as well as an incremental one.

        Two connections: the read side holds a server-side cursor open for the
        whole iteration, so the write side has to commit on its own connection.
        """
        batch_id = context["run_id"]
        read_conn = PostgresHook(postgres_conn_id=DEST_CONN_ID).get_conn()
        write_conn = PostgresHook(postgres_conn_id=DEST_CONN_ID).get_conn()
        try:
            t0 = time.time()
            total = 0
            for chunk in iter_staged_rows(read_conn, "dw.stg_fact_transformed",
                                          FACT_TRANSFORMED_COLUMNS, batch_id,
                                          chunk_size=CHUNK_SIZE):
                total += load_fact_reviews(write_conn, chunk)
            logger.info(f"Fact loaded from staging in {time.time() - t0:.2f}s "
                        f"({total} rows inserted)")
        except Exception:
            logger.exception("Fact load failed")
            raise
        finally:
            read_conn.close()
            write_conn.close()

    @task(trigger_rule="all_done")
    def cleanup_staging(**context):
        """all_done, not all_success: a failed run must still clean up after
        itself, or its rows sit in the staging tables forever."""
        batch_id = context["run_id"]
        dst_conn = PostgresHook(postgres_conn_id=DEST_CONN_ID).get_conn()
        try:
            cleanup_staging_rows(dst_conn, batch_id)
        finally:
            dst_conn.close()

    # --- wiring ---

    extract_product = extract_product_to_staging()
    load_product = load_product_from_staging()
    dim_load_tasks["brand"] >> extract_product >> load_product

    date_task = load_date_dimension()
    create_staging_tables >> date_task

    extract_fact = extract_fact_to_staging()
    create_staging_tables >> extract_fact

    transform_fact = transform_fact_staged(extract_fact)
    quality_fact = quality_check_fact_staged()
    load_fact_task = load_fact_from_staging()

    # transform_fact reads every dimension's keys via extract_lookup_dim, so it
    # waits on all of them - separate from its implicit dependency on
    # extract_fact via the XCom parameter.
    [load_product, dim_load_tasks["customer"],
     dim_load_tasks["reviewer_profile"], date_task] >> transform_fact

    transform_fact >> quality_fact >> load_fact_task >> cleanup_staging()


sephora_dw_pipeline_staged()
