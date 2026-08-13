# CLAUDE.md — Sephora Reviews Data Engineering Capstone

**This file is the source of truth and the running checkpoint for this project.**
Update the Status table and the Measured Numbers section at the end of every stage.
Never let it drift from what has actually been built and verified.

---

## 0. Project checkpoint — read this first

Written 2026-08-12 so project work can resume from verified facts rather than
assumptions. Sections 1–9 describe the *design*; this section describes *where the work
actually stands right now*.

### The one-line summary

**Stages 1–11 of the pipeline are built, run, and verified.** The warehouse holds
1,093,371 fact rows, Airflow runs both modes green, the dashboard works, 51 tests
pass, and the eight-minute deck is complete. The DAG was then simplified from 16
tasks / 33 edges to **15 / 21** by replacing the failure watcher with a teardown
(**D24**), which is verified by an injected failure and fixed a latent race.

### Where the code is right now

| | |
|---|---|
| Current branch | `dag-simplification` — the D24 work, **not yet merged** |
| `main` | `e2a4323` — the completion merge, local only |
| Remote state | `origin/main` still at `90edfab`; **nothing since has been pushed** |
| Deck | **`presentation/sephora_pipeline_deck.html` — nine slides, current, the one to present.** Opens in a browser, no build step. Embeds the generated SVG diagrams, the DAG graph, and two cropped dashboard charts |
| Diagrams | `docs/diagrams/build_diagrams.py` generates architecture, OLTP ER and star schema as SVG (+ PNG rasters for Markdown). Used by both the README and the deck — see that folder's README to regenerate |
| Screenshots | The three the deck uses are **current** (`airflow_dag_graph`, `chart_price_rating`, `chart_price_spread`). The original four are **still STALE** and now feed only `build_deck.ps1` |
| PowerPoint | `build_deck.ps1` → `presentation/output/*.pptx|pdf` is **superseded**: eight slides, pre-D24/D25, stale captures. Kept as the path to an editable Office file if one is ever required |

### Working conventions the user expects

- **Git**: work on a phase branch, merge to `main` when the phase is done.
  Match the existing log's voice: imperative sentences that say what changed and why
  ("Make the hype gap, price range and skin-group floor real query parameters").
- **This file**: update the Status table and Measured numbers at the end of every
  stage. Never write an estimated number here — measure it or leave it blank.
- **Code style**: section 9. `etl/` is 2-space indented, top-level scripts are 4.
- **Database**: **port 5434 only.** 5432 and 5433 on this machine belong to
  unrelated stacks, one of which is a *different Sephora project*. Pointing at
  the wrong port will appear to work and produce wrong numbers.

### Repo map

```
explore.py          stage 1 — profiling, 14 checks, prints a report (only script allowed print())
clean.py            stage 2 — data/raw/*.csv → data/processed/*.csv, drops rows never columns (D14)
ingest.py           stage 3 — COPY data/processed → raw schema, asserts counts against clean.py
pipeline.py         local runner: --mode full | historical | incremental
etl/                extract · transform · reconcile · quality · load · staging  (2-space indent)
dags/               sephora_dw_pipeline_staged.py — the 15-task DAG
sql/init/           create both databases
sql/oltp/           01_raw_schema.sql + 15 timestamped migrations (raw → 3nf → staging)
sql/datawarehouse/  7 numbered migrations — 5 dims + fact_reviews
sql/analytics/views/  11 views, the dashboard's only read surface
sql/validation/     dashboard_checks.sql — read-only assertions, changes nothing (D22)
dashboard/app.py    Streamlit, ONE page, Sephora theme, live Postgres connection (D25)
tests/              unit/ + integration/ + test_dag_structure.py + verify_dag_in_container.py
docs/               01–11 + README index; guide/ holds the 12-page PDF walkthrough; diagrams/ generates the 3 diagrams; screenshots/
presentation/       sephora_pipeline_deck.html — the 9-slide deck; assets/, speaker_notes.md
setup.ps1           11 resumable steps, end to end from empty Docker to loaded warehouse
reference/          the course's reference project — the format constraint, see section 1
```

Total migrations: **22** (15 OLTP + 7 DW), all re-appliable against a loaded database.

### Getting a working environment

```powershell
# 1. Databases (compose project leapfrog-sephora, host port 5434)
docker compose up -d

# 2. Full setup, 11 resumable steps — safe to re-run
.\setup.ps1

# 3. Tests
py -m pytest              # 51 collected; 1 skips locally (airflow not in host venv)

# 4. Dashboard
py -m streamlit run dashboard/app.py        # http://localhost:8501

# 5. Airflow
docker compose -f docker-compose-airflow.yml up -d   # http://localhost:8081
```

