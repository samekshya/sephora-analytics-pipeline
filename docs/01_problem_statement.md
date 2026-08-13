# 01 — Problem Statement

## Background

Sephora sells thousands of products across hundreds of brands, and customers
leave over a million reviews against them. The product catalogue and the review
stream live in different files with different grains, and the review file
repeats product attributes on every row. Answering a basic question — *does a
higher price actually buy a better-rated product?* — means reconciling those
files by hand every time.

## Goal

Build an end-to-end data engineering pipeline that explores, cleans,
normalizes, models and loads Sephora product and review data into an
analytics-ready warehouse, orchestrated by Airflow, with a dashboard on top.

## Data source

**[Sephora Products and Skincare Reviews](https://www.kaggle.com/datasets/nadyinky/sephora-products-and-skincare-reviews)**
(Kaggle) — scraped from Sephora's US site in March 2023.

| | |
|---|---|
| Format | CSV — one product catalogue file, five review files split by product range |
| Products | 8,494 |
| Reviews | 1,094,411 raw → 1,093,371 after deduplication |
| Reviewers | 503,216 |
| Brands | 304 |
| Date range | 2008-08-28 → 2023-03-21 |

**Why this dataset**: the two sides join cleanly on a real key, the review
volume is large enough to make incremental loading a genuine requirement rather
than a demonstration, and the reviewer attributes create a real modelling
problem worth solving (see [02](02_data_quality_findings.md) §3 and D2).

Every figure in these documents was produced by `explore.py` against the actual
files, or queried from the live database. Nothing is taken from the dataset's
own description.

## Business questions

The dashboard and the analytics views answer exactly these five. Adding or
dropping one requires a decision-log entry.

| # | Question | Answered by |
|---|---|---|
| **BQ1** | Which brands and categories earn the highest ratings, and which underperform? | `vw_rating_by_brand`, `vw_rating_by_category` |
| **BQ2** | Hype vs reality — which products have high `loves_count` but low ratings? | `vw_hype_vs_reality` |
| **BQ3** | Does price predict satisfaction — do expensive products actually rate better? | `vw_rating_by_price_band` |
| **BQ4** | Do reviewers with different skin types and tones rate the same products differently? | `vw_rating_by_skin_type`, `vw_rating_by_skin_tone` |
| **BQ5** | How do review volume and average rating trend over time? | `vw_review_volume_by_month` |

A sixth question — *which product attributes (Vegan, Clean at Sephora…)
correlate with rating?* — was evaluated against the data and deliberately
dropped. See [02](02_data_quality_findings.md) §5 and **D3**.

## Non-functional requirements

| Requirement | How it is met | Evidence |
|---|---|---|
| **Traceability** | Every warehouse row traces to a raw source record via `(source_row_id, product_id)`; the `raw` schema keeps every source column | D13, D14 |
| **Idempotency** | `ON CONFLICT … DO NOTHING` on every load; re-running inserts 0 | `tests/unit/test_transform.py::test_reconcile_load_idempotent_rerun` |
| **Incremental capability** | Watermark on `MAX(submission_date)`; new reviews load without reprocessing history | [05](05_etl_and_incremental_loading.md) |
| **No silent data loss** | Every dropped row is counted against a named reason; unexplained gaps raise | `etl/reconcile.py`, D19 |
| **Visibility** | Structured logging throughout; failures fail loudly, and a failed DAG run reports failed | D20 → D24 (cleanup as teardown) |

## Explicitly out of scope

Stated so the boundary is a decision rather than an omission.

- **Real-time / streaming ingestion** — the source is a static batch export.
- **Sentiment analysis or NLP on review text** — the text is kept in the OLTP
  layer for traceability, but no business question needs it (D6).
- **`highlights` and `ingredients`** — evaluated and measured during
  exploration, then descoped (D3). The `highlights` column is a *genuine*
  many-to-many; it was cut for scope, not because the domain lacks one.
- **External API enrichment** — no business question required data the source
  files don't carry.
- **Cloud deployment, Spark, object storage** — future work, not built.
- **Product recommendation modelling** — an analytics/ML problem, not a data
  engineering one.
- **`EXPLAIN ANALYZE` before/after capture** — indexes were created
  deliberately with stated reasons, but no performance comparison was recorded.

## Related documents

- [02 — Data quality findings](02_data_quality_findings.md)
- [03 — Architecture](03_architecture.md)
- [09 — Decision log](09_decision_log.md)
