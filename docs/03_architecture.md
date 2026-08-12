# 03 — Architecture

## End-to-end flow

```
 data/raw/*.csv                                    Kaggle export, 550 MB, gitignored
 ├─ product_info.csv          8,494 rows
 └─ reviews_*.csv  (x5)   1,094,411 rows
        │
        │  explore.py      profiling only — writes nothing, reads everything
        │                  (findings -> docs/02)
        │
        │  clean.py        dedup (D4), type coercion, 'Grey'->'gray',
        │                  'notSureST'->NULL, derive review_length (D6).
        ▼                  DOES NOT DROP COLUMNS (D14).
 data/processed/*.csv
 ├─ products.csv              8,494 rows      8.1 MB
 └─ reviews.csv           1,093,371 rows    546.7 MB    (1,040 dupes removed)
        │
        │  ingest.py       COPY, truncate-and-reload in ONE transaction.
        │                  Asserts loaded counts against clean.py's output.
        ▼
╔═══════════════════════════════════════════════════════════════════════════╗
║  sephora_oltp                                          Postgres 16 : 5434 ║
║                                                                           ║
║  raw schema        1:1 mirror of the CSVs + source_file. Every source      ║
║   ├ product_info   column kept, for traceability.                         ║
║   └ reviews                                                               ║
║        │  15 numbered, append-only migrations                             ║
║        ▼                                                                  ║
║  3nf schema        9 tables, every FK enforced by Postgres.               ║
║   ├ brand (304)          <- brand_name removed from product               ║
║   ├ category (174)       <- keyed on the full triple, NOT nested (D1)     ║
║   ├ product (8,494)                                                       ║
║   ├ author (503,216)     <- IDENTITY ONLY, no attributes (D2)             ║
║   ├ skin_tone (13) / skin_type (4) / eye_color (5) / hair_color (7)       ║
║   └ review (1,093,371)   <- the 4 attributes live HERE, at review grain   ║
║        │                    review_text stops here (D6)                   ║
║        ▼                                                                  ║
║  staging schema    De-normalized again, on purpose: dimension attributes  ║
║   ├ product        pre-joined so extract.py stays a plain SELECT.         ║
║   └ review         NULL -> 'Unknown' happens HERE, not in 3nf.            ║
╚═══════════════════════════════════════════════════════════════════════════╝
        │
        │  etl/  package        extract -> transform -> quality -> load
        │  ├ extract.py         3 modes: full / historical / incremental
        │  ├ transform.py       natural keys -> surrogate keys; returns
        │  │                    (DataFrame, drops-by-reason)
        │  ├ reconcile.py       extracted == transformed + dropped, or RAISE
        │  ├ quality.py         GATE, not a fixer. hard_failure halts,
        │  │                    warning logs and continues.
        │  ├ load.py            ON CONFLICT DO NOTHING everywhere
        │  └ staging.py         per-run staging tables for the DAG
        │
        │  driven by:  pipeline.py  (local, no scheduler)
        │              dags/sephora_dw_pipeline_staged.py  (Airflow 3.3)
        ▼
╔═══════════════════════════════════════════════════════════════════════════╗
║  sephora_dw                                            Postgres 16 : 5434 ║
║                                                                           ║
║  dw schema — star schema. Grain: ONE ROW PER REVIEW.                      ║
║                                                                           ║
║                        dim_brand (304)                                    ║
║                              │ brand_key                                  ║
║                              ▼                                            ║
║    dim_date  ◄──────────  dim_product (8,494)                             ║
║    (5,379)    date_key         │ product_key                              ║
║       ▲                        ▼                                          ║
║       └──────────────  fact_reviews (1,093,371)  ──────────┐              ║
║                                │                            │             ║
║                   customer_key │                            │ profile_key ║
║                                ▼                            ▼             ║
║                    dim_customer (503,216)    dim_reviewer_profile (1,896) ║
║                    identity only (D2)        junk dimension (D2)          ║
║                                                                           ║
║  10 analytics views +  6 stg_* tables used only during a DAG run          ║
╚═══════════════════════════════════════════════════════════════════════════╝
        │
        ▼
 dashboard/app.py       Streamlit, 2 pages, LIVE connection.
                        Reads views, never raw fact/dim joins.
```

## Why the shape is like this

### Two databases, not two schemas (D7)

`sephora_oltp` and `sephora_dw` are separate databases on the same Postgres
instance. The ETL therefore holds two connections and cannot accidentally join
across the boundary — which is what keeps the star schema honest about being
loaded, rather than being a view over the OLTP tables.

The practical consequence shows up in `dim_date`: its range is derived from
`MIN`/`MAX(submission_date)` in the OLTP staging layer, but the table lives in
the warehouse, so it cannot be seeded by a static migration. `load_dim_date()`
reads bounds from one database and writes to the other.

### Normalize, then de-normalize again

`raw → 3nf` removes redundancy. `3nf → staging` puts a lot of it back. That is
not wasted work — the two layers have different jobs:

| | `3nf` | `staging` / `dw` |
|---|---|---|
| Optimized for | correctness, write integrity | read speed, dashboard joins |
| `brand_name` stored | once, in `brand` | on every product row |
| A missing attribute is | a NULL foreign key | the string `'Unknown'` |
| Question it answers | "is this data internally consistent?" | "what is the average rating by brand?" |

Doing both is what demonstrates the difference between an OLTP model and a
dimensional one, rather than asserting it.

### Three layers in OLTP, not two

`raw` exists purely for traceability — every source column survives, including
the ones nothing downstream uses. Columns are dropped exactly once, explicitly,
at the `raw → 3nf` boundary (**D14**), so it stays possible to tell later which
removals were cleaning and which were scope.

## Failure and recovery

| Failure | What happens |
|---|---|
| Partial `COPY` during ingest | Whole load rolls back inside one transaction; `raw` is unchanged |
| A dimension key won't resolve | Row dropped, counted against a named reason; unexplained gaps raise `ReconciliationError` |
| Bad data reaches the gate | `DataQualityError` → `AirflowFailException`; fails fast, does not consume the retry budget |
| A DAG task fails | `cleanup_staging` still runs (`all_done`); `watch_for_failure` still marks the run **FAILED** |
| Task retried mid-write | Staging rows for that `batch_id` are deleted before re-staging, so a retry replaces rather than doubles |
| Pipeline re-run entirely | `ON CONFLICT DO NOTHING` → 0 inserted; verified |

## Physical layout

| Component | Where | Port |
|---|---|---|
| Postgres 16 | `leapfrog_sephora_postgres` | host **5434** → 5432 |
| Airflow 3.3 API server | `leapfrog_airflow_apiserver` | host **8081** → 8080 |
| Airflow scheduler / DAG processor | `leapfrog_airflow_*` | — |
| Airflow metadata DB | `leapfrog_airflow_metadata` | internal only |
| Streamlit | host process | **8501** |

Both compose files share `name: leapfrog-sephora`, so they join one Docker
network and Airflow reaches Postgres as `postgres:5432` — the *internal* port.
From inside a container, `localhost:5434` is the container itself.

> Port 5434 is deliberate. Ports 5432 and 5433 on the original development
> machine belong to unrelated stacks, and sharing an instance between projects
> makes it too easy to drop the wrong database.

## Related documents

- [04 — Schema documentation](04_schema_documentation.md)
- [05 — ETL and incremental loading](05_etl_and_incremental_loading.md)
- [06 — Airflow runbook](06_airflow_runbook.md)
- [`dashboard/data_model.md`](../dashboard/data_model.md) — what the dashboard reads
