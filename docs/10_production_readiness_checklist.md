# 10 — Production Readiness Checklist

Self-audit against what the course covered, so the project demonstrates real
practice rather than a script that happens to run.

**Rule for this file**: an item is checked only if there is something in the
repository that proves it — a test, a migration, a measured run. Unchecked
items are listed with a reason, never quietly dropped.

Last verified: **2026-08-08**.

---

## 1. Data ingestion

- [x] All raw CSVs ingested into a `raw` schema with **every** source column retained
- [x] Script-based ingestion (`ingest.py`, `COPY`), not a manual client import
- [x] Credentials via `.env` / `python-dotenv`, never hardcoded
- [x] Transactional — truncate and reload in one transaction; rolls back rather than committing a partial load
- [x] Loaded counts asserted against what cleaning reported (8,494 / 1,093,371)
- [x] `.env.example` carries **working local defaults**, so a fresh clone connects without guessing

## 2. Data cleaning and standardisation

- [x] Null handling documented and applied consistently — NULL FK in `3nf`, `'Unknown'` at the staging boundary, and the reason for the difference written down (D5, D14)
- [x] Type casting enforced (dates as `DATE`, prices as `NUMERIC`, flags as `BOOLEAN`)
- [x] Value standardisation — `'Grey'`/`'gray'` collapsed, `'notSureST'` placeholder removed
- [x] Deduplication applied and justified with **both** candidate keys measured (1,040 vs 5,525)
- [x] Every cleaning rule logs rows in / out / dropped
- [x] Cleaning raises rather than warns where a violation would break a downstream key

## 3. Data modelling

- [x] Explicit grain statement for the fact table — one row per review, in the DDL
- [x] Three-layer OLTP: `raw` (traceability), `3nf` (normalised), `staging` (analytics-ready)
- [x] Genuine 3NF — brand, category and the four reviewer attributes all extracted
- [x] Star schema: `fact_reviews` + 5 dimensions
- [x] Foreign keys **enforced in Postgres**, not implied by naming
- [x] Junk dimension for the four correlated low-cardinality attributes (D2)
- [x] Derived attributes computed once in the ETL (`price_band`), not per-visual
- [ ] **External API enrichment** — not attempted; no business question needed data the source files don't carry
- [ ] **Bridge table / many-to-many** — the domain *does* have one (`highlights`, 112 tags, 30,204 product-tag pairs). It was **measured and deliberately descoped** (D3), not absent

## 4. Incremental loading

- [x] Watermark pattern — `MAX(submission_date)` read from the fact table itself
- [x] Watermark captured **before any write** in the run, so it cannot advance past rows the same run is loading
- [x] Strictly `>` not `>=`, so a current watermark extracts 0 rather than re-offering a day forever
- [x] Static source, so incremental is demonstrated by splitting **real** data at 2023-01-01 (49,503 rows held back) rather than generating fake rows
- [x] Documented which tables are incremental (fact only) and which are full every run (all dimensions), and why (D10)
- [x] **Three named modes** — `full` / `historical` / `incremental`, so no mode's name overstates what it loads (D17)

## 5. Idempotency

- [x] `INSERT … ON CONFLICT DO NOTHING` on every dimension and fact load
- [x] Every table has a business key the conflict clause can target
- [x] Raw layer uses truncate-and-reload in a single transaction
- [x] **Tested** — full re-run inserted **0**; incremental re-run extracted **0**
- [x] DAG task retries don't duplicate staged rows (`batch_id` deleted before re-staging)
- [x] Migrations rerunnable (`IF NOT EXISTS`), verified by re-applying all 22 against a loaded database

## 6. Modularity

- [x] Separate module per concern: `extract` / `transform` / `reconcile` / `quality` / `load` / `staging`
- [x] One function per table rather than one generic loop
- [x] Airflow tasks map 1:1 to those functions — no inline SQL or pandas in the DAG file
- [x] DAG tasks generated from a config list rather than hand-copied, so they cannot drift
- [x] `run_pipeline()` separated from CLI parsing, so the same code runs from a CLI, a test or a DAG
- [x] Config centralised in `.env`; Airflow connections built from it as env vars, so there is nothing to register by hand

## 7. Logging and error handling

- [x] Every script logs rows read, rows written and errors — structured logging, not `print()`
- [x] Timestamped per-run log files in `logs/`
- [x] Loaders wrapped in try/except with rollback and a meaningful message
- [x] Row counts measured by `COUNT(*)` before and after, **not** `cursor.rowcount` — which reports only the last page under `execute_values` and gave 3,868 instead of 1,043,868 until fixed
- [x] Quality failures carry a **severity**; hard failures halt, warnings log and continue (D21)
- [x] **Unexplained row loss raises** rather than continuing silently (D19)

