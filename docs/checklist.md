# Production Requirements Checklist

**Project**: Sephora Reviews Analytics Warehouse
**Stack**: Python, PostgreSQL 16, Airflow 3.3.0, Power BI
**Purpose**: track engineering discipline against what the course covered, so the final
project demonstrates real practice rather than a script that happens to run.

---

## 1. Data Ingestion
- [x] Ingest all raw CSVs into a `raw` schema with every source column retained
- [x] Ingestion is script-based (`ingest.py`, `COPY`), not a manual client import
- [x] Credentials loaded via `.env` / `python-dotenv`, never hardcoded
- [x] Transactional loader — truncate and reload inside one transaction, rolls back on a
      partial load rather than committing it
- [x] Loaded counts asserted against the counts cleaning reported (8,494 / 1,093,371)

## 2. Data Cleaning & Standardisation
- [x] Null handling documented and applied consistently — NULL FK in `3nf`, `'Unknown'` at
      the staging boundary, and the reasoning for the difference written down (D5, D14)
- [x] Type casting enforced (dates as `DATE`, costs as `NUMERIC`, flags as `BOOLEAN`)
- [x] Value standardisation — `'Grey'`/`'gray'` collapsed, `'notSureST'` placeholder removed
- [x] Deduplication applied and justified with both candidate keys measured (1,040 vs 5,525)
- [x] Every cleaning rule logs rows in / out / dropped

## 3. Data Modelling
- [x] Explicit grain statement for the fact table — one row per review, written in the DDL
- [x] Three-layer OLTP: `raw` (traceability), `3nf` (normalised), `staging` (analytics-ready)
- [x] Genuine 3NF — no transitive dependencies; brand, category and the four reviewer
      attributes all extracted to their own tables
- [x] Star schema: `fact_reviews` + `dim_product`, `dim_brand`, `dim_customer`,
      `dim_reviewer_profile`, `dim_date`
- [x] Foreign keys actually enforced in Postgres, not implied by naming
- [x] Junk dimension for the four correlated low-cardinality attributes (D2)
- [ ] External API enrichment — not attempted; no business question needed it

## 4. Incremental Loading
- [x] Watermark pattern — `MAX(submission_date)` read from the fact table itself
- [x] Watermark captured before any write in the run, so it cannot advance past rows the same
      run is loading
- [x] Static source, so incremental behaviour is demonstrated by splitting real data
      chronologically at 2023-01-01 (49,503 rows held back) rather than generating fake rows
- [x] Documented which tables are incremental (fact only) and which are full every run
      (all dimensions) and why (D10)

## 5. Idempotency
- [x] `INSERT ... ON CONFLICT DO NOTHING` on every dimension and fact load
- [x] Every table has a business key the conflict clause can target
- [x] Raw layer uses truncate-and-reload in a single transaction
- [x] Explicitly tested — full reload re-run inserted **0** rows; incremental re-run
      extracted **0** rows
- [x] DAG task retries don't duplicate staged rows (batch_id deleted before re-staging)

## 6. Modularity
- [x] Separate module per concern: `extract.py` / `transform.py` / `quality.py` / `load.py`
- [x] One function per table rather than one generic loop
- [x] Airflow tasks map 1:1 to those functions — no inline SQL or pandas in the DAG file
- [x] DAG tasks generated from a config list rather than hand-copied, so they cannot drift
- [x] Config centralised in `.env`; connection strings supplied to Airflow as env vars

## 7. Logging & Error Handling
- [x] Every script logs rows read, rows written and errors — structured logging, not `print()`
- [x] Timestamped per-run log files in `logs/`
- [x] Loaders wrapped in try/except with rollback and a meaningful message
- [x] Cleaning raises rather than warns where a violation would break a downstream key
- [x] Row counts measured by `COUNT(*)` before and after, not `cursor.rowcount` — which
      reports only the last page under `execute_values` and gave a wrong number until fixed

## 8. Query & Performance Awareness
- [x] Index on every fact foreign key, plus the watermark column
- [x] Indexes created deliberately with the reason stated in the DDL comment
- [x] Views in the warehouse backing the dashboard (6 of them), so logic is versioned
- [x] Bulk loading via `execute_values` with a tuned page size, and chunked reads over a
      server-side cursor where memory would otherwise be the limit
- [ ] `EXPLAIN ANALYZE` before/after comparison — not captured

## 9. Orchestration (Airflow)
- [x] Full pipeline runs as a single DAG
- [x] Explicit task dependencies, parallel dimension branches
- [x] Fact split into extract / transform / quality / load for per-stage retry
- [x] Retry policy configured (2 retries, 5-minute delay)
- [x] Quality failures raise `AirflowFailException` so bad data fails fast instead of
      consuming the retry budget
- [x] `cleanup_staging` with `trigger_rule="all_done"` so failed runs still clean up
- [x] DAG re-runnable without duplicating data

## 10. Data Quality Testing
- [x] Not-null checks on every surrogate key
- [x] Row count reconciliation raw → 3nf → staging, with any gap reported
- [x] Business-rule checks — rating in 1–5, counts non-negative, feedback split sums
- [x] Two invariants enforced as `CHECK` constraints, not just observed
- [x] Quality checks run inside the DAG with visible pass/fail per table
- [x] Fault injection — 8 cases proving the gate rejects bad data, not just accepts good

## 11. Version Control
- [x] Meaningful commit history, one commit per step
- [x] A branch per project phase, merged to `main` with `--no-ff` so the phase structure
      stays visible in the graph
- [x] `.gitignore` excludes `.env`, `data/`, `logs/` and the reference material

## 12. Analytics Output
- [x] Views answering all four locked business questions
- [x] Logic in versioned SQL rather than trapped inside the Power BI file
- [x] KPI view states products reviewed alongside products in catalogue, so coverage isn't
      overstated
- [ ] Power BI dashboard built — see README
- [ ] At least one DAX measure

## 13. Documentation
- [x] README with setup instructions someone else could follow
- [x] Problem statement and data source documentation with measured profiling
- [x] Decision log, written as decisions were made rather than reconstructed at the end
- [x] Architecture diagram and ERD (mermaid, in the README)
- [x] Explicit out-of-scope section
- [x] `CLAUDE.md` as a single source of truth for status and measured numbers

---

## Notes

Unchecked items are deliberate, not forgotten: no external API enrichment (no business
question needed it), and no `EXPLAIN ANALYZE` capture. The Power BI items need the desktop
application and are the remaining manual step.
