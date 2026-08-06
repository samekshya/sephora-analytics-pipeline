# 09 — Decision Log

This log captures the significant design and scoping decisions made during the project, in the
order they were made, along with the reasoning behind each. The goal is traceability of
*thinking*, not just of data — anyone reading this should understand why the project looks the
way it does, not just what it looks like.

Entries are never renumbered or removed, even if a later decision reverses an earlier one — the
log is a history, not a current-state summary.

---

## D1. Category is keyed on the (primary, secondary, tertiary) triple, not modelled as a hierarchy

**Date**: 2026-08-06

**Decision**: `3nf.category` is one row per distinct
`(primary_category, secondary_category, tertiary_category)` combination — 174 rows — with a
UNIQUE constraint across all three. The warehouse flattens all three onto `dim_product`.

**Why**: the obvious design is three nested levels, primary → secondary → tertiary. The data
doesn't support it. Checked directly: one `secondary_category` appears under as many as **7
different primaries** (`Value & Gift Sets` under 7, `Mini Size` under 5, and `Brushes &
Applicators`, `Hair`, `Candles & Home Scents`, `Self Tanners`, `Shop by Concern`, `Skincare`,
`Sunscreen` each under 2). Modelling it as a hierarchy would assert a parent-child relationship
that doesn't exist, and any drill-down built on it would produce wrong totals. The triple is
what the data actually is.

---

## D2. Reviewer attributes live on the review, held in a junk dimension — not on the customer

**Date**: 2026-08-06

**Decision**: `dim_customer` holds identity only (`customer_key`, `customer_id`). The four
reviewer attributes move into `dim_reviewer_profile`, a junk dimension holding one row per
distinct `(skin_tone, skin_type, eye_color, hair_color)` combination — 2,003 rows. In the OLTP
layer they sit on `3nf.review` as FKs to four small lookup tables.

**Why**: an earlier hand-written schema of mine (`reference/02_warehouse_schema.sql`) modelled
these as attributes of `dim_customer`, keyed `UNIQUE (customer_id)`. Tested against the data
before building on it:

| Attribute | Authors with >1 distinct value | Max distinct |
|---|---|---|
| `skin_tone` | 12,525 | 4 |
| `skin_type` | 8,387 | 4 |
| `hair_color` | 7,614 | 4 |
| `eye_color` | 827 | 3 |

In total **22,503 of 503,216 authors (4.47%)** do not have a constant profile, and because
prolific reviewers are disproportionately among them, those authors account for **149,788
reviews — 13.69% of the dataset**.

One row per customer forces one profile per person, so ~1 review in 7 would be tagged with a
profile the reviewer didn't record on that review — silently, with no error, no constraint
violation, and no way to notice downstream. It would corrupt business question #4 specifically,
which is the question those attributes exist to answer.

**Alternatives rejected**: SCD Type 2 on the customer would model the change over time
correctly, but the source has no reliable change events or effective dates to build it from —
the values simply differ between submissions. Putting the four columns directly on
`fact_reviews` would work but means 1M rows carrying four repeated text values.

A junk dimension is the standard Kimball treatment for exactly this: several low-cardinality,
correlated attributes that don't justify separate dimensions. 2,003 rows of the 4,200
theoretically possible combinations actually occur.

---

## D3. `highlights` evaluated, then descoped

**Date**: 2026-08-06

**Decision**: the `highlights` column is dropped at the cleaning step. Business question #5
("which product attributes correlate with rating?") is dropped with it. The project answers
four business questions and has no bridge tables.

**Why**: `highlights` holds a stringified list — `"['Vegan', 'Hydrating', 'Cruelty-Free']"` —
and is the dataset's one genuine many-to-many. Profiled before deciding: **112 distinct tags**,
2,207 products with none, 4.8 tags on average for the rest, 30,204 total product-tag pairs,
covering **82.4% of reviewed products and 89.6% of all reviews**.

A cell holding several values breaks **1NF**, so keeping the column honestly would require
`highlight` + `product_highlight` in the 3NF layer and `dim_highlight` + a bridge in the
warehouse. Storing the raw comma-list in a text column was never an option — it would make the
project's 3NF claim false.

Weighed against an 8-minute presentation and the many-to-many filter complexity a bridge
introduces in Power BI, the column was cut. The cost is real and acknowledged: it removes the
only many-to-many modelling problem in the project.

