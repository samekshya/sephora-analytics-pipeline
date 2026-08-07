# 04 — Schema Documentation

Every table in both databases: grain, keys, columns, and why it is shaped that
way. Row counts were queried from the live database on **2026-08-08**.

---

# `sephora_oltp`

## `raw` schema — landing zone

1:1 mirror of the cleaned CSVs plus a `source_file` column. **Every source
column is kept**, including ones nothing downstream uses, because this layer's
only job is traceability (**D14**).

| Table | Grain | Rows | Key |
|---|---|---|---|
| `raw.product_info` | one row per product | 8,494 | none enforced |
| `raw.reviews` | one row per review | 1,093,371 | none enforced |

No constraints beyond column types. A landing zone that rejects rows cannot
tell you what the source actually contained.

---

## `3nf` schema — normalized OLTP

Nine tables. Every foreign key is **enforced by Postgres**, not implied by
naming. Third normal form: every non-key attribute depends on the key, the
whole key, and nothing but the key.

### `brand` — 304 rows

| Column | Type | Notes |
|---|---|---|
| `brand_id` | `INTEGER` | **PK**, from the source |
| `brand_name` | `TEXT NOT NULL` | `UNIQUE` |

Keyed on the source's own `brand_id` rather than a new surrogate, because
`brand_id → brand_name` was verified strictly 1:1 across all 8,494 products
(and `clean.py` asserts it, so a violation stops the pipeline).

**This table is the reason `brand_name` does not belong on `product`**: it
depends on `brand_id`, not on `product_id` — a transitive dependency, which is
exactly what 3NF removes.

### `category` — 174 rows

| Column | Type | Notes |
|---|---|---|
| `category_id` | `SERIAL` | **PK** |
| `primary_category` | `TEXT NOT NULL` | |
| `secondary_category` | `TEXT` | nullable — 8 products have none |
| `tertiary_category` | `TEXT` | nullable — 990 products have none |

`UNIQUE NULLS NOT DISTINCT (primary, secondary, tertiary)`. The
`NULLS NOT DISTINCT` matters: SQL treats `NULL ≠ NULL`, so a plain `UNIQUE`
would happily accept two identical rows whose secondary and tertiary are both
null.

Keyed on the **full triple**, deliberately not modelled as three nested levels
(**D1**) — see [02](02_data_quality_findings.md) §4.5.

### `product` — 8,494 rows

| Column | Type | Notes |
|---|---|---|
| `product_id` | `TEXT` | **PK** |
| `product_name` | `TEXT NOT NULL` | |
| `brand_id` | `INTEGER NOT NULL` | **FK →** `brand` |
| `category_id` | `INTEGER NOT NULL` | **FK →** `category` |
| `price_usd` | `NUMERIC(10,2) NOT NULL` | `CHECK (> 0)` |
| `size`, `variation_type`, `variation_value` | `TEXT` | nullable |
| `loves_count` | `INTEGER NOT NULL` | `CHECK (>= 0)` |
| `rating` | `NUMERIC(6,4)` | `CHECK (BETWEEN 1 AND 5)` |
| `reviews` | `INTEGER` | the source's own count — kept for reconciliation, **never used as a measure** |
| `child_count` | `INTEGER NOT NULL` | `CHECK (>= 0)` |
| 5 boolean flags | `BOOLEAN NOT NULL` | `limited_edition`, `new`, `online_only`, `out_of_stock`, `sephora_exclusive` |

Indexes on `brand_id` and `category_id`.

**Dropped at this boundary** (D14): `highlights` (breaks 1NF, descoped — D3),
`ingredients`, `value_price_usd` (94.7% null), `sale_price_usd` (96.8%),
`child_max_price`/`child_min_price` (67.6%), `variation_desc` (85.3%).

### `author` — 503,216 rows

| Column | Type |
|---|---|
| `author_id` | `TEXT` **PK** |

**Identity only.** No `skin_tone`, `skin_type`, `eye_color` or `hair_color` —
those are not functionally dependent on `author_id` (**D2**).

### `skin_tone` / `skin_type` / `eye_color` / `hair_color` — 13 / 4 / 5 / 7 rows

Each: `<name>_id SERIAL PK`, `<name> TEXT NOT NULL UNIQUE`.

The `UNIQUE` constraint is what makes the `'Grey'`/`'gray'` defect impossible to
reintroduce: a second spelling would need a new lookup row and would fail the FK.

`skin_tone` is 13 rather than 14 because `'notSureST'` was a placeholder, mapped
to NULL during cleaning.

### `review` — 1,093,371 rows

