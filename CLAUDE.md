# CLAUDE.md — Sephora Reviews Data Engineering Capstone

**This file is the source of truth and the running checkpoint for this project.**
Update the Status table and the Measured Numbers section at the end of every stage.
Never let it drift from what has actually been built and verified.

---

## 1. Project goals (from initial planning)

Capstone project for a data engineering course. End-to-end pipeline over Sephora
product/review data:

1. Explore the raw CSVs — missing values, duplicates, inconsistencies.
2. Clean the raw CSVs.
3. Build a 3NF OLTP database and load the cleaned data into it.
4. Build a star-schema data warehouse and load it from the OLTP.
5. Write analytics queries and build a dashboard.
6. Orchestrate the whole workflow with Apache Airflow (full + incremental).

### Presentation requirements (8 minutes, must cover all five)

1. Introduction to the data source
2. Data flow architecture
3. Design decisions made
4. Airflow DAG — incremental and full
5. Data visualization — KPIs, trends, insights

### Format constraint

The repo structure, module boundaries, code style, SQL migration conventions, and doc set
mirror the reference project
(`reference/healthcare-analytics-data-warehouse-main.zip` — Synthea EHR → Postgres OLTP →
star schema DW → Airflow → Power BI), because that is the exact pattern taught in the course.
Deviations from it are deliberate and listed in section 7.

---

## 2. Locked business questions

The dashboard and analytics queries answer exactly these. Do not add or drop without
recording a decision-log entry.

1. Which brands and categories earn the highest ratings, and which underperform?
2. How do review volume and average rating trend over time?
3. Does price predict satisfaction — do expensive products actually rate better?
4. Which product attributes (Vegan, Clean at Sephora, Cruelty-Free…) correlate with rating?
5. Do reviewers with different skin types rate the same skincare products differently?

---

## 3. Stack

- **Python 3.13.12** — pandas 3.0.3, psycopg2, python-dotenv
- **PostgreSQL 16** — two databases: `sephora_oltp` (schemas `raw`, `3nf`, `staging`) and
  `sephora_dw` (star schema)
- **Apache Airflow 3.3.0** — Docker Compose, LocalExecutor, staged DAG, watermark incremental
- **Power BI Desktop** — 2-page dashboard, live Postgres connection
- **SQL** — append-only numbered migrations

---

## 4. Architecture

```
data/raw/*.csv
   │  explore.py    profiling / inconsistency report
   │  clean.py      → data/processed/*.csv
   ▼
sephora_oltp ── raw schema       1:1 CSV mirror, loaded by ingest.py (COPY)
   │            3nf schema       9 normalized tables, FKs enforced
   │            staging schema   trimmed, analytics-ready subset
   ▼  etl/ package: extract → transform → quality gate → load
sephora_dw     5 dims + fact_reviews + dim_highlight + bridge_product_highlight
   ▼
Power BI (2 pages)
```

Grain of `fact_reviews`: **one row per review.**

---

## 5. Status

| Stage | State |
|---|---|
| 0. Project plan + CLAUDE.md | Done |
| 1. Explore (`explore.py`, problem statement doc) | Not started |
| 2. Clean (`clean.py` → `data/processed/`) | Not started |
| 3. OLTP raw + 3NF + staging, `ingest.py` | Not started |
| 4. DW star schema migrations | Not started |
| 5. ETL package + `pipeline.py` | Not started |
| 6. Airflow staged DAG | Not started |
| 7. Analytics views + Power BI dashboard | Not started |
| 8. README / decision log / checklist | Not started |

---

## 6. Measured numbers

Fill in from actual runs. Never estimate here — if it isn't measured, leave it blank.

### Source data (measured 2026-08-06, before any cleaning)

| Metric | Value |
|---|---|
| `product_info.csv` rows × cols | 8,494 × 27 |
| Duplicate `product_id` | 0 |
| Brands (`brand_id` ↔ `brand_name`, strictly 1:1) | 304 |
| Distinct (primary, secondary, tertiary) category triples | 174 |
| Distinct highlights (parsed from the list-string) | 112 |
| Review rows across 5 CSVs | 1,094,411 |
| Distinct authors | 503,216 |
| Distinct products reviewed | 2,351 |
| `submission_time` range | 2008-08-28 → 2023-03-21 |
| Orphan reviews (product_id not in product_info) | 0 |
| Duplicates on (author_id, product_id, submission_time) | 1,040 |
| Duplicates on (author_id, product_id) only | 5,525 |
| Reviews dated 2023 (held back for the incremental demo) | 49,531 |
| Rating distribution | 5★ 698,951 · 4★ 199,389 · 3★ 81,816 · 2★ 53,032 · 1★ 61,223 |

