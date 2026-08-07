# 06 — Airflow Runbook

Airflow **3.3.0**, LocalExecutor, Docker Compose. One DAG:
`sephora_dw_pipeline_staged`, **16 tasks**.

---

## Starting and stopping

```powershell
# start (Postgres must already be up)
docker compose up -d
docker compose -f docker-compose-airflow.yml up -d

# or, as part of the full setup path
.\setup.ps1 -Step 9

# stop, keeping the metadata database
docker compose -f docker-compose-airflow.yml down

# logs
docker compose -f docker-compose-airflow.yml logs -f airflow_scheduler
```

**UI: <http://localhost:8081>** (8080 belongs to an unrelated stack on the
original machine).

### Connections

There are none to create by hand. `docker-compose-airflow.yml` builds
`AIRFLOW_CONN_SEPHORA_OLTP` and `AIRFLOW_CONN_SEPHORA_DW` from the values in
`.env`, so they exist as environment variables and survive
`docker compose down`.

They point at **`postgres:5432`**, not `localhost:5434`. Both compose files
share `name: leapfrog-sephora`, so Airflow and Postgres sit on one Docker
network and Airflow reaches the database by *service name* on its *internal*
port. From inside the scheduler container, `localhost:5434` is the scheduler.

Verify:

```powershell
docker exec leapfrog_airflow_scheduler python -c "from airflow.models import DagBag; d=DagBag('/opt/airflow/dags'); print(d.import_errors or 'no import errors')"
```

---

## Triggering a run

In the UI: **DAGs → `sephora_dw_pipeline_staged` → Trigger** → set
**`load_mode`** in the config form. It is an enum, so it renders as a dropdown:

| `load_mode` | Loads | Use when |
|---|---|---|
| `full` | every review, no date bound | Building or rebuilding for real |
| `historical` | reviews before 2023-01-01 (1,043,868) | **Demo step 1** |
| `incremental` | reviews after the watermark | **Demo step 2**, and normal operation |

Default is `incremental` — the cheap, safe option.

### The demo sequence

```
1. Trigger with load_mode = historical    -> 1,043,868 rows, watermark ends 2022-12-31
2. Trigger with load_mode = incremental   -> 49,503 rows,   watermark ends 2023-03-21
3. Trigger with load_mode = incremental   -> 0 rows extracted, gate skipped, 0 inserted
```

Run 3 is worth showing: it proves the watermark stops the pipeline doing work
that has already been done, and that an empty batch is a clean no-op rather
than a failure.

**To reset for a rehearsal** (destroys the warehouse fact data, keeps the OLTP
side):

```powershell
docker exec leapfrog_sephora_postgres psql -U postgres -d sephora_dw -c "TRUNCATE dw.fact_reviews RESTART IDENTITY;"
```

Dimensions can stay — they reload in full every run and `ON CONFLICT` makes
that a no-op.

---

## Task graph

```
                       create_staging_tables
                                │
        ┌───────────────┬───────┴───────┬────────────────┬──────────────────┐
        ▼               ▼               ▼                ▼                  ▼
 extract_brand   extract_customer  extract_reviewer  load_date_       extract_fact
  _to_staging      _to_staging      _profile_to_       dimension        _to_staging
        │               │            staging               │                │
        ▼               ▼               ▼                  │                ▼
  load_brand      load_customer   load_reviewer_           │        transform_fact
  _from_staging   _from_staging   profile_from_            │            _staged
        │               │            staging               │                │
        ▼               │               │                  │                ▼
 extract_product        │               │                  │        quality_check
  _to_staging           │               │                  │         _fact_staged
        │               │               │                  │                │
        ▼               │               │                  │                ▼
  load_product          │               │                  │        load_fact
  _from_staging         │               │                  │        _from_staging
        │               │               │                  │                │
        └───────────────┴───────────────┴──────────────────┘                │
                                │                                           │
                                └──────────► transform_fact_staged ◄────────┘
                                                     │
                                             cleanup_staging  (all_done)
                                                     │
                                            watch_for_failure (one_failed)
```

Three dimension branches run in **parallel**. `dim_product` waits on
`dim_brand` because it resolves `brand_key`. `transform_fact_staged` waits on
every dimension because it needs all their keys.

### Why staged extract/load pairs

Each pair is independently retryable, a load failure doesn't re-hit the OLTP
source, and the Graph view names the stage that failed instead of showing one
red box. No row-level data crosses task boundaries via XCom — XCom is metadata
storage, and 503,216 customer rows through it would be an abuse of the metadata
database. Intermediate results go to `dw.stg_*` tables scoped by
`batch_id = run_id`.

A **retry** re-uses the same `run_id`, so `stage_rows` deletes that batch's rows
before re-staging. Without that, a retry after a partial write would silently
double everything the first attempt managed to stage.

---

## Reading a failed run

### `watch_for_failure` is red

That is the watcher doing its job. **The real failure is elsewhere** — look for
the other red task in the Graph view. The watcher's own log says only that
something upstream failed.

### `quality_check_fact_staged` failed

Bad data reached the gate. The log names the check and the detail:

```
Quality check failed on fact_reviews: value_range — rating: 3 value(s) outside [1, 5]
```

