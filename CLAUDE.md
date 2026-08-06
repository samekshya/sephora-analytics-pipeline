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

The warehouse schema additionally builds on an earlier hand-written schema of my own
(`reference/02_warehouse_schema.sql`) — its date-key convention, data-driven `dim_date`
range, FK indexes and CHECK constraints are kept; its `dim_customer` design is corrected
(see D2).

---

## 2. Locked business questions

The dashboard and analytics queries answer exactly these four. Do not add or drop without
recording a decision-log entry.

1. Which brands and categories earn the highest ratings, and which underperform?
2. How do review volume and average rating trend over time?
3. Does price predict satisfaction — do expensive products actually rate better?
4. Do reviewers with different skin types rate the same skincare products differently?

> A fifth question — "which product attributes (Vegan, Clean at Sephora…) correlate with
> rating?" — was evaluated against the data and deliberately dropped. See **D3**.

---

## 3. Stack

- **Python 3.13.12** — pandas 3.0.3, psycopg2 2.9.12, python-dotenv
- **PostgreSQL 16** — in Docker, **host port 5434**, compose project `leapfrog-sephora`,
  volume `leapfrog-sephora_sephora_pgdata`. Two databases: `sephora_oltp` (schemas `raw`,
  `3nf`, `staging`) and `sephora_dw` (schema `dw`, star schema).
  > Ports 5432 and 5433 on this machine belong to unrelated stacks (`course_postgres` and a
  > separate Sephora project at `D:\Data Projects\sephora-analytics-de-project`). This project
  > uses its own container on 5434 — never point it at 5432 or 5433.
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
sephora_dw     dw schema — 5 dimensions + fact_reviews
   ▼