## 8. Query and performance awareness

- [x] Index on every fact foreign key, plus the watermark column
- [x] Indexes created deliberately with the reason stated in the DDL comment
- [x] Views in the warehouse backing the dashboard (9), so logic is versioned rather than trapped in the app
- [x] At least one view using **window functions** — `vw_review_volume_by_month` (rolling 3-month, cumulative, `LAG` growth)
- [x] Bulk loading via `execute_values` with a tuned page size
- [x] Chunked reads over a server-side cursor where memory would otherwise be the limit (D15)
- [ ] **`EXPLAIN ANALYZE` before/after comparison** — not captured. Indexes were reasoned about, not benchmarked

## 9. Orchestration (Airflow)

- [x] Full pipeline runs as a single DAG — 16 tasks
- [x] Explicit task dependencies, parallel dimension branches
- [x] Fact split into extract / transform / quality / load for per-stage retry
- [x] Retry policy configured (2 retries, 5-minute delay)
- [x] Quality failures raise `AirflowFailException` so bad data fails fast instead of consuming the retry budget
- [x] `cleanup_staging` with `trigger_rule="all_done"` so failed runs still clean up
- [x] **Failure watcher** so `all_done` cleanup cannot leave a failed run reporting success (D20)
- [x] Watcher wiring asserted by tests, not assumed
- [x] Load mode selectable from the UI as an enum Param
- [x] DAG re-runnable without duplicating data

## 10. Data quality testing

- [x] Not-null checks on every surrogate key
- [x] Row count reconciliation `raw` → `3nf` → `staging`, with any gap reported
- [x] Business-rule checks — rating 1–5, counts non-negative, feedback split sums
- [x] Two invariants enforced as `CHECK` constraints, not just observed
- [x] Quality checks run inside the DAG with visible pass/fail per table
- [x] **Fault injection** — 15 cases proving the gate rejects bad data, not just accepts good
- [x] **Real pytest suite** — 45 tests, unit and integration separated by marker
- [x] Dashboard asserted against the warehouse it reads (`AppTest`)
- [ ] **Coverage measurement** — not run. Test count is not coverage

## 11. Version control

- [x] Meaningful commit history, one commit per step
- [x] A branch per project phase, merged to `main` with `--no-ff` so the phase structure stays visible
- [x] `.gitignore` excludes `.env`, `data/`, `logs/`, `__pycache__`, test artifacts and the reference material
- [x] No credentials committed; `.env.example` holds defaults, `.env` is ignored

## 12. Analytics output

- [x] Views answering all five business questions
- [x] Logic in versioned SQL rather than trapped inside a dashboard file
- [x] KPI view states products reviewed **alongside** products in catalogue, so coverage isn't overstated
- [x] Validation SQL separate from view DDL (D22)
- [x] Every view reconciles to `fact_reviews` — verified, all 8 full-population views at exactly 1,093,371
- [x] **Dashboard built** — Streamlit, 2 pages, live connection, interactive filters
- [x] Charts state their own caveats (truncated axes, partial final month, minimum-review floors)
- [ ] ~~At least one DAX measure~~ — **not applicable**: Streamlit was chosen over Power BI (D18). The cost is recorded there rather than hidden

## 13. Documentation

- [x] README with setup instructions someone else could follow
- [x] Problem statement and data source documentation with measured profiling
- [x] Decision log written as decisions were made, not reconstructed at the end — 22 entries
- [x] Architecture diagram and schema documentation
- [x] Explicit out-of-scope section
- [x] Airflow runbook including how to read a failed run
- [x] Testing evidence stating what each test **proves**
- [x] Dashboard docs explaining each visual and which question it answers
- [x] Reproducible setup path (`setup.ps1`, 11 steps, resumable)
- [x] `data/README.md` so someone else can source the CSVs

---

## Summary of unchecked items

Five, all deliberate:

| Item | Why |
|---|---|
| External API enrichment | No business question needed data outside the source files |
| Bridge table / many-to-many | The domain has one (`highlights`); it was measured and descoped for scope (D3). **Not** absent from the domain |
| `EXPLAIN ANALYZE` capture | Indexes reasoned about and justified in DDL comments, but never benchmarked |
| Coverage measurement | 45 tests exist and are documented by what they prove; percentage coverage was not measured |
| DAX measure | Not applicable — Streamlit chosen over Power BI (D18) |

Nothing here is unchecked because it was forgotten.
