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

> **Correction (2026-08-08)**: the loaded dimension holds **1,896 rows, not 2,003**. 2,003 is
> the number of distinct combinations in the *raw* data; cleaning collapses `'notSureST'` to
> `'Unknown'` and `'Grey'` to `'gray'` before the dimension is built. The 2,003 figure was
> measured correctly and then applied to the wrong thing. Left in place above rather than
> silently edited — the entry is a record of what was decided and known at the time.

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
correlated attributes that don't justify separate dimensions. 2,003 of the 4,200 theoretically
possible combinations occur in the raw data — 1,896 once cleaning collapses the two known
value defects, which is the loaded row count (see the correction above).

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

## D15. The fact load reads and writes in chunks

**Date**: 2026-08-06

**Decision**: `load_fact_from_staging` in the Airflow DAG reads `stg_fact_transformed` through
a server-side cursor in 100,000-row chunks and loads each chunk, rather than materialising the
whole batch.

**Why**: the first full-reload DAG run was SIGKILLed at exactly this task. Every other task
succeeded; the log ended mid-task with no traceback, and the scheduler recorded
`exit_code=<Negsignal.SIGKILL: -9>` — the signature of the process being killed rather than
failing.

The cause is that the task held two full copies of the batch at once: a DataFrame of 1,043,868
rows, and the list of tuples `_records()` builds from it for `execute_values`. `pipeline.py`
does the same thing and survives, because it runs on the host with the whole machine
available; the containerised task worker did not.

`iter_staged_rows` uses a named (server-side) cursor so Postgres streams the result instead of
shipping all of it before the first row is available, and caps peak memory at the chunk size
regardless of how large the batch is. That is what makes the same task work for both a
1,043,868-row full reload and a 49,503-row incremental batch.

Two connections are required: a named cursor holds its transaction open for the life of the
iteration, so committing writes on the same connection would invalidate it mid-loop.

**Worth recording** because the local runner and the DAG ran identical code and only one of
them failed. "It works on my machine" was literally true, and the difference was the memory
available to the process, not the logic.

---

## D16. Category analysis runs at the secondary level, because every reviewed product is Skincare

**Date**: 2026-08-06

**Decision**: business question 1's category half is answered with `secondary_category`, not
`primary_category`. The dashboard's category visual groups on secondary. The KPI row states
products reviewed alongside products in catalogue so the gap is visible rather than implied.

**Why**: found while cross-checking the analytics views against the loaded warehouse. Grouping
1,093,371 reviews by `primary_category` returned **one row**:

```
 primary_category | reviewed_products | reviews
------------------+-------------------+----------
 Skincare         |             2,351 | 1,093,371
```

The catalogue holds 8,494 products across 9 primary categories — Skincare 2,420, Makeup 2,369,
Hair 1,464, Fragrance 1,432, and five smaller ones. But **only Skincare products have any
reviews at all**, and 2,351 of the 2,420 Skincare products are covered. The other 6,074
products have zero.

This is inherent to the source, not a pipeline fault: the dataset is *Sephora Products and
Skincare **Reviews*** — the product catalogue was scraped in full, the review scrape covers
skincare only. The earlier profiling recorded "2,351 of 8,494 products have reviews" without
noticing that all 2,351 fall in one category.

**Consequences**:
- `primary_category` is constant across the fact table, so a chart of it is a single bar.
  `secondary_category` is the level that varies usefully — Moisturizers 297,201 reviews,
  Treatments 221,871, Cleansers 200,477, Eye Care 74,966, Masks 70,483, Sunscreen 41,126.
- `vw_rating_by_skin_type`'s `WHERE primary_category = 'Skincare'` is now a no-op. It stays
  as a guard: if a future load ever brought in makeup reviews, the view would keep answering
  the question it claims to answer rather than silently widening.
- Any statement of the form "which categories rate best across Sephora" is unsupportable from
  this data and must not appear on the dashboard. The honest framing is "within skincare".

**Worth recording** because the pipeline was working perfectly and the number was still
misleading. Every row count reconciled; the flaw was in what the data covers, which no
integrity check can catch.