| Column | Type | Notes |
|---|---|---|
| `review_id` | `BIGSERIAL` | **PK** |
| `source_row_id` | `BIGINT NOT NULL` | from the CSV index |
| `source_file` | `TEXT NOT NULL` | which CSV it came from |
| `author_id` | `TEXT NOT NULL` | **FK →** `author` |
| `product_id` | `TEXT NOT NULL` | **FK →** `product` |
| `submission_date` | `DATE NOT NULL` | indexed — the watermark column |
| `rating` | `SMALLINT NOT NULL` | `CHECK (BETWEEN 1 AND 5)` |
| `is_recommended` | `BOOLEAN` | nullable — 167,988 don't say |
| `helpfulness` | `NUMERIC(18,16)` | nullable, **never imputed** (D5) |
| `total_feedback_count` | `INTEGER NOT NULL` | `CHECK (>= 0)` |
| `total_pos_feedback_count` | `INTEGER NOT NULL` | `CHECK (>= 0)` |
| `total_neg_feedback_count` | `INTEGER NOT NULL` | `CHECK (>= 0)` |
| `review_text` / `review_title` | `TEXT` | **stops here** (D6) |
| `review_length` | `INTEGER` | `CHECK (>= 0)` |
| `skin_tone_id` … `hair_color_id` | `INTEGER` | **FK →** the four lookups, all **nullable** |

**Constraints that encode findings rather than merely documenting them:**

```sql
UNIQUE (source_row_id, product_id)                              -- idempotency key (D13)
CHECK (pos_feedback + neg_feedback = total_feedback)            -- verified on all 1.09M rows
CHECK ((helpfulness IS NULL) = (total_feedback_count = 0))      -- the D5 invariant
```

The four attribute FKs are nullable, and the load uses `LEFT JOIN`, because an
inner join would drop every review that left an attribute blank — between 111K
and 227K rows each. A blank answer is still a review.

---

## `staging` schema — analytics-ready

De-normalized again on purpose: `extract.py` stays a plain `SELECT` per table
instead of carrying join logic in Python.

| Table | Grain | Rows |
|---|---|---|
| `staging.product` | one row per product | 8,494 |
| `staging.review` | one row per review | 1,093,371 |

`staging.product` flattens `brand_name` and all three category levels back in.
`staging.review` resolves the four attribute FKs back to text and **coalesces
NULL → `'Unknown'`**, has no `review_text`, and is indexed on
`submission_date`, `product_id` and `author_id`.

Both are truncate-and-reload: staging is a derived view of `3nf`, not a system
of record.

---

# `sephora_dw`

## `dw` schema — star schema

**Grain of the fact table: one row per review.**

Deliberately *not* normalized. `dim_product` repeats brand name and all three
category levels on every row; that redundancy buys single-join dashboard
queries. The normalized version of the same data lives in `3nf`.

### `dim_date` — 5,379 rows

| Column | Type | Notes |
|---|---|---|
| `date_key` | `INTEGER` | **PK**, `YYYYMMDD` (**D12**) |
| `full_date` | `DATE NOT NULL` | `UNIQUE` |
| `year`, `quarter`, `month`, `week`, `day`, `day_of_week` | `INTEGER` | with `CHECK` ranges |
| `month_name`, `day_name` | `VARCHAR(10)` | |
| `is_weekend` | `BOOLEAN NOT NULL` | |

Generated by `generate_series` in SQL, over a range **derived from the data**
(min/max `submission_date` ± 30 days), not hardcoded. It cannot be seeded by a
static migration because staging lives in a different database (D7), and a
hardcoded range would go stale the moment newer reviews arrive.

### `dim_brand` — 304 rows

`brand_key SERIAL PK` · `brand_id INTEGER NOT NULL UNIQUE` · `brand_name TEXT NOT NULL`

`brand_id` is the business key, so `ON CONFLICT` has a target and a re-run is a
no-op.

### `dim_product` — 8,494 rows

| Column | Type | Notes |
|---|---|---|
| `product_key` | `INTEGER` | **PK** (serial) |
| `product_id` | `TEXT NOT NULL` | `UNIQUE` — business key |
| `product_name` | `TEXT NOT NULL` | |
| `brand_key` | `INTEGER NOT NULL` | **FK →** `dim_brand` |
| `primary_category` | `TEXT NOT NULL` | flattened, not snowflaked |
| `secondary_category`, `tertiary_category` | `TEXT` | nullable |
| `price_usd` | `NUMERIC(10,2) NOT NULL` | |
| `price_band` | `TEXT NOT NULL` | **derived in `transform.py`**, not in the source |
| `size` | `TEXT` | nullable |
| `loves_count` | `INTEGER NOT NULL` | |
| 5 boolean flags | `BOOLEAN NOT NULL` | |

Category is **flattened**; brand **is** snowflaked to `dim_brand`. Brand is a
genuine analytic entity in its own right (BQ1) and 304 rows makes the join
cheap; the category levels are filtered and grouped on constantly, and a star
schema pays for that with redundancy rather than joins.

`price_band` is computed once in the ETL so every visual grouping by price uses
identical boundaries — `[0, 15, 30, 50, 100, ∞)`, left-closed. Computing bands
per-visual is how two charts end up disagreeing.

