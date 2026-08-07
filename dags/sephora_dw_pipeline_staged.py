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

Load mode is chosen from the UI via the `load_mode` Param: full, historical or
incremental (see etl/extract.py for what each one means).

watch_for_failure is the DAG's only leaf task and exists so that
cleanup_staging's trigger_rule='all_done' cannot leave a failed run reporting
success. See the task's own docstring.
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
    extract_reviews_for_mode, extract_lookup_dim, extract_brand_lookup,
    get_watermark, LOAD_MODES, FULL, HISTORICAL, INCREMENTAL,
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
from etl.reconcile import reconcile_transform, reconcile_load, ReconciliationError
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
        "load_mode": Param(
            INCREMENTAL,
            type="string",
            enum=list(LOAD_MODES),
            title="Load mode",
            description=(
                "full: every review, no date bound. "
                "historical: reviews before 2023-01-01 only — the demo "
                "baseline, which deliberately holds later rows back so an "
                "incremental run afterwards has real data to pick up. "
                "incremental: only reviews after the warehouse watermark."
            ),
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
        return extract_task, load_task

    dim_task_pairs = {cfg["key"]: make_dim_staging_tasks(cfg) for cfg in DIM_CONFIGS}
    dim_load_tasks = {key: pair[1] for key, pair in dim_task_pairs.items()}

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
            product_df, drops = build_dim_product(raw_df, brand_lookup)
            reconcile_transform(len(raw_df), len(product_df), drops,
                                'dim_product')
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
        review batch, stages it, and returns {watermark, mode, rows_extracted} as a small
        XCom consumed by nothing else - the value is recorded so the run's own
        logs show which watermark it used."""
        batch_id = context["run_id"]
        mode = context["params"]["load_mode"]
        logger.info(f"Extracting fact in {mode.upper()} mode")

        oltp_conn = PostgresHook(postgres_conn_id=SRC_CONN_ID).get_conn()
        dw_conn = PostgresHook(postgres_conn_id=DEST_CONN_ID).get_conn()
        try:
            t0 = time.time()
            # Only incremental needs a watermark, and it is read BEFORE this run
            # writes anything, so it cannot advance past rows this run loads.
            watermark = get_watermark(dw_conn) if mode == INCREMENTAL else None
            df = extract_reviews_for_mode(oltp_conn, mode, watermark)

            stage_rows(dw_conn, "dw.stg_fact_extract", FACT_EXTRACT_COLUMNS,
                       df, batch_id)
            logger.info(f"Fact extract staged in {time.time() - t0:.2f}s")

            # rows_extracted travels forward so transform can reconcile against
            # it. Reading the staging table's own count there instead would just
            # be asking the same question twice and calling it a check.
            return {
                "watermark": str(watermark) if watermark else None,
                "mode": mode,
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

            # Reconcile against what EXTRACT reported, not against what we just
            # read back. If staging itself lost rows, comparing the staging
            # table to itself would never notice.
            rows_extracted = extract_context["rows_extracted"]
            if len(raw_df) != rows_extracted:
                raise ReconciliationError(
                    f"stg_fact_extract holds {len(raw_df)} rows but extract "
                    f"reported {rows_extracted} — rows lost in staging")

            lookups = extract_lookup_dim(dw_conn)
            fact_df, drops = build_fact_reviews(raw_df, lookups)
            reconcile_transform(rows_extracted, len(fact_df), drops,
                                'fact_reviews')

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
                # Warning-severity, never fatal. Both measures are legitimately
                # null in bulk (is_recommended unanswered ~15%; helpfulness
                # undefined wherever nobody voted — D5). The thresholds are set
                # above the observed rates, so they stay quiet on normal data
                # and speak up only if the source shifts.
                null_rate_checks=[('is_recommended', 30.0),
                                  ('helpfulness', 80.0)],
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
            inserted = 0
            offered = 0
            for chunk in iter_staged_rows(read_conn, "dw.stg_fact_transformed",
                                          FACT_TRANSFORMED_COLUMNS, batch_id,
                                          chunk_size=CHUNK_SIZE):
                offered += len(chunk)
                inserted += load_fact_reviews(write_conn, chunk)

            # offered == inserted + already_present, summed across chunks.
            already_present = reconcile_load(offered, inserted, 'fact_reviews')
            logger.info(f"Fact loaded from staging in {time.time() - t0:.2f}s "
                        f"({offered} offered, {inserted} inserted, "
                        f"{already_present} already present)")
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

    @task(trigger_rule="one_failed", retries=0)
    def watch_for_failure():
        """Marks the DAG RUN failed if ANY upstream task failed.

        Why this task has to exist
        --------------------------
        Airflow decides a DAG run's final state from its LEAF tasks. Before this
        task, the only leaf was cleanup_staging, which runs with
        trigger_rule='all_done' precisely so it cleans up after a failure. The
        combination is a trap: extract fails -> cleanup still runs -> cleanup
        succeeds -> the only leaf is green -> THE DAG RUN REPORTS SUCCESS even
        though the warehouse got no data. A green run that loaded nothing is
        worse than a red one, because nobody goes looking.

        How the fix works
        -----------------
        Every task in the DAG is wired upstream of this one, and it carries
        trigger_rule='one_failed', which fires as soon as at least one direct
        upstream task has failed:

          - Something failed  -> the rule is satisfied -> this task RUNS and
                                 raises -> it is a leaf, and a failed leaf makes
                                 the whole DAG run FAILED.
          - Nothing failed    -> the rule is never satisfied -> this task is
                                 SKIPPED. A skipped leaf does not fail a run, so
                                 a clean run stays green.

        retries=0 because retrying a task whose entire job is to report that
        something already failed would just delay the red status by 10 minutes.

        This is the watcher pattern from the Airflow docs, which exists for
        exactly this all_done-cleanup situation.
        """
        raise AirflowFailException(
            "Upstream task failure detected — failing the DAG run. "
            "Check the Graph view for the red task; cleanup_staging will have "
            "run regardless, so no staging rows are left behind."
        )

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

    cleanup = cleanup_staging()
    transform_fact >> quality_fact >> load_fact_task >> cleanup

    # The watcher must see EVERY task, because trigger_rule evaluates a task's
    # DIRECT upstreams only. A task missing from this list is a task whose
    # failure the watcher cannot notice, so the list is built from the task
    # objects themselves rather than typed out by hand.
    all_tasks = [create_staging_tables, extract_product, load_product,
                 date_task, extract_fact, transform_fact, quality_fact,
                 load_fact_task, cleanup]
    for extract_task, load_task in dim_task_pairs.values():
        all_tasks.extend([extract_task, load_task])

    all_tasks >> watch_for_failure()


sephora_dw_pipeline_staged()