---

## D17. Three explicit load modes replace `--full-reload`

**Date**: 2026-08-08

**Decision**: `full` (every review, no date bound) · `historical` (before 2023-01-01) ·
`incremental` (after the watermark). Wired identically through `pipeline.py --mode` and the
DAG's `load_mode` Param.

**Why**: the previous `--full-reload` flag loaded reviews **before 2023-01-01 only** — a
historical baseline, not a full load. The name claimed something the code did not do. Anyone
reading `--full-reload` would reasonably conclude the warehouse held everything, when a
quarter of a year was missing by design, and no error or log line would correct them.

A mode that deliberately withholds data has to say so in its name. Splitting the two apart
also made a real gap visible: there was **no way to load everything in one command**. The demo
baseline had quietly become the only "full" load available.

`extract_reviews_for_mode()` is the single place a mode string becomes a query, so
`pipeline.py` and the DAG cannot drift into disagreeing about what a mode means.

**Ruled out**: keeping two modes and renaming `--full-reload` to `--historical`. That fixes
the lie but leaves the missing capability.

---

## D18. Streamlit rather than Power BI

**Date**: 2026-08-08

**Decision**: the dashboard is `dashboard/app.py`, a Streamlit app in this repository,
querying `sephora_dw` live.

**Why**: the dashboard becomes **part of the project** rather than an artifact beside it.

- **Versioned and diffable.** A `.pbix` is a binary; its logic can only be inspected by
  opening it in the application. Every query here is plain text in git and reviewable in a
  pull request like any other code.
- **Reproducible by anyone.** Clone, `pip install -r requirements.txt`, one command. No
  desktop install, no licence, no Windows requirement.
- **Testable.** `tests/integration/test_dashboard_smoke.py` runs the app through Streamlit's
  `AppTest` harness and asserts the KPI row equals `SELECT count(*), avg(rating) FROM
  dw.fact_reviews`. A Power BI report cannot be asserted against its own source in CI.
- **One definition of every number.** The app reads the same views as
  `sql/validation/dashboard_checks.sql`, so the two cannot drift. Logic embedded in DAX would
  be a second definition living somewhere unversioned.

**Cost, stated honestly**: Power BI is what the course taught and what many employers use;
DAX and the Power BI data model are not demonstrated by this project. The trade was made for
reproducibility and testability, and it is the reason the checklist item "at least one DAX
measure" is now marked not-applicable rather than pending.

**Ruled out**: building both. Two dashboards means two places for a number to be wrong.

---

## D19. Every dropped row is counted against a named reason

**Date**: 2026-08-08

**Decision**: `etl/reconcile.py` enforces two identities, and raises `ReconciliationError`
when either fails:

```
rows_extracted == rows_transformed + sum(rows_dropped_by_reason)
rows_offered   == rows_inserted    + rows_already_present
```

`build_dim_product` and `build_fact_reviews` return `(DataFrame, drops)` where `drops` maps a
reason — `unresolved_product`, `unresolved_customer`, `unresolved_reviewer_profile`,
`out_of_range_date`, `unresolved_brand` — to a count, **including the zeros**.

**Why**: `transform.py` previously dropped unresolved rows with `logger.warning` and nothing
else. That is a silent data-loss channel with a paper trail nobody reads. If 1,000 reviews
pointed at a product missing from `dim_product`, the run stayed green, the fact table was
quietly 1,000 rows short, and the only evidence was one WARNING among thousands of log lines.

Dropping rows is legitimate — a review whose product genuinely isn't in the catalogue cannot
be loaded. Dropping them **without saying how many and why** is not. The identity turns an
unnoticed shortfall into a stopped pipeline.

Zeros are recorded deliberately: a reason key that appears only when it fires makes "nothing
was dropped for this reason" indistinguishable from "this reason was never checked".

---

## D20. A failure watcher task, because `all_done` cleanup masked failures