`explore.py::explore_highlights()` stays in the script and still reports the full tag
distribution, so this is a measured decision rather than an oversight. `ingredients` is dropped
on the same basis without the same analysis — no locked question came close to needing it.

---

## D4. Deduplication key includes the submission date

**Date**: 2026-08-06

**Decision**: reviews are deduplicated on `(author_id, product_id, submission_time)`, removing
1,040 rows.

**Why**: the obvious key is `(author_id, product_id)` — one review per person per product. That
would remove **5,525** rows. The triple removes only **1,040**. The 4,485-row difference is the
same author reviewing the same product on genuinely different dates, which the source clearly
supports and which is real user behaviour (re-reviewing after longer use). Deduplicating on the
pair would silently delete 4,485 real reviews. Both numbers are recorded here so the choice is
auditable rather than asserted.

---

## D5. `helpfulness` NULLs are never imputed

**Date**: 2026-08-06

**Decision**: `helpfulness` stays NULL where the source has no value. Every helpfulness measure
in the dashboard filters on `total_feedback_count > 0`.

**Why**: 561,592 rows have a NULL `helpfulness` — over half the dataset, which looks alarming
until you check what drives it. `helpfulness IS NULL` corresponds to `total_feedback_count = 0`
on **all 1,094,411 rows, with 0 disagreements**. The value is undefined because nobody has voted
on the review yet, not missing because something went wrong.

Filling it with 0 would assert "everyone who voted found this unhelpful" — a different and false
claim, and one that would drag every average toward zero in proportion to how new a review is.
The feedback counts were also confirmed internally consistent: `pos + neg = total` on every row,
0 exceptions.

---

## D6. Review text stops at the OLTP boundary

**Date**: 2026-08-06

**Decision**: `review_text` and `review_title` are stored in `3nf.review` for traceability but
do not reach `staging` or the warehouse. `fact_reviews` carries `review_length` instead.

**Why**: measured at **350 MB** across 1.09M rows (min 8 characters, median 263, mean 321, max
6,448). Carrying that into a fact table would slow every load and every scan to serve a question
no locked business question asks — sentiment and NLP are explicitly out of scope. `review_length`
preserves the one property that is analytically interesting (do longer reviews rate differently?)
at 4 bytes per row. The full text remains one join away in the OLTP database if it's ever needed.

---

## D7. Two physically separate databases

**Date**: 2026-08-06

**Decision**: `sephora_oltp` (schemas `raw`, `3nf`, `staging`) and `sephora_dw` (schema `dw`) as
two separate Postgres databases, not one database with more schemas.

**Why**: OLTP-shaped data (normalized, source-mirroring) and OLAP-shaped data (denormalized,
query-optimized) are conceptually different systems. Separating them physically makes the
pipeline boundary concrete and demonstrable — "here is my source system, here is my warehouse,
here is the pipeline between them" — which is a clearer story than schema prefixes inside one
database.

**Trade-off accepted**: moving data across the boundary requires Python holding two connections,
rather than a single cross-schema `INSERT … SELECT`, since Postgres can't join across databases
without `dblink`/`postgres_fdw`.

---

## D8. Incremental loading demonstrated by splitting real data at 2023-01-01

**Date**: 2026-08-06

**Decision**: reviews before 2023-01-01 are the full load (1,044,880 rows before dedup);
reviews from 2023-01-01 onward are held back as the incremental batch (49,531 rows — January
16,907, February 16,754, March 15,870).

**Why**: the source is a static export, so incremental behaviour has to be simulated somehow.
Generating synthetic new reviews with Faker would mean fabricating internally consistent rows
(real author IDs, real product IDs, plausible ratings and feedback counts) — non-trivial work
that produces fake data. Splitting the real data chronologically achieves the same
demonstration — a watermark advancing across multiple runs — using real rows, at zero
engineering cost. Three months at ~16K rows each is enough volume to be visible in the row
counts and to run the watermark more than once.

---

## D9. Postgres generates every surrogate key, not pandas

**Date**: 2026-08-06

**Decision**: every dimension key is `serial`. `load.py` inserts keyless; a post-load lookup
reads the keys back once the rows exist.

**Why**: the dimension branches load in parallel in the Airflow DAG. If pandas assigned the
keys, the branches would have to coordinate auto-increment state between processes. The database
already serializes that correctly, for free.

---

## D10. Dimensions load in full every run; only reviews are incremental

**Date**: 2026-08-06