### Pipeline runs

| Run | Result |
|---|---|
| Cleaning: rows in → out | _pending_ |
| raw → 3nf → staging reconciliation | _pending_ |
| Full load (`pipeline.py --full-reload`) | _pending_ |
| Incremental load (`pipeline.py`) | _pending_ |
| Idempotency, real case (re-run full, no watermark reset) | _pending_ |
| Idempotency, empty case (re-run incremental) | _pending_ |
| Airflow full / incremental / re-run | _pending_ |

---

## 7. Key design decisions

Full reasoning lives in `docs/09_decision_log.md`. Summary:

- **D1** Category is keyed on the full (primary, secondary, tertiary) triple — one secondary
  category appears under up to 7 different primaries, so it is not a real hierarchy.
- **D2** Reviewer attributes (skin_tone / skin_type / eye_color / hair_color) belong to the
  **review**, not the author — the same author shows up to 4 different values. In the DW they
  collapse into a junk dimension, `dim_reviewer_profile`.
- **D3** Highlights get `bridge_product_highlight`, not 112 boolean columns and not a
  delimited string.
- **D4** Dedup key is (author_id, product_id, submission_time) — 1,040 dupes — not
  (author_id, product_id) — 5,525 — because the difference is legitimate re-reviews.
- **D5** `helpfulness` nulls are not imputed: null ⟺ `total_feedback_count = 0`. Undefined,
  not missing.
- **D6** Full review text stops at the OLTP boundary; `fact_reviews` carries `review_length`.
- **D7** Two physical databases: `sephora_oltp` and `sephora_dw`.
- **D8** Incremental split: full = reviews through 2022-12-31, incremental = 2023-01-01 on
  (49,531 real rows across 3 months).
- **D9** Surrogate keys come from Postgres `serial`, never from pandas.
- **D10** Products and highlights load in full every run; only reviews are incremental.

### Deliberate deviations from the reference project

| Deviation | Why |
|---|---|
| Explicit `3nf` schema between `raw` and `staging` | Course goal #3 requires a 3NF OLTP; the reference's OLTP was a source mirror only |
| Script-based ingestion (`ingest.py`, `COPY`) | The reference imported CSVs by hand in DBeaver — its own checklist calls that a gap. 1.09M rows makes manual import impractical |
| One bridge, not two | The dataset has exactly one genuine many-to-many (product ↔ highlight) |
| Bridge does not depend on the fact load | It is a dimension-outrigger bridge, not a fact bridge |
| Junk dimension `dim_reviewer_profile` | Four correlated low-cardinality attributes — the textbook case |
| `dim_author` has no descriptive attributes | See D2 |

---

## 8. Conventions to follow when writing code

Matched to the reference project so the format stays consistent:

- `etl/` modules use **2-space indentation**; top-level scripts use 4.
- Every module: `logger = logging.getLogger(__name__)`, f-string log messages, no `print()`
  in pipeline code (`explore.py` is the exception — it is a reporting script).
- `extract.py` exposes a generic `extract(conn, sql, params=None)` helper; every table gets
  its own named function on top of it, plus `_full` / `_incremental` / `_all` variants.
- `transform.py` exposes module-level column-list constants (`FACT_COLUMNS`, `BRIDGE_*`) and
  a single `_drop_unmatched` choke point for dropping rows whose merge key didn't resolve.
- `quality.py` is a **gate, not a fixer** — it raises `DataQualityError`, never repairs data.
- `load.py` uses the `_records` / `_execute` helper pair, and every insert targets a natural
  or source key with `ON CONFLICT … DO NOTHING`.
- SQL lives in numbered append-only migrations, never edited in place:
  `sql/oltp/migrations/<timestamp>_<name>.sql`, `sql/datawarehouse/migrations/NN_<name>.sql`.
- Credentials only via `.env` / `python-dotenv` — never hardcoded, never committed.
- Empty DataFrames are handled explicitly at every stage (return typed empty frame, skip
  load, log it) so an empty incremental run is a no-op, not a crash.