**Date**: 2026-08-08 · **Superseded by [D24](#d24-cleanup_staging-is-a-teardown-not-a-watched-task) on 2026-08-12**

> The bug described here is real and the fix worked. It was later replaced by a smaller
> mechanism that achieves the same guarantee. The entry is kept because the bug is the reason
> the current design exists, and because the reasoning below is still the reasoning.

**Decision**: `watch_for_failure`, `trigger_rule="one_failed"`, `retries=0`, wired downstream
of all 15 other tasks and the DAG's only leaf.

**Why**: `cleanup_staging` uses `trigger_rule="all_done"` so a failed run still clears its
staging rows. Correct in itself — but it made cleanup the only **leaf** task, and Airflow
derives a DAG run's final state from its leaves. The result:

> extract fails → cleanup still runs → cleanup succeeds → the only leaf is green →
> **the DAG run reports SUCCESS** with an empty warehouse.

A green run that loaded nothing is worse than a red one, because nobody investigates it. This
is the Airflow documentation's own watcher pattern, and it exists for exactly this situation.

- Something failed → `one_failed` is satisfied → the watcher runs, raises, and a failed leaf
  fails the run.
- Nothing failed → the rule is never satisfied → the watcher is **skipped**, and a skipped
  leaf leaves the run green.

`retries=0` because retrying a task whose only job is to report an existing failure would
delay the red status by ten minutes.

The upstream list is built from task **objects** rather than typed-out names, because
`one_failed` evaluates *direct* upstreams only — a task missing from the list is a failure the
watcher cannot see. Asserted by `test_watcher_watches_every_other_task`.

---

## D21. Quality checks carry a severity; not every finding should stop a run

**Date**: 2026-08-08

**Decision**: every check in `etl/quality.py` declares `hard_failure` or `warning`.
Hard failures raise `DataQualityError` before any write; warnings are logged and the run
continues.

**Why**: originally every check was fatal, which sounds rigorous and is actually a trap — it
means the only checks worth writing are the ones you are willing to stop production for.
Anything softer simply never gets written, and the gate stays silent about things worth
knowing.

The distinction is real here, not decorative. `is_recommended` is unanswered on ~15% of
reviews and `helpfulness` is undefined wherever nobody voted (D5). Both are legitimately null
in bulk. Failing a run over that would be wrong; saying nothing would be worse. `check_null_rate`
warns, so a *shift* — `is_recommended` suddenly arriving 90% null — is visible in the logs
before it quietly flattens a dashboard number.

Warnings are logged **before** the hard-failure raise, so a run that dies still leaves its
warnings behind rather than losing them.

`check_unique_key` stays a **hard** failure despite being survivable: `ON CONFLICT DO NOTHING`
would absorb duplicates without corrupting anything, but the loaded count would then silently
disagree with the extracted count — precisely the gap D19 exists to close.

---

## D22. Analytics SQL is split into views and validation

**Date**: 2026-08-08

**Decision**: `sql/analytics/views/` holds view DDL. `sql/validation/dashboard_checks.sql`
holds read-only assertions. They are separate directories.

**Why**: they are opposite jobs sharing one folder. Running the views folder **changes the
database**; running the validation file **changes nothing** and tells you whether what the
dashboard shows is true. Mixing them means no one can safely run either without reading it
first.

The validation file now reconciles every view back to `fact_reviews` — all 8 full-population
views return exactly 1,093,371 — and labels the two deliberate subsets
(`vw_rating_by_skin_type` is Skincare-only, `vw_hype_vs_reality` requires ≥50 reviews) so a
smaller number reads as intentional rather than as loss. The rule is stated in the file: **if
the dashboard and this file disagree, the dashboard is wrong.**

---

## D23. Dashboard controls are query parameters, and the quality panel recomputes

> **Narrowed by [D25](#d25-one-page-one-control-and-a-validated-palette) on 2026-08-12.**
> The principle stands and the panel is unchanged, but the dashboard was reduced to a
> single page with **one** control, so the claim below is now demonstrated by the brand
> review floor alone rather than by five separate widgets.

**Date**: 2026-08-08

**Decision**: every interactive control on the dashboard binds its value into the SQL rather
than filtering the returned DataFrame, and the data-quality panel derives every figure at
render time instead of reading a stored summary.

**Why — the controls**: a slider that filters a cached DataFrame and a slider that
re-parameterises the query look *identical* on screen. They are not the same claim. The
second demonstrates that the dashboard is a live query interface over the warehouse; the
first demonstrates that pandas can subset a frame. So the three Deep-dive sliders feed
`WHERE hype_gap >= %s`, `WHERE price_usd BETWEEN %s AND %s`, and
`HAVING sum(review_count) >= %s` — the last replacing a hardcoded `HAVING >= 1000`, which
was always a judgement call and is more honest as a control the viewer can move.

Slider end-points are read from the views' own `min`/`max` rather than hardcoded, and are
deliberately *not* narrowed by the category filter: a control whose range moves while you are
using it cannot be reasoned about mid-demo.

Each control is asserted individually in `tests/integration/test_dashboard_smoke.py` by moving
it and requiring the corresponding caption to change. Verified non-vacuous: reverting the
skin-group floor to its hardcoded `1000` makes `test_skin_group_floor_is_live` fail while the
other two still pass.

**Why — the panel recomputes**: `etl/reconcile.py` logs its counts, it does not persist them,
so there is no reconciliation table to read. Rather than hardcode the numbers from a past run,
the panel re-derives them: row accounting across `raw.reviews` → `3nf.review` →
`staging.review` → `dw.fact_reviews`, the four named drop reasons re-checked against the
loaded warehouse, and the reconciling-view count computed by running the same `UNION` as
`dashboard_checks.sql`. That last one is *counted*, not typed, so it cannot keep claiming 8
after someone adds a ninth view.

**The case that made this worth getting right**: the panel must distinguish **held back** from
**lost**. At the historical baseline the warehouse is legitimately 49,503 rows behind
`staging.review`, because a `historical` load holds 2023 back so the incremental has real data
to pick up (D8). A panel that reported that as a shortfall — or worse, printed "nothing was
dropped" beside a `-49,503` — would be wrong at exactly the moment it is on screen during the
demo. It now compares the gap against the count of staging rows *after* the watermark and says
which of the three states it is in, escalating to an `st.error` only when rows are genuinely
unaccounted for.

One number in the panel is labelled **not live**: the 1,040 duplicates `clean.py` removed
before anything reached Postgres (D4). Neither database can be queried for it. It is stated
and labelled rather than omitted, because the panel's claim is about what happened to every
row — not only the parts that are convenient to query.

---

## D24. `cleanup_staging` is a teardown, not a watched task

**Date**: 2026-08-12 · supersedes [D20](#d20-a-failure-watcher-task-because-all_done-cleanup-masked-failures)

**Decision**: mark `cleanup_staging` with `.as_teardown()` and delete `watch_for_failure`
entirely. The DAG goes from **16 tasks / 33 edges to 15 tasks / 21 edges**.

**Why**: D20's watcher solved the right problem the expensive way. Because `trigger_rule`
evaluates *direct* upstreams only, the watcher had to be wired downstream of every single
task — 15 of the DAG's 33 edges existed solely to let one task observe the others. Nearly
half the graph was failure plumbing, and every new task added a wiring obligation that,
if forgotten, silently stopped failures being reported.

Airflow's teardown feature addresses the same situation structurally. From
`DagRun._tis_for_dagrun_state`:

```python
def is_effective_leaf(task):
    for down_task_id in task.downstream_task_ids:
        down_task = dag.get_task(down_task_id)
        if not down_task.is_teardown or down_task.on_failure_fail_dagrun:
            return False          # a non-ignorable downstream: not a leaf
    return not task.is_teardown or task.on_failure_fail_dagrun
```

Marking cleanup a teardown makes it *ignorable*, which promotes
`load_fact_from_staging` to sole effective leaf. Cleanup still runs after a failure, and it
can no longer report success on the run's behalf. Failure propagation through
`upstream_failed` then does the job the watcher's 15 edges were doing — verified by
`test_every_task_can_fail_the_run`, which asserts every task has a path to the leaf.

**The trap, recorded so it is not "fixed" later**: `on_failure_fail_dagrun=True` looks like
the right way to make cleanup's *own* failure count. It is not. It makes cleanup
non-ignorable, which makes it the sole effective leaf again and **reinstates D20's bug
exactly**. The flag must stay `False`, and `test_cleanup_does_not_fail_the_dagrun` pins it
there. The trade is deliberate and asymmetric: a failed cleanup strands batch-scoped rows,
which is hygiene; a masked pipeline failure is correctness.

**Verified by failure injection**, not by reading the docs. With `extract_fact_to_staging`
forced to `failed`:

| | |
|---|---|
| `transform` / `quality` / `load_fact` | `upstream_failed` |
| `cleanup_staging` | **success** — still cleaned up |
| DAG run | **failed** |

A green cleanup beside a red run is precisely the case that used to report success.

**A latent race this exposed.** The first injection run left **513,606 rows** in three
staging tables carrying that run's own `batch_id`. Cause: `cleanup` had `load_fact` as its
only upstream — in *both* the old and new designs. A normal run hides it, because `load_fact`
always finishes after the dimensions. But when the fact chain short-circuits to
`upstream_failed`, cleanup fires immediately, finds empty tables, deletes nothing, and the
dimension branches stage their rows afterwards. Cleanup now waits on every staging **writer**
(`load_product`, `load_customer`, `load_reviewer_profile`, `load_fact`). Those extra edges
cost nothing structurally — each of those tasks still has `transform_fact` downstream, so
cleanup stays ignorable and the leaf set is unchanged. Re-verified: all six staging tables at
0 after an injected failure. Pinned by `test_cleanup_waits_for_every_staging_writer`.

---

## D25. One page, one control, and a validated palette

**Date**: 2026-08-12 · narrows [D23](#d23-dashboard-controls-are-query-parameters-and-the-quality-panel-recomputes)

**Decision**: the dashboard is a **single scrolling page** with a small, deliberate set
of controls, themed Sephora black / white / red.

> **Revised the same day.** This entry originally landed with exactly **one** control
> (the brand review floor), cutting five. Category- and product-level filtering was then
> asked for and added back, giving **four**: category, brand review floor, brand, and a
> product name search. The principle that survived is not "one control" — it is that
> every control must **bind into SQL** and must have an **unambiguous scope**. The five
> that were cut (date range, hype gap, price range, skin-group floor, and the old
> whole-page category multiselect) are still gone. See *Scope* below.

**Why one page**: two pages meant the five business questions were split across a
navigation control, so answering "what did you find?" required knowing which page a
finding lived on. A capstone dashboard is read once, in order, by someone who has
never seen it. Scrolling is a better interface than navigating for that. Every
section now states its finding **in words** under the heading, so the page is legible
without reading a single chart.

**Why one control**: the page previously carried a category multiselect, a date-range
slider, a hype-gap slider, a price-range slider and a skin-group floor. Each was a
genuine SQL parameter — that part of D23 was true and is preserved for the survivor —
but five controls on a page nobody is going to operate is complexity for its own
sake, and each one is a way for the demo to end up in a state that does not show the
finding. The review floor stays because without it the "best brand" is whichever has
a single 5-star review; it still binds in as `WHERE review_count >= %s`.

**What this costs, stated plainly**: three of the tests that asserted individual
sliders were live are gone with the sliders. The data-quality panel half of D23 is
untouched, and the surviving controls are each covered by a test that moves one and
requires the corresponding caption to change.

### Scope — the part that makes a partial filter honest

A category filter cannot scope every chart, and pretending otherwise is the real
hazard. Of the views the page reads:

| Section | Responds to Category? | Why |
|---|---|---|
| Brands | **yes** | via the new `vw_rating_by_brand_category` |
| Categories · Hype · Skin type · Product explorer | **yes** | their views carry `secondary_category` |
| Volume/rating trend · Price bands | **no** | `vw_review_volume_by_month` and `vw_rating_by_price_band` aggregate the category column away |

The two that cannot respond are **labelled *all categories* in their card titles**, a
sidebar note lists exactly what the filter scopes, and selecting a subset raises a
banner naming the categories in force. A filter that silently does nothing to two
sections while appearing to work is worse than no filter.

**`vw_rating_by_brand_category` exists specifically for this.** `vw_rating_by_brand`
groups by brand alone, so a category predicate applied to it is a no-op — the brand
chart would have stayed catalogue-wide while the page claimed to be filtered. The new
view is a full-population view and reconciles to `fact_reviews` at 1,093,371 like the
rest. The dashboard re-aggregates it to brand level with a **review-count-weighted
mean**: averaging the per-category averages would weight a 12-review category the same
as a 300,000-review one.

**The product-level filters live in their own section**, not the sidebar. Their brand
picker and name search sit directly above the only table they scope, so there is never
a question about what they affect — the ambiguity the category filter has to explain
with a note.

### Other filters that were considered

Recorded so the absence is a decision rather than an oversight:

| Filter | Cost | Verdict |
|---|---|---|
| Price range | Free — `price_usd` is on `vw_hype_vs_reality` | Available; the price-band section already answers BQ3 more directly |
| Rating / recommend threshold | Free on the product view | Selecting on the outcome invites survivorship reasoning |
| Product flags (`sephora_exclusive`, `limited_edition`, …) | Needs a view; they sit on `dim_product` | Genuinely interesting, no business question attached |
| Date range | Needs a category × month view | Cut — the trend chart is the whole point of BQ5 and shortening it removes the finding |
| Skin tone / type as a *filter* | Needs a fact-level predicate on the junk dimension | It is a **dimension of the answer** in BQ4, not a filter on it |
| Tertiary category | Free — already on `dim_product` | 174 triples is too many for a usable control |

### The palette was validated, not chosen

Sephora's colours are black, white and the brand red. Every value was run through the
data-viz validator against the actual `#151515` card surface rather than picked by eye:

| Slot | Value | Result |
|---|---|---|
| Categorical pair | `#F5405F` red · `#5589C7` blue | worst-pair CVD ΔE **16.1**, normal-vision **29.1** |
| Ordinal ramp (5 price bands) | `#F7A8B8` → `#A81736` | monotone lightness, single hue (11° spread) |
| Diverging midpoint | `#8A8781` | neutral, and still visible on black |

Only **two** categorical slots exist, because the page never plots more than two
series at once. A third warm hue (gold `#E9B44C`) was tried and **cut**: it failed
deuteranope separation against the brand red at ΔE 4.2, which the validator caught and
an eye would not have.

### Three charts changed form, because the old ones misled

This is the part worth defending. Most effects in this data are a tenth of a star, so
the axis has to be truncated to show them — and **a truncated axis under bars lies**,
because bar length is read from zero. On the old price chart, "Under $15" (4.2383) was
drawn roughly six times shorter than "$50–100" (4.3335): a 2% difference rendered as
600%. Category and skin-type bars had the same defect.

All three became **position encodings** — a line across the ordered price bands, dot
plots for category and skin type. Same truncation, now honest, and the price line
shows the inverted U at a glance instead of implying it.

Review length became **small multiples**. The 1-star share (3–8%) and 5-star share
(61–67%) live on different scales, so grouped on one axis the 5-star bars towered and
the 1-star decline — half the finding — flattened into a strip along the baseline. A
second y-axis is the usual fix and is worse: two arbitrary scales invent a
relationship. Separate panels let each tail be read on its own scale.

### A wrong claim the redesign caught

Rendering the price chart exposed that **`rating_stddev` is not monotonic**. It falls
1.2211 → 1.0996 through `$50–100` and then **widens again to 1.1366** above $100. This
document, `README.md` and `CLAUDE.md` all asserted it "falls steadily as price rises",
each of them directly beneath a table showing otherwise. Corrected everywhere. The
accurate finding is stronger: **$50–100 is the sweet spot on both measures** — best
rated *and* most agreed upon — and the priciest band regresses on both at once.

---

## Format for future entries

New decisions follow the same shape: **Decision** (what was chosen), **Why** (the reasoning,
including what was ruled out and why), and the measured evidence where a measurement drove it.