**Decision**: `dim_brand`, `dim_product`, `dim_customer` and `dim_reviewer_profile` always
extract their complete source set, regardless of whether the run is full or incremental. Only
`fact_reviews` uses the watermark.

**Why**: dimensions have no time axis. If `dim_product` were built from the same date-windowed
extract used for the fact table, a review arriving in the incremental batch for a
newly-catalogued product would find no matching product key and be silently dropped by
`_drop_unmatched` — undercounting with no error. Loading dimensions in full costs seconds
(8,494 products, 304 brands) and removes the failure mode entirely.

---

## D11. `brand_key` removed from the fact table

**Date**: 2026-08-06

**Decision**: `fact_reviews` has no `brand_key`. Brand analysis joins
`fact_reviews → dim_product → dim_brand`.

**Why**: my earlier schema carried `brand_key` on both `fact_reviews` and `dim_product`. Every
product belongs to exactly one brand, so the fact-table copy carries no information the product
key doesn't already determine. What it does add is a way for the two to disagree — nothing in
the schema prevents a row pointing at product P (brand X) while its `brand_key` says brand Y.
The denormalization would save one join hop; that isn't worth a column that can silently
contradict itself.

---

## D12. `dim_date` keeps the integer `YYYYMMDD` key and a data-driven range

**Date**: 2026-08-06

**Decision**: carried over unchanged from `reference/02_warehouse_schema.sql` —
`date_key INT` in `YYYYMMDD` form, `full_date DATE UNIQUE`, and the range generated from
`MIN(submission_time) - 30` to `MAX(submission_time) + 30` with `ON CONFLICT DO NOTHING`.

**Why**: the integer key is the standard Kimball convention and sorts and joins identically to a
date. More importantly, deriving the range from the data rather than hardcoding it means the
dimension can't silently go stale when new reviews arrive past the hardcoded end — and the
`ON CONFLICT` makes re-running it safe. This was already right in the earlier schema and there
was no reason to change it.

**Verified safe**: `submission_time` has a non-midnight time component on **0 of 1,094,411
rows**. Every value is date-only, so a date-grain key and a date-grain watermark lose nothing.

---

## D13. `UNIQUE(source_row_id, product_id)` kept as the fact-table idempotency key

**Date**: 2026-08-06

**Decision**: keep the composite key from the earlier schema, targeting it with
`ON CONFLICT … DO NOTHING`.

**Why**: the source has no review ID. `source_row_id` is the CSV row index, and it **restarts at
0 in every one of the five review files** — which looks like a guaranteed collision. Tested
rather than assumed: **0 duplicate `(source_row_id, product_id)` pairs** across all 1,094,411
rows. The reason is structural, not luck — the files are split by product range, so every
product's reviews live entirely in one file, which makes the pair unique by construction.

Worth recording because the key looks broken at a glance and the reason it isn't depends on a
property of the file split that isn't obvious.

---

## D14. Cleaning does not drop columns; column trims happen once at the raw → 3NF boundary

**Date**: 2026-08-06

**Decision**: `clean.py` performs structural cleaning only — deduplication, type coercion,
whitespace trimming, value normalisation, and one derived column. Every source column survives
into `data/processed/` and therefore into the `raw` schema. Columns are dropped in exactly one
place: the `raw → 3nf` migrations.

**Why**: this project has two things that both sound like "cleaning" — removing bad rows and
removing unwanted columns. Doing both in the same step makes it impossible to tell later
whether a missing column was a deliberate scope decision or a casualty of a cleaning rule. It
also breaks the traceability requirement: a warehouse row can only be traced back to a raw
record if the raw record is complete.

Keeping `highlights` and `ingredients` in `raw` costs almost nothing — they live only in the
8,494-row product file (8.1 MB processed), not the 1.09M-row review file — while preserving the
ability to answer "what did the source actually say?" without re-reading the CSVs.

This mirrors the reference project's own rule: its `raw` schema retained every column from every
source file, with drops applied explicitly and once at the `raw → staging` boundary.

**Consequence for D3**: `highlights` is not deleted by `clean.py` as originally worded — it
reaches `raw` and is dropped at the `raw → 3nf` boundary along with `ingredients` and the sparse
pricing columns. The scoping decision is unchanged; only the place it takes effect moved.

---

## Format for future entries

New decisions follow the same shape: **Decision** (what was chosen), **Why** (the reasoning,
including what was ruled out and why), and the measured evidence where a measurement drove it.