It raises `AirflowFailException`, so it **fails immediately without retrying** —
bad data will not become good on a second attempt, and burning the retry budget
would just delay the diagnosis by ten minutes. Fix the source or the transform;
do not clear and re-run hoping.

### A task failed with `ReconciliationError`

Rows went missing through a path nobody declared. The message gives the
arithmetic:

```
fact_reviews: row counts do not balance. extracted=100, transformed=90,
dropped=5 (accounted=95), UNEXPLAINED=5.
```

This means `transform.py` lost rows outside its counted drop reasons — a real
bug, not a data problem.

### `load_fact_from_staging` was killed

If the task dies without a Python traceback, check for SIGKILL (exit 137) — the
container hit its memory limit. This happened on the first full-reload run and
is why the task reads in 100,000-row chunks over a server-side cursor (**D15**).
If it recurs, lower `CHUNK_SIZE` in the DAG file or raise the container's memory.

### Staging tables have rows in them

They shouldn't between runs. `cleanup_staging` runs with `trigger_rule="all_done"`
so even a failed run cleans up. To check:

```sql
SELECT 'stg_fact_extract' t, count(*) FROM dw.stg_fact_extract
UNION ALL SELECT 'stg_fact_transformed', count(*) FROM dw.stg_fact_transformed
UNION ALL SELECT 'stg_dim_product', count(*) FROM dw.stg_dim_product
UNION ALL SELECT 'stg_dim_brand', count(*) FROM dw.stg_dim_brand
UNION ALL SELECT 'stg_dim_customer', count(*) FROM dw.stg_dim_customer
UNION ALL SELECT 'stg_dim_reviewer_profile', count(*) FROM dw.stg_dim_reviewer_profile;
```

All six should be 0. Rows left behind mean a run was killed hard enough that
even `all_done` didn't fire; deleting by `batch_id` is safe.

---

## The failure watcher

`cleanup_staging` must run after a failure, so it uses `trigger_rule="all_done"`.
That made it the DAG's only **leaf** task — and Airflow derives a DAG run's
state from its leaves. The result was a trap:

> extract fails → cleanup still runs → cleanup succeeds → the only leaf is
> green → **the DAG run reports SUCCESS** with an empty warehouse.

A green run that loaded nothing is worse than a red one, because nobody
investigates it.

`watch_for_failure` fixes this. It carries `trigger_rule="one_failed"` and every
other task is wired upstream of it:

| Scenario | Rule satisfied? | Watcher | DAG run |
|---|---|---|---|
| Any task failed | yes | **runs → raises** | **FAILED** |
| Nothing failed | no | **skipped** | SUCCESS |

A skipped leaf does not fail a run, so clean runs stay green. `retries=0`:
retrying a task whose only job is to report an existing failure would just
delay the red status.

The upstream list is built from task **objects**, not typed-out names, because
`one_failed` evaluates *direct* upstreams only — a task missing from that list
is a failure the watcher cannot see.
`tests/test_dag_structure.py::test_watcher_watches_every_other_task` asserts it.

---

## Retry policy

`retries=2`, `retry_delay=5 minutes`, set in `default_args` — with two
deliberate exceptions:

| Task | Retries | Why |
|---|---|---|
| `watch_for_failure` | 0 | Reports an existing failure; retrying delays the truth |
| `quality_check_fact_staged` | 2 configured, but raises `AirflowFailException` | Fails fast — bad data won't pass on retry |

Retries are worth having on the extract and load tasks, where a dropped
connection or a transient lock is plausible.

---

## Verifying DAG structure

Two versions of the same 11 assertions exist, because neither alone is enough.

**Locally** — `pytest`, but it **skips**, since Airflow isn't in the host venv:

```powershell
py -m pytest tests/test_dag_structure.py -q
# SKIPPED [1] apache-airflow not installed locally
```

**In the container** — where Airflow actually is, and therefore where the
result means something. `pytest` is *not* installed in the `apache/airflow`
image and cannot be added without root, so this version uses plain Python:

```powershell
docker cp tests/verify_dag_in_container.py leapfrog_airflow_scheduler:/tmp/
docker exec leapfrog_airflow_scheduler python /tmp/verify_dag_in_container.py
```

```
PASS  dag imports without errors
PASS  expected_tasks_present  (16 tasks)
PASS  watcher_uses_one_failed
PASS  watcher_does_not_retry
PASS  watcher_is_the_only_leaf  ({'watch_for_failure'})
PASS  watcher_watches_every_other_task  (15 upstreams)
PASS  cleanup_runs_even_after_failure  (all_done)
PASS  cleanup_precedes_watcher
PASS  retry_policy  (retries=2, delay=0:05:00)
PASS  load_mode_param_offers_three_modes
PASS  fact_is_split_into_four_stages
PASS  product_waits_for_brand

11 passed, 0 failed        # exit code 0
```

Verified on 2026-08-08 against the running scheduler.

`tests/` is also mounted at `/opt/airflow/project/tests` in
`docker-compose-airflow.yml`, so after the next `docker compose up` the
`docker cp` step becomes unnecessary. Until the containers are recreated, use
the copy.

> A test that only ever skips proves nothing. That is the entire reason the
> second file exists — the pytest version is unrunnable in precisely the
> environment whose wiring it is asserting.