`.env` already exists locally and is gitignored; `.env.example` carries working
defaults. Source CSVs are **not** in git — `data/README.md` says where to get them.

### What remains — the actual to-do list

1. **Merge `dag-simplification`**, then push. `origin` is 14+ commits behind.
2. Optional: re-capture the four original screenshots (see `docs/screenshots/README.md`).
   They no longer block the presentation — the HTML deck does not read them — but
   `build_deck.ps1` still does, and `failure_proof_v2_20260812` (a **failed** run with
   `cleanup_staging` green) remains the most persuasive evidence in the set.
3. Optional: `docs/07_dashboard_insights.md` predates the review-length view, and
   `docs/03_architecture.md` predates the generated architecture diagram.
4. If the numbers ever move, regenerate the PDF guide — `docs/guide/README.md` has the
   one-line Chrome command — and re-run `build_diagrams.py`, which has the row counts on it.

### Things that look like bugs and are not

- **The warehouse being 49,503 rows behind staging** at the historical baseline
  is correct — those are the 2023 rows held back for the incremental demo (D8).
  The dashboard's data-quality panel distinguishes "held back" from "lost" on
  purpose (D23). Do not "fix" it.
- **`--mode historical` does not reset a full warehouse.** There is no truncate
  anywhere and every load is `ON CONFLICT DO NOTHING`. To reset for a demo:
  `DELETE FROM dw.fact_reviews WHERE submission_date >= '2023-01-01'`.
- **`historical` is missing from the Airflow trigger dropdown on purpose.** The
  DAG offers `TRIGGERABLE_LOAD_MODES` — full and incremental — because
  historical is a baseline-rebuild tool, not something you orchestrate, and
  against an already-full warehouse it inserts nothing and reads as a broken
  run. It is still in `etl.extract.LOAD_MODES` and still runs locally with
  `py pipeline.py --mode historical`.
- **`cleanup_staging` showing green on a FAILED Airflow run** is the intended
  state. It is a **teardown**: it runs after failures so staging is not stranded,
  and Airflow excludes it from run-state calculation so it cannot report success
  on the run's behalf (D24). Do not set `on_failure_fail_dagrun=True` to "improve"
  this — that makes cleanup the sole effective leaf again and reinstates the
  exact bug D20 was written about.
- **A red run with no `failed` task** — look for `upstream_failed` (orange). Run
  state comes from `load_fact_from_staging`, which inherits it.
- **`helpfulness` nulls** are undefined, not missing (D5). Do not impute them.

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

The dashboard and analytics queries answer exactly these five. Do not add or drop without
recording a decision-log entry.

1. **BQ1** — Which brands and categories earn the highest ratings, and which underperform?
2. **BQ2** — Hype vs reality: which products have high `loves_count` but low ratings?
3. **BQ3** — Does price predict satisfaction — do expensive products actually rate better?
4. **BQ4** — Do reviewers with different skin types and tones rate the same products differently?
5. **BQ5** — How do review volume and average rating trend over time?

> BQ2 was added during the phase-9 remediation and is backed by `vw_hype_vs_reality`.
>
> A further question — "which product attributes (Vegan, Clean at Sephora…) correlate with
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
- **Streamlit + Plotly** — single-page dashboard, live Postgres connection (D18; replaced Power BI)
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
   ▼  etl/ package: extract → transform → reconcile → quality gate → load
sephora_dw     dw schema — 5 dimensions + fact_reviews + 11 analytics views
   ▼