Power BI (2 pages)
```

Grain of `fact_reviews`: **one row per review.**

---

## 5. Target schemas

### OLTP — `sephora_oltp`

`raw` schema: `raw.product_info`, `raw.reviews` (all source columns, plus `source_file`).

`3nf` schema — 9 tables, FKs enforced:

| Table | Key | Notes |
|---|---|---|
| `brand` | `brand_id` PK | 304 rows; `brand_name` UNIQUE (1:1 verified) |
| `category` | `category_id` serial PK | 174 rows; UNIQUE on (primary, secondary, tertiary) |
| `product` | `product_id` PK | FK → brand, FK → category |
| `author` | `author_id` PK | 503,216 rows; **no descriptive attributes** (D2) |
| `skin_tone` / `skin_type` / `eye_color` / `hair_color` | serial PK each | lookup tables |
| `review` | `review_id` PK | FK → author, product, and the 4 lookups |

`staging` schema: `staging.product` (brand name + 3 category columns flattened),
`staging.review` (no review text, `review_length` precomputed).

### Warehouse — `sephora_dw`, schema `dw`

| Table | Key | Notes |
|---|---|---|
| `dim_date` | `date_key INT` (YYYYMMDD) | `full_date` UNIQUE; range derived from the data with 30 days padding, `ON CONFLICT DO NOTHING` |
| `dim_brand` | `brand_key` serial | `brand_id` UNIQUE |
| `dim_product` | `product_key` serial | `product_id` UNIQUE; FK → dim_brand; 3 category columns flattened; price_usd, price_band, size, loves_count, flags |
| `dim_customer` | `customer_key` serial | `customer_id` UNIQUE — **shopper identity only** (D2) |
| `dim_reviewer_profile` | `reviewer_profile_key` serial | **Junk dimension**, ~2,003 rows; UNIQUE on (skin_tone, skin_type, eye_color, hair_color) |
| `fact_reviews` | `review_key` serial | `UNIQUE(source_row_id, product_id)`; FKs to product / customer / reviewer_profile / date; measures: rating (CHECK 1–5), is_recommended, helpfulness, total_feedback_count, total_pos_feedback_count, total_neg_feedback_count, review_length; `submission_date` for the watermark |

Indexes on all four fact FK columns. **No `brand_key` on the fact table** (D11).

---

## 6. Status

| Stage | State |
|---|---|
| 0. Project plan + CLAUDE.md | Done |
| 1. Explore (`explore.py`, problem statement doc) | **Done** — 14 checks, all run clean; findings in `docs/problem statement and data sources.md`, decisions D1–D13 in `docs/09_decision_log.md` |
| 2. Clean (`clean.py` → `data/processed/`) | **Done** — run end-to-end in 24s; `data/processed/products.csv` (8.1 MB) and `reviews.csv` (546.7 MB) |
| 3. OLTP raw + 3NF + staging, `ingest.py` | **Done** — 15 migrations applied, reconciliation clean, 0 row gap end to end |
| 4. DW star schema migrations | **Done** — 7 migrations, 5 dims + fact_reviews |
| 5. ETL package + `pipeline.py` | **Done** — all 4 run modes verified; 8/8 quality fault-injection tests pass |
| 6. Airflow staged DAG | **Done** — full and incremental runs both green, all 15 tasks |
| 7. Analytics views | **Done** — 6 views + cross-check script. **Power BI dashboard still to build** (needs the desktop app) |
| 8. README / decision log / checklist | **Done** — 16 decisions logged |

---

## 7. Measured numbers

Fill in from actual runs. Never estimate here — if it isn't measured, leave it blank.

### Source data (measured 2026-08-06, before any cleaning)

| Metric | Value |
|---|---|
| `product_info.csv` rows × cols | 8,494 × 27 |
| Duplicate `product_id` | 0 |
| Brands (`brand_id` ↔ `brand_name`, strictly 1:1) | 304 |
| Distinct (primary, secondary, tertiary) category triples | 174 |
| Review rows across 5 CSVs | 1,094,411 |
| Distinct authors | 503,216 |
| Distinct products reviewed | 2,351 |
| `submission_time` range | 2008-08-28 → 2023-03-21 |
| Rows with a non-midnight time component | 0 (date grain is sufficient) |
| Orphan reviews (product_id not in product_info) | 0 |
| Duplicates on (author_id, product_id, submission_time) | 1,040 |
| Duplicates on (author_id, product_id) only | 5,525 |
| Duplicates on (source_row_id, product_id) across all 5 files | 0 (valid idempotency key) |
| Reviews dated 2023 (held back for the incremental demo) | 49,531 |
| Rating distribution | 5★ 698,951 · 4★ 199,389 · 3★ 81,816 · 2★ 53,032 · 1★ 61,223 |
| Authors whose reviewer profile is **not** constant | 22,503 (4.47%) |
| Reviews written by those authors | 149,788 (13.69%) |
| Distinct reviewer-profile combinations | 2,003 (of 4,200 possible) |
| Reviews before the 2023-01-01 cutoff (full load, pre-dedup) | 1,044,880 |
| `review_text` total volume | 350 MB (min 8, median 263, mean 321, max 6,448 chars) |
| Rows where `helpfulness IS NULL` ⟺ `total_feedback_count = 0` disagree | 0 |
| Rows where `pos + neg != total` feedback | 0 |
| Products with reviews (of 8,494 catalogue products) | 2,351 |
| `highlights`: distinct tags / product-tag pairs | 112 / 30,204 (descoped, D3) |

### Known data-quality issues to fix in `clean.py`

| Issue | Detail |
|---|---|
| `eye_color` casing/spelling | Both `'Grey'` and `'gray'` present — same colour, must be normalised to one |
| `skin_tone` sentinel | `'notSureST'` is a "not sure" placeholder, not a real skin tone — map to Unknown |
| Duplicate reviews | 1,040 exact duplicates on the D4 key |
| Redundant review columns | `product_name` / `brand_name` / `price_usd` repeat on every review row and agree 100% with `product_info.csv` — drop at staging |
| Null reviewer attributes | skin_tone 170,539 · eye_color 209,628 · skin_type 111,557 · hair_color 226,768 → map to `'Unknown'` for the junk dimension |

### Pipeline runs

| Run | Result |
|---|---|
| **Cleaning — products** | 8,494 in → 8,494 out (0 dropped); 16,072 cells whitespace-trimmed; `product_id` unique, `brand_id` → `brand_name` 1:1 both asserted |
| **Cleaning — reviews** | 1,094,411 in → **1,093,371** out (1,040 duplicates removed); 1,030,753 cells trimmed; 4,859 `eye_color` `'Grey'` → `'gray'`; 70 `skin_tone` `'notSureST'` → null; 0 unparseable dates; 0 `(source_row_id, product_id)` collisions after dedup |
| **Expected fact-table counts** (post-dedup) | full load `< 2023-01-01`: **1,043,868** · incremental `>= 2023-01-01`: **49,503** |
| **Ingest** (`ingest.py`, COPY) | `raw.product_info` 8,494 · `raw.reviews` 1,093,371 — loaded in 15s, counts asserted against `clean.py` output |
| **raw → 3nf → staging** | 0 row gap on both products and reviews; all 6 integrity checks return 0 |
| **3NF row counts** | brand 304 · category 174 · product 8,494 · author 503,216 · review 1,093,371 · skin_tone 13 · skin_type 4 · eye_color 5 · hair_color 7 |
| **Staging row counts** | product 8,494 · review 1,093,371 (date range 2008-08-28 → 2023-03-21) |
| raw → 3nf → staging reconciliation | _pending_ |
| **Full load** (`pipeline.py --full-reload`) | 1,043,868 fact rows inserted; dims 304 / 8,494 / 503,216 / 1,896 / 5,379. Fact load 62s |
| **Idempotency, real case** (re-run full) | 1,043,868 offered, **0 inserted** everywhere |
| **Incremental load** (`pipeline.py`) | watermark 2022-12-31 → 49,503 extracted, **49,503 inserted** |
| **Idempotency, empty case** (re-run incremental) | watermark 2023-03-21 → **0 extracted**, gate skipped, 0 inserted |
| **Final warehouse** | **fact_reviews 1,093,371** — matches `staging.review` exactly. Date range 2008-08-28 → 2023-03-21, avg rating 4.2990 |
| **Quality fault injection** (`tests/test_quality.py`) | 8 passed, 0 failed |
| **Airflow, full reload** | All 15 tasks green; 1,043,868 fact rows. `load_fact_from_staging` SIGKILLed on the first attempt and succeeded after chunking (D15) |
| **Airflow, incremental** | All 15 tasks green in **22 seconds**; 49,503 rows → 1,093,371 total |
| **Staging cleanup** | All 6 staging tables at 0 rows after both runs (`trigger_rule="all_done"`) |
| **Analytics views** | 6 views created and cross-checked against the fact table |

### Headline analytics results (for the presentation)

| Finding | Detail |
|---|---|
| Overall | 1,093,371 reviews · avg rating **4.2990** · **83.99%** recommend |
| **BQ3 — price vs satisfaction is an inverted U** | Under $15 **4.2383** → $15-30 4.2756 → $30-50 4.3055 → **$50-100 4.3335 (peak)** → $100+ **4.2708 (falls back)**. Rating variance also falls steadily as price rises (stddev 1.2211 → 1.0996) |
| BQ1a — best brands (≥500 reviews) | MARA 4.8608 · DAMDAM 4.7394 · Dr. Lara Devgan 4.7164 |
| BQ1a — worst brands (≥500 reviews) | Topicals 3.6590 · DERMAFLASH 3.7856 · Isle of Paradise 3.8601 |
| BQ1b — categories (secondary, see D16) | Moisturizers 297,201 · Treatments 221,871 · Cleansers 200,477 · Eye Care 74,966 · Masks 70,483 · Sunscreen 41,126. Best-rated Cleansers 4.3443, worst Sunscreen 4.1665 |
| BQ2 — trend | Volume grew 2,760 (2008) → 215,278 (2020), then eased. Rating dipped to **4.2075 in 2020** and recovered to 4.3384 by 2022 |
| BQ4 — skin type | Combination 4.3092 → dry 4.2911 → normal 4.2822 → **oily 4.2708**. Real but small spread (0.038) — worth stating as a weak signal, not a headline |

---

## 8. Key design decisions

Full reasoning lives in `docs/09_decision_log.md`. Summary:

- **D1** Category is keyed on the full (primary, secondary, tertiary) triple — one secondary
  category appears under up to 7 different primaries, so it is not a real hierarchy. The
  warehouse flattens all three onto `dim_product`.
- **D2** Reviewer attributes (skin_tone / skin_type / eye_color / hair_color) belong to the
  **review**, not the author. Measured: 22,503 authors (4.47%) give more than one distinct
  value, affecting 149,788 reviews (13.69%). A `dim_customer` keyed `UNIQUE` on the author,
  holding those four attributes, would force one profile per author and mis-tag ~1 in 7
  reviews. Fixed with a **junk dimension**, `dim_reviewer_profile` (2,003 rows);
  `dim_customer` keeps identity only.
- **D3** **`highlights` evaluated, then dropped.** The column holds a stringified list
  (112 distinct tags, 82.4% coverage of reviewed products, 89.6% of reviews) and is a genuine
  many-to-many, which in a 3NF database would require `highlight` + `product_highlight`
  tables and in the warehouse a `dim_highlight` + bridge. Explored and measured, then cut to
  keep scope proportionate to an 8-minute presentation and to avoid many-to-many filter
  complexity in Power BI. Business question #5 was dropped with it. `explore.py` still
  reports the tag distribution so the decision is visibly informed, not accidental.
  Storing the raw comma-list in a column was never an option — that breaks 1NF.
- **D4** Dedup key is (author_id, product_id, submission_time) — 1,040 dupes — not
  (author_id, product_id) — 5,525 — because the difference is legitimate re-reviews.
- **D5** `helpfulness` nulls are not imputed: null ⟺ `total_feedback_count = 0`. Undefined,
  not missing. Helpfulness measures filter on `total_feedback_count > 0`.
- **D6** Full review text stops at the OLTP boundary; `fact_reviews` carries `review_length`.
- **D7** Two physical databases: `sephora_oltp` and `sephora_dw`.
- **D8** Incremental split: full = reviews through 2022-12-31, incremental = 2023-01-01 on
  (49,531 real rows across 3 months).
- **D9** Surrogate keys come from Postgres `serial`, never from pandas.
- **D10** Products and brands load in full every run; only reviews are incremental.
- **D11** `brand_key` removed from `fact_reviews`. Brand is functionally determined by
  product, so a copy on the fact adds no information and creates a way for the two to
  disagree. It lives on `dim_product` only.
- **D12** `dim_date.date_key` is `INT` in `YYYYMMDD` form, and the date range is derived from
  the data with 30 days of padding rather than hardcoded — both carried over from the earlier
  hand-written schema, which got this right.
- **D13** `UNIQUE(source_row_id, product_id)` is kept as the fact-table idempotency key.
  Verified: the CSV row index restarts per file, but each product appears in exactly one file
  (the files are split by product range), so the pair collides **0 times** across all
  1,094,411 rows.
- **D14** `clean.py` does **not** drop columns. Every source column reaches `raw` for
  traceability; column trims (`highlights`, `ingredients`, sparse pricing columns) happen once,
  explicitly, at the `raw → 3nf` boundary. Mixing row-cleaning and column-dropping in one step
  makes it impossible to tell later which was a scope decision and which was a cleaning rule.

### Deliberate deviations from the reference project

| Deviation | Why |
|---|---|
| Explicit `3nf` schema between `raw` and `staging` | Course goal #3 requires a 3NF OLTP; the reference's OLTP was a source mirror only |
| Script-based ingestion (`ingest.py`, `COPY`) | The reference imported CSVs by hand in DBeaver — its own checklist calls that a gap. 1.09M rows makes manual import impractical |
| No bridge tables | The one genuine many-to-many in this dataset (`highlights`) was deliberately descoped — see D3 |
| Junk dimension `dim_reviewer_profile` | The reference had no analog; four correlated low-cardinality attributes is the textbook case |
| `dim_customer` carries no descriptive attributes | See D2 |

---

## 9. Conventions to follow when writing code

Matched to the reference project so the format stays consistent:

- `etl/` modules use **2-space indentation**; top-level scripts use 4.
- Every module: `logger = logging.getLogger(__name__)`, f-string log messages, no `print()`
  in pipeline code (`explore.py` is the exception — it is a reporting script).
- `extract.py` exposes a generic `extract(conn, sql, params=None)` helper; every table gets
  its own named function on top of it, plus `_full` / `_incremental` / `_all` variants.
- `transform.py` exposes module-level column-list constants (`FACT_COLUMNS`) and a single
  `_drop_unmatched` choke point for dropping rows whose merge key didn't resolve.
- `quality.py` is a **gate, not a fixer** — it raises `DataQualityError`, never repairs data.
- `load.py` uses the `_records` / `_execute` helper pair, and every insert targets a natural
  or source key with `ON CONFLICT … DO NOTHING`.
- SQL lives in numbered append-only migrations, never edited in place:
  `sql/oltp/migrations/<timestamp>_<name>.sql`, `sql/datawarehouse/migrations/NN_<name>.sql`.
- DDL uses `IF NOT EXISTS` so migrations are rerunnable.
- Credentials only via `.env` / `python-dotenv` — never hardcoded, never committed.
- Empty DataFrames are handled explicitly at every stage (return typed empty frame, skip
  load, log it) so an empty incremental run is a no-op, not a crash.