### `dim_customer` — 503,216 rows

`customer_key SERIAL PK` · `customer_id TEXT NOT NULL UNIQUE`

**Identity only** — the single most important decision in this warehouse
(**D2**). See [02](02_data_quality_findings.md) §3.

### `dim_reviewer_profile` — 1,896 rows

`reviewer_profile_key SERIAL PK` · `skin_tone` · `skin_type` · `eye_color` ·
`hair_color`, all `TEXT NOT NULL`, `UNIQUE` on all four together.

A **junk dimension**: one row per distinct combination of four low-cardinality,
correlated attributes. Four separate dimensions would mean four more FK columns
on a 1.09M-row fact table for no analytic gain; four text columns on the fact
would mean 1.09M repeated strings.

> 1,896 rows, **not 2,003**. 2,003 is the count of distinct combinations in the
> raw data; cleaning (`'notSureST'` → `'Unknown'`, `'Grey'` → `'gray'`)
> collapses it to 1,896. Older documents cited 2,003 for the loaded table,
> which was wrong.

No NULL members — missing answers became `'Unknown'` at the staging boundary,
because a junk dimension with NULLs cannot be filtered on, and "declined to
say" is a real answer.

### `fact_reviews` — 1,093,371 rows

| Column | Type | Role |
|---|---|---|
| `review_key` | `INTEGER` | **PK** (serial) |
| `source_row_id` | `BIGINT NOT NULL` | business key |
| `product_id` | `TEXT NOT NULL` | business key |
| `product_key` | `INTEGER NOT NULL` | **FK →** `dim_product` |
| `customer_key` | `INTEGER NOT NULL` | **FK →** `dim_customer` |
| `reviewer_profile_key` | `INTEGER NOT NULL` | **FK →** `dim_reviewer_profile` |
| `date_key` | `INTEGER NOT NULL` | **FK →** `dim_date` |
| `rating` | `SMALLINT NOT NULL` | measure, `CHECK (1–5)` |
| `is_recommended` | `BOOLEAN` | measure, nullable |
| `helpfulness` | `NUMERIC(18,16)` | measure, nullable, never imputed |
| `total_feedback_count` | `INTEGER NOT NULL` | measure, `CHECK (>= 0)` |
| `total_pos_feedback_count` | `INTEGER NOT NULL` | measure, `CHECK (>= 0)` |
| `total_neg_feedback_count` | `INTEGER NOT NULL` | measure, `CHECK (>= 0)` |
| `review_length` | `INTEGER` | measure, `CHECK (>= 0)` |
| `submission_date` | `DATE NOT NULL` | degenerate — the watermark |

```sql
UNIQUE (source_row_id, product_id)                      -- drives ON CONFLICT DO NOTHING
CHECK (pos_feedback + neg_feedback = total_feedback)    -- restated from 3nf.review
```

**No `brand_key`** (**D11**). Brand is functionally determined by product, so a
copy on the fact adds no information while creating a way for the two to
disagree after a bad load. Brand analysis joins through `dim_product`.

**No `review_text`** (**D6**). 350 MB of free text has no place at this grain;
`review_length` carries the one analytically useful property in 4 bytes.

`submission_date` is kept **alongside** `date_key` even though they are
redundant: the watermark needs `MAX()` of a real date, and unpacking that from
an integer key on every incremental run is the kind of cleverness that breaks
quietly.

**Indexes**: one per dimension FK, plus `submission_date`. At 1.09M rows every
dashboard visual is a join through one of these, and the star schema's whole
performance argument depends on them existing.

### `stg_*` tables — 6, transient

`stg_dim_brand`, `stg_dim_product`, `stg_dim_customer`,
`stg_dim_reviewer_profile`, `stg_fact_extract`, `stg_fact_transformed`.

Each carries a `batch_id` (the Airflow `run_id`) and is indexed on it. They hold
a run's intermediate results so each DAG stage is independently retryable, and
`cleanup_staging` empties them at the end of every run — including failed ones.
**All six are at 0 rows between runs.**

### Views — 9

Documented in [`dashboard/data_model.md`](../dashboard/data_model.md) and
[07](07_dashboard_insights.md).

---

## Referential integrity, verified

```sql
-- 0 on every run
SELECT count(*) FROM dw.fact_reviews f
LEFT JOIN dw.dim_product p ON p.product_key = f.product_key
LEFT JOIN dw.dim_customer c ON c.customer_key = f.customer_key
LEFT JOIN dw.dim_reviewer_profile rp ON rp.reviewer_profile_key = f.reviewer_profile_key
LEFT JOIN dw.dim_date d ON d.date_key = f.date_key
WHERE p.product_key IS NULL OR c.customer_key IS NULL
   OR rp.reviewer_profile_key IS NULL OR d.date_key IS NULL;
```

Asserted by `tests/integration/test_pipeline_reconciliation.py` and by
`sql/validation/dashboard_checks.sql` §4.