Streamlit dashboard (one page, live connection)
```

Orchestrated by `dags/sephora_dw_pipeline_staged.py` (15 tasks) or run locally with
`pipeline.py --mode full|historical|incremental`.

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
| `dim_reviewer_profile` | `reviewer_profile_key` serial | **Junk dimension**, **1,896 rows** (2,003 combinations exist in the raw data; cleaning collapses them); UNIQUE on (skin_tone, skin_type, eye_color, hair_color) |
| `fact_reviews` | `review_key` serial | `UNIQUE(source_row_id, product_id)`; FKs to product / customer / reviewer_profile / date; measures: rating (CHECK 1–5), is_recommended, helpfulness, total_feedback_count, total_pos_feedback_count, total_neg_feedback_count, review_length; `submission_date` for the watermark |

Indexes on all four fact FK columns. **No `brand_key` on the fact table** (D11).

---

## 6. Status

| Stage | State |
|---|---|
| 0. Project plan + CLAUDE.md | Done |
| 1. Explore (`explore.py`, problem statement doc) | **Done** — 14 checks, all run clean; findings in `docs/02_data_quality_findings.md`, decisions D1–D13 in `docs/09_decision_log.md` |
| 2. Clean (`clean.py` → `data/processed/`) | **Done** — run end-to-end in 24s; `data/processed/products.csv` (8.1 MB) and `reviews.csv` (546.7 MB) |
| 3. OLTP raw + 3NF + staging, `ingest.py` | **Done** — 15 migrations applied, reconciliation clean, 0 row gap end to end |
| 4. DW star schema migrations | **Done** — 7 migrations, 5 dims + fact_reviews |
| 5. ETL package + `pipeline.py` | **Done** — three named load modes (D17), row reconciliation (D19), severity-aware quality gate (D21) |
| 6. Airflow staged DAG | **Done** — 15 tasks; cleanup is a teardown, replacing the failure watcher (D24, superseding D20); historical, incremental and an injected-failure run all verified |
| 7. Analytics views | **Done** — 11 views (one uses window functions), split from validation SQL (D22); `vw_rating_by_brand_category` added so the dashboard category filter can scope the brand chart (D25) |
| 8. Streamlit dashboard | **Done** — ONE page, validated Sephora palette, 4 query-bound controls (category · **brand** · brand review floor · product search — the first three in the sidebar), live KPI strip and data-quality panel (D18, D23, D25) |
| 9. Tests | **Done** — 52 pytest passing + 11 DAG assertions verified in-container |
| 10. Documentation | **Done** — `docs/01`–`11` + index; 24 decisions logged |
| 11. Reproducibility | **Done** — `setup.ps1`, 11 resumable steps; `.env.example` with working defaults |
| — Dashboard polish | **Done and merged** — status strip, 3 query-param controls, shareable Deep-dive URL, `vw_rating_by_review_length`, data-quality panel, shared page shape. Source of D23 |
| — Presentation deck | **Done** — `presentation/sephora_pipeline_deck.html`, 9 slides timed to 8:00, every slide rendered and visually inspected at 1600×900. Supersedes the 8-slide PowerPoint, which is kept and marked stale |
| — Diagrams | **Done** — architecture, OLTP ER and star schema, generated by `docs/diagrams/build_diagrams.py` as SVG (deck) + PNG (Markdown). Wired into the README, replacing two Mermaid blocks |
| — Screenshots | **Partly stale by design** — the 3 the deck uses are current; the original 4 feed only `build_deck.ps1`. `docs/screenshots/README.md` marks which is which |

Stages 1–11 and all presentation deliverables are complete and verified against
real runs; the numbers in section 7 come from those runs, not from estimates.

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
| Distinct reviewer-profile combinations | 2,003 raw (of 4,200 possible) → **1,896 after cleaning**, which is `dim_reviewer_profile`'s row count |
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
| **raw → 3nf → staging reconciliation** | Products 8,494 → 8,494 → 8,494; reviews 1,093,371 → 1,093,371 → 1,093,371; **0 unexplained row gap** |
| **Historical load** (`pipeline.py --mode historical`) | 1,043,868 fact rows inserted; dims 304 / 8,494 / 503,216 / 1,896 / 5,379. Fact load 62s |
| **Idempotency, real case** (re-run full) | 1,043,868 offered, **0 inserted** everywhere |
| **Incremental load** (`pipeline.py`) | watermark 2022-12-31 → 49,503 extracted, **49,503 inserted** |
| **Idempotency, empty case** (re-run incremental) | watermark 2023-03-21 → **0 extracted**, gate skipped, 0 inserted |
| **Final warehouse** | **fact_reviews 1,093,371** — matches `staging.review` exactly. Date range 2008-08-28 → 2023-03-21, avg rating 4.2990 |
| **Quality fault injection** (`tests/unit/test_quality.py`) | 15 collected cases, all passing |
| **Airflow, historical** | All tasks green; 1,043,868 fact rows. `load_fact_from_staging` SIGKILLed on the first attempt and succeeded after chunking (D15) |
| **Airflow, incremental** | All tasks green in **22 seconds**; 49,503 rows → 1,093,371 total |
| **Airflow verification, watcher design (2026-08-12)** | `verification_historical_20260812`: success, 15 success + skipped watcher, **164s**. `verification_incremental_20260812` restored 49,503 rows in **27s**. Superseded by the teardown runs below |
| **Airflow verification, teardown design (2026-08-12, D24)** | `teardown_historical_20260812`: success, **134s**. Controlled reset removed exactly 49,503 2023 rows; `teardown_incremental_20260812` restored them in **22s**. Final fact count 1,093,371; watermark 2023-03-21; all 6 staging tables empty |
| **Failure injection (2026-08-12, D24)** | `extract_fact_to_staging` forced to `failed`. Result: 3 tasks `upstream_failed`, `cleanup_staging` **success**, **DAG run FAILED** — a green cleanup beside a red run. First attempt stranded **513,606** staging rows through a pre-existing race (cleanup waited only on `load_fact`); after wiring cleanup to all 4 staging writers, the re-run left all 6 tables at **0** |
| **Staging cleanup** | All 6 staging tables at 0 rows after every run, including the injected-failure run |
| **Analytics views** | **10** views created; all 8 full-population views reconcile to 1,093,371 exactly (`vw_rating_by_skin_type` and `vw_hype_vs_reality` are deliberate subsets) |
| **DAG structure** | 15 tasks, 21 edges; 11/11 assertions pass in-container (`load_fact_from_staging` is the only effective leaf; every task has a propagation path to it) |
| **Final test suite (2026-08-12)** | **51 passed**, 1 skipped locally (Airflow is verified separately in-container); 31 non-failing pandas DBAPI compatibility warnings |
| **Migration idempotency** | All 22 migrations re-applied against a fully-loaded database with no error |
| **Dashboard** | Both pages render via `AppTest`; KPI row equals `SELECT count(*), avg(rating) FROM dw.fact_reviews`. Each of the 3 Deep-dive sliders asserted live individually (hype gap 1,660 → 484 products, price 1,660 → 935, skin tones 12 → 14 at floor 0) |
| **Live-refresh demo, verified end to end** | `DELETE FROM dw.fact_reviews WHERE submission_date >= '2023-01-01'` → exactly 1,043,868 / watermark 2022-12-31; incremental restores 49,503 with 0 already present. `--mode historical` does **not** reset a full warehouse (no truncate anywhere, all loads `ON CONFLICT DO NOTHING`) |

### Headline analytics results (for the presentation)

| Finding | Detail |
|---|---|
| Overall | 1,093,371 reviews · avg rating **4.2990** · **83.99%** recommend |
| **BQ3 — price vs satisfaction is an inverted U** | Under $15 **4.2383** → $15-30 4.2756 → $30-50 4.3055 → **$50-100 4.3335 (peak)** → $100+ **4.2708 (falls back)**. Rating spread turns in the SAME band: stddev 1.2211 → 1.1861 → 1.1498 → **1.0996 ($50-100, tightest)** → 1.1366 ($100+, widens again). $50-100 is the sweet spot on both measures. **Not** a monotone fall — an earlier note here and in docs/07 and README claimed it was, contradicting their own tables |
| BQ1a — best brands (≥500 reviews) | MARA 4.8608 · DAMDAM 4.7394 · Dr. Lara Devgan 4.7164 |
| BQ1a — worst brands (≥500 reviews) | Topicals 3.6590 · DERMAFLASH 3.7856 · Isle of Paradise 3.8601 |
| BQ1b — categories (secondary, see D16) | By volume: Moisturizers 297,201 (4.3172) · Treatments 221,871 (4.3040) · Cleansers 200,477 (**4.3443, best**) · Mini Size 85,433 (4.2856) · Eye Care 74,966 (**4.1784**) · Masks 70,483 (4.3410) · Lip Balms 61,321 (4.3327) · Sunscreen 41,126 (**4.1665, worst**) |
| **BQ2 — hype vs reality** | Most overhyped: The Ordinary Vitamin C 23% — 132,601 loves, **3.4456** rating. The INKEY List Oat Cleansing Balm 127,819 loves / 3.6044. Sleeper hits: MACRENE actives products, ~200 loves and **4.93** ratings |
| BQ2 — trend | Volume grew 2,760 (2008) → 215,278 (2020), then eased. Rating dipped to **4.2075 in 2020** and recovered to 4.3384 by 2022 |
| BQ4 — skin type | Combination 4.3092 → dry 4.2911 → normal 4.2822 → **oily 4.2708**. Real but small spread (0.038) — worth stating as a weak signal, not a headline |
| **Review length — the assumed finding is false** | "Unhappy customers write more" does **not** hold here. Avg rating is flat across every length bucket (4.2784 → 4.3342, spread **0.056**), and 1★ reviews are the *shortest* (median 230 chars vs 283 for 3★/4★). The real signal is polarisation: as length rises, the 1★ share falls **8.15% → 3.73%** *and* the 5★ share falls **67.35% → 61.07%**, so both tails shrink together and cancel in the mean. `rating_stddev` falls monotonically 1.2555 → 1.0589 |

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
  reviews. Fixed with a **junk dimension**, `dim_reviewer_profile` (**1,896 rows**);
  `dim_customer` keeps identity only.
- **D3** **`highlights` evaluated, then dropped.** The column holds a stringified list
  (112 distinct tags, 82.4% coverage of reviewed products, 89.6% of reviews) and is a genuine
  many-to-many, which in a 3NF database would require `highlight` + `product_highlight`
  tables and in the warehouse a `dim_highlight` + bridge. Explored and measured, then cut to
  keep scope proportionate to an 8-minute presentation and to avoid many-to-many filter
  complexity in the dashboard. A sixth business question was dropped with it. `explore.py` still
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
- **D15** `load_fact_from_staging` reads in 100,000-row chunks over a server-side cursor. The
  first full run was SIGKILLed: materialising 1,043,868 rows and then building a list of
  tuples from them meant two full copies resident at once.
- **D16** Category analysis runs at the **secondary** level. Every reviewed product is
  `Skincare` at the primary level, so a primary-category chart is a single bar.
- **D17** Three named load modes — `full` (no date bound), `historical` (before 2023-01-01,
  the demo baseline), `incremental` (after the watermark). The old `--full-reload` stopped at
  2023 while claiming to be full, and there was no way to load everything in one command.
- **D18** **Streamlit instead of Power BI.** The dashboard lives in the repo: versioned,
  diffable, testable, reproducible with one command. Cost stated honestly — DAX and the Power
  BI model are not demonstrated by this project.
- **D19** Every dropped row is counted against a named reason, zeros included, and an
  unexplained gap raises `ReconciliationError`. Dropping rows is allowed; dropping them
  without saying how many and why is not.
- **D20** *(superseded by D24)* `cleanup_staging` uses `all_done` so failures still clean up —
  which made it the only leaf, and Airflow derives run state from leaves, so a failed extract
  produced a **green** run over an empty warehouse. First fixed with a `watch_for_failure`
  watcher wired downstream of all 15 other tasks.
- **D24** The watcher is replaced by marking `cleanup_staging` `.as_teardown()`. Airflow
  excludes ignorable teardowns from run-state calculation, so `load_fact_from_staging` becomes
  the sole effective leaf and failure propagates to it — same guarantee, **15 tasks / 21 edges**
  instead of 16 / 33. `on_failure_fail_dagrun` **must stay False**: setting it True makes
  cleanup the sole leaf again and reinstates D20's bug. Proven by injecting a failure, which
  also exposed a pre-existing race that stranded 513,606 staging rows; cleanup now waits on
  every staging writer.
- **D21** Quality checks carry a severity. `hard_failure` halts before any write; `warning`
  logs and continues. All-fatal sounds rigorous but means the only checks worth writing are
  ones you would stop production for.
- **D22** `sql/analytics/views/` (DDL, changes the database) is separate from
  `sql/validation/` (read-only assertions, changes nothing). Opposite jobs.
- **D23** Dashboard controls are **query parameters, not dataframe filters**, and
  the data-quality panel **recomputes rather than reads a stored summary**. Each
  slider binds into the SQL (`WHERE hype_gap >= %s`, `BETWEEN %s AND %s`,
  `HAVING sum(review_count) >= %s`); a client-side filter would look identical on
  screen and be a different claim. The panel distinguishes **held back** from
  **lost**: at the historical baseline the warehouse is legitimately 49,503 rows
  behind staging, and a panel that called that a shortfall would be lying at
  exactly the moment it is on screen during the demo.

### Deliberate deviations from the reference project

| Deviation | Why |
|---|---|
| Explicit `3nf` schema between `raw` and `staging` | Course goal #3 requires a 3NF OLTP; the reference's OLTP was a source mirror only |
| Script-based ingestion (`ingest.py`, `COPY`) | The reference imported CSVs by hand in DBeaver — its own checklist calls that a gap. 1.09M rows makes manual import impractical |
| No bridge tables | The one genuine many-to-many in this dataset (`highlights`) was deliberately descoped — see D3 |
| Junk dimension `dim_reviewer_profile` | The reference had no analog; four correlated low-cardinality attributes is the textbook case |
| `dim_customer` carries no descriptive attributes | See D2 |
| **Streamlit instead of Power BI** | The dashboard becomes part of the repo — versioned, diffable, testable in CI, reproducible with one command. The cost (no DAX, no Power BI model demonstrated) is stated in D18 rather than hidden |
| **A teardown-based failure guarantee** | The reference's DAG had no `all_done` cleanup task, so it never hit the bug where a failed run reports success (D20 → D24) |
| **Enforced row reconciliation** | The reference dropped unmatched rows with a log line. Counting every drop against a named reason and raising on an unexplained gap is stricter than the pattern taught (D19) |

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
