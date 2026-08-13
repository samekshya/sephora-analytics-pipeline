# 06 — Airflow Runbook

Airflow **3.3.0**, LocalExecutor, Docker Compose. One DAG:
`sephora_dw_pipeline_staged`, **15 tasks**.

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
| `incremental` | reviews after the watermark | **The demo**, and normal operation |

Default is `incremental` — the cheap, safe option.

> **`historical` is not in the dropdown.** It is a third mode in
> `etl.extract.LOAD_MODES`, but it is a *baseline-rebuild tool*, not something
> you orchestrate: it loads reviews before 2023-01-01 and holds the rest back so
> an incremental run afterwards has real data to pick up. Triggered against a
> warehouse that is already full — which is the state it is usually in — it
> inserts nothing and looks like a broken run. Run it locally instead, with
> `py scripts/pipeline.py --mode historical`. The DAG exposes only
> `TRIGGERABLE_LOAD_MODES`.

### The demo sequence

Set the baseline **before** you open Airflow, from a terminal:

```powershell
py scripts/pipeline.py --mode historical    # -> 1,043,868 rows, watermark ends 2022-12-31
```

Then, in the UI:

```
1. Trigger with load_mode = incremental   -> 49,503 rows, watermark ends 2023-03-21
2. Trigger with load_mode = incremental   -> 0 rows extracted, gate skipped, 0 inserted
```

Run 2 is worth showing: it proves the watermark stops the pipeline doing work
that has already been done, and that an empty batch is a clean no-op rather
than a failure.

**To reset for a rehearsal**, remove only the 2023 slice — this is what the
`historical` baseline amounts to, and it is faster than reloading a million rows:

```powershell
docker exec leapfrog_sephora_postgres psql -U postgres -d sephora_dw -c "DELETE FROM dw.fact_reviews WHERE submission_date >= '2023-01-01';"
```

To start the fact table from empty instead:

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
                                    cleanup_staging  (teardown, all_done)
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

### The run is red but no task shows `failed`

Look for **`upstream_failed`** (orange), not `failed` (red). The run's state comes
from `load_fact_from_staging`, which inherits `upstream_failed` from whatever
actually broke. Walk back up the chain to the one genuinely red task.

### `cleanup_staging` is green on a failed run

That is correct and intended. Cleanup is a **teardown** task: it runs after a
failure so staging rows are not stranded, and it is excluded from the run's state
calculation so its success cannot mask the failure (**D24**).

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

## Why a failed run reports failed

`cleanup_staging` must run after a failure, so it uses `trigger_rule="all_done"`.
That made it the DAG's last **leaf** task — and Airflow derives a DAG run's
state from its leaves. The result was a trap:

> extract fails → cleanup still runs → cleanup succeeds → the only leaf is
> green → **the DAG run reports SUCCESS** with an empty warehouse.

A green run that loaded nothing is worse than a red one, because nobody
investigates it.

Marking cleanup `.as_teardown()` fixes this. Airflow excludes ignorable teardowns
when deciding which tasks count toward run state, so the leaf becomes
`load_fact_from_staging`:

| Scenario | Effective leaf state | DAG run |
|---|---|---|
| Any task failed | `upstream_failed` propagates to `load_fact_from_staging` | **FAILED** |
| Nothing failed | `success` | SUCCESS |

Cleanup still runs in both cases; it simply no longer speaks for the run.

> **Do not set `on_failure_fail_dagrun=True`.** It makes cleanup non-ignorable,
> which makes it the sole effective leaf again and reinstates the exact bug above.
> `test_cleanup_does_not_fail_the_dagrun` pins it to `False`.

This replaced a `watch_for_failure` watcher task that had to be wired downstream
of all 15 other tasks — 15 of the DAG's 33 edges existed only for failure
reporting. Same guarantee, **15 tasks and 21 edges** instead of 16 and 33 (**D24**,
superseding D20).

Cleanup waits on every staging **writer**, not just the fact chain, because a
short-circuiting fact chain otherwise lets it run while the dimension branches are
still staging — which stranded 513,606 rows in testing. See D24.

---

## Retry policy

`retries=2`, `retry_delay=5 minutes`, set in `default_args` — with two
deliberate exceptions:

| Task | Retries | Why |
|---|---|---|
| `quality_check_fact_staged` | 2 configured, but raises `AirflowFailException` | Fails fast — bad data won't pass on retry |

Retries are worth having on the extract and load tasks, where a dropped
connection or a transient lock is plausible.

> Note that `retries=2, retry_delay=5m` means a genuinely failing extract takes
> **~11 minutes** to reach its final state. A run that looks stuck on a red-ish
> task is usually just waiting out a retry delay.

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
PASS  expected_tasks_present  (15 tasks; missing=set(), unexpected=set())
PASS  cleanup_runs_even_after_failure  (all_done_setup_success)
PASS  cleanup_is_a_teardown
PASS  cleanup_does_not_fail_the_dagrun  (True would make cleanup the sole effective leaf again)
PASS  cleanup_cannot_speak_for_the_run  ({'load_fact_from_staging'})
PASS  every_task_can_fail_the_run  (set())
PASS  cleanup_waits_for_every_staging_writer  (4 upstreams)
PASS  retry_policy  (retries=2, delay=0:05:00)
PASS  load_mode_param_offers_two_triggerable_modes  (default=incremental, enum=['full', 'incremental'])
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
