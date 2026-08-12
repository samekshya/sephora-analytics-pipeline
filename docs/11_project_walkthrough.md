# Project Walkthrough — Everything Done So Far, Step by Step

**Purpose of this file**: a full narrative account of the Sephora Reviews capstone,
from the raw CSVs to the current state, written so anyone (including future-me)
can read it top to bottom and understand not just *what* was built but *why*,
at every step. `CLAUDE.md` is the terse running checkpoint; this is the long
version.

> **Written 2026-08-07, before the phase-9 remediation.** The narrative of how
> the pipeline was built is still accurate — that is genuinely how it happened.
> Several specifics changed the next day. What they were, and where the current
> account lives:
>
> | Then | Now |
> |---|---|
> | Two load modes; `--full-reload` stopped at 2023 | Three named modes: `full` / `historical` / `incremental` — [05](05_etl_and_incremental_loading.md), D17 |
> | 15 DAG tasks | **15** — a failure watcher was added (D20), then replaced by a teardown that does the same job with 12 fewer edges — [06](06_airflow_runbook.md), D24 |
> | Unmatched rows dropped with a log warning | Counted against a named reason; unexplained gaps raise — D19 |
> | Quality checks all fatal | `hard_failure` / `warning` severities — D21 |
> | 8 hand-rolled fault-injection cases | **49 pytest tests** — [08](08_testing_evidence.md) |
> | Power BI planned, not built | **Streamlit, built** — [`dashboard/`](../dashboard/README.md), D18 |
> | 6 analytics views | **10**, split from validation SQL — D22 |
> | `dim_reviewer_profile` described as 2,003 rows | **1,896** — 2,003 is the pre-cleaning figure |

---

## 0. What we started with

Two kinds of raw CSVs in `data/raw/`, straight from Sephora's product/review
scrape, never touched by hand:

- **`product_info.csv`** — 8,494 rows × 27 columns. One row per product:
  name, brand, three levels of category, price, size, loves count, flags
  (`limited_edition`, `new`, `online_only`, `out_of_stock`,
  `sephora_exclusive`), plus some sparse pricing columns and a stringified
  `highlights` list.
- **Five `reviews_*.csv` files** totalling 1,094,411 rows. One row per
  review: author id, product id, rating, recommendation, review text/title,
  feedback vote counts, submission timestamp, and four self-reported reviewer
  attributes (skin_tone, skin_type, eye_color, hair_color).

The goal, set out from the start: explore it, clean it, normalize it into a
proper OLTP database, build a star-schema warehouse from that, write
analytics on top, and orchestrate the whole thing with Airflow — the standard
shape of a data engineering capstone, deliberately mirrored on a reference
project so the format matched what the course taught.

---

## 1. Exploration (`explore.py`)

Before writing a single cleaning rule, we ran 14 profiling checks against the
raw files and wrote up everything found in
`docs/02_data_quality_findings.md`. This stage existed to answer one
question honestly: **what is actually wrong with this data**, rather than
guessing.

What we found, and why each finding mattered downstream:

- **`product_id` is unique** (0 duplicates) — safe as a primary key.
- **`brand_id` → `brand_name` is a strict 1:1 mapping** across all 8,494
  products — meaning brand can be its own table keyed on `brand_id`, no
  ambiguity.
- **174 distinct (primary, secondary, tertiary) category triples**, and
  critically: **one secondary category appears under up to 7 different
  primaries** (e.g. "Value & Gift Sets"). This single fact drove a real design
  decision later (D1) — category could *not* be modeled as a clean 3-level
  hierarchy, because it isn't one in the data.
- **1,094,411 review rows**, 503,216 distinct authors, only 2,351 distinct
  products actually reviewed (out of 8,494 in the catalogue — most of the
  catalogue has zero reviews).
- **`submission_time` range**: 2008-08-28 → 2023-03-21, and every single
  timestamp had a midnight time component — so the true grain of the data is
  a *date*, not a datetime. That meant we could drop to `DATE` precision
  without losing anything.
- **0 orphan reviews** — every review's `product_id` resolves to a real
  product.
- **Duplicate reviews measured two ways**: 1,040 duplicates on
  `(author_id, product_id, submission_time)` vs. 5,525 on
  `(author_id, product_id)` alone. The gap between those two numbers is what
  let us tell a *duplicate* apart from a *legitimate re-review* (someone
  reviewing the same product twice, months apart) — decision D4.
- **`(source_row_id, product_id)` never collides across all 5 files** — 0
  duplicates. This became the fact table's idempotency key later (D13),
  because each product lives in exactly one file, so pairing the file's own
  row index with the product id is a safe natural key even though
  `source_row_id` alone restarts at 0 in every file.
- **2023 data (49,531 rows) was set aside** specifically to demonstrate
  incremental loading later, rather than faking synthetic new rows.
- **Rating distribution**: 5★ 698,951 · 4★ 199,389 · 3★ 81,816 · 2★ 53,032 ·
  1★ 61,223 — heavily skewed toward 5 stars, as review data usually is.
- **Reviewer attribute stability**: this was the most important finding in
  the whole exploration phase. 22,503 authors (4.47%) reported *more than one
  distinct value* for at least one of skin_tone/skin_type/eye_color/hair_color
  across their reviews — affecting 149,788 reviews (13.69% of the dataset).
  In plain terms: people's self-reported skin type on Sephora isn't fixed —
  it's answered per review, and it drifts. This single measurement is what
  later killed the idea of storing those four attributes on a "customer"
  table (see D2 below — it's the single biggest design decision in the
  project).
- **Distinct reviewer-profile combinations**: only 2,003 out of 4,200
  theoretically possible combinations of the four attributes actually occur —
  small enough to become a dimension table of its own.
- **Feedback-count consistency**: verified across all 1.09M rows that
  `helpfulness IS NULL` if and only if `total_feedback_count = 0`, and that
  `total_pos_feedback_count + total_neg_feedback_count = total_feedback_count`
  always. Zero violations. Both became formal invariants (D5, and later a
  `CHECK` constraint).
- **`highlights` column**: a stringified list, 112 distinct tags, present on
  82.4% of reviewed products / 89.6% of reviews. This is a genuine
  many-to-many relationship (one product can have many tags, one tag applies
  to many products). We measured it, then explicitly decided *not* to model
  it — see D3.

**Decisions D1–D13** were written into `docs/09_decision_log.md` as they were
made during this stage, not reconstructed afterward.

---

## 2. Cleaning (`clean.py`)

`clean.py` reads the raw CSVs and writes cleaned versions to
`data/processed/` (`products.csv`, `reviews.csv`), ready for loading. Its
scope was deliberately narrow and stated up front in the file's own
docstring: **structural cleaning only** — dedup, type coercion, whitespace
trimming, fixing two known value defects, and one derived column. It
explicitly does **not** drop any columns (that's decision D14, explained
below) — every source column survives into the raw database layer for
traceability, and only gets trimmed later at the raw→3NF boundary.

### What it actually does, in order:

**For products:**
1. Reads `product_info.csv`, trims whitespace on every text column (logging
   how many cells were touched — 16,072 total).
2. Drops exact duplicate rows (0 found).
3. **Asserts** `product_id` is unique — raises an error and halts if not,
   rather than silently proceeding. (0 duplicates confirmed.)
4. **Asserts** `brand_id → brand_name` really is 1:1 across the whole file —
   again halts on violation rather than silently building an inconsistent
   brand table.
5. Coerces types: floats (`rating`, `price_usd`, etc.) via `pd.to_numeric`;
   integers (`brand_id`, `loves_count`, `reviews`, `child_count`) using
   pandas' **nullable `Int64`**, not `float64` — this mattered because a
   nullable int column stored as float64 would write back out as `"11.0"`,
   which Postgres's `COPY` rejects against an `INTEGER` column. The decimal
   point isn't cosmetic, it's a type error.
6. Casts the five 0/1 flag columns to real booleans.
7. Converts empty strings to real `NULL`s (so Postgres gets `NULL`, not an
   empty string) on the sparse/optional columns.

Result: **8,494 rows in → 8,494 rows out, 0 dropped.**

**For reviews:**
1. Reads and concatenates all 5 review CSVs, naming the unnamed index column
   `source_row_id` and tagging every row with `source_file` (which CSV it
   came from) — this tagging is what later proves the idempotency key never
   collides.
2. Trims whitespace (1,030,753 cells touched).
3. **Deduplicates** on `(author_id, product_id, submission_time)` — the D4
   key — dropping 1,040 exact duplicate reviews, while *keeping* the 5,525−1,040
   = 4,485 legitimate re-reviews (same author+product, different date).
4. **Asserts** `(source_row_id, product_id)` is unique after dedup — this is
   the idempotency key the fact table will later use, so a violation here
   would be caught before it ever reached the warehouse. 0 collisions.
5. **Fixes the two known value defects found during exploration**:
   - `eye_color`: `'Grey'` (capital G, 4,859 occurrences) collapsed into
     `'gray'` — same colour, two spellings in the source.
   - `skin_tone`: `'notSureST'` (70 occurrences) — a "not sure" placeholder
     value, not a real skin tone — mapped to null rather than treated as a
     14th skin tone.
6. Coerces types (floats, nullable `Int64` integers, `submission_time`
   parsed to a real date — **0 unparseable values**, and since every
   timestamp is midnight, truncated down to `DATE` precision).
7. `is_recommended` cast to nullable boolean (arrives as 1.0/0.0/NaN).
8. **Derives `review_length`** as the character count of `review_text` — this
   one derived column is what lets the warehouse carry a useful signal about
   review length *without* carrying the 350 MB of actual review text (decision
   D6).
9. Converts empty strings to null on text/attribute columns.

Result: **1,094,411 rows in → 1,093,371 rows out (1,040 duplicates removed)**,
run end-to-end in 24 seconds, every step logged with counts.

Every rule in `clean.py` logs rows in/out/dropped — so the numbers in
`CLAUDE.md`'s "Measured Numbers" table aren't estimates, they're what the log
files actually reported.

---

## 3. Ingest into the OLTP `raw` schema (`ingest.py`)

`ingest.py` loads the two cleaned CSVs into `sephora_oltp.raw.product_info`
and `sephora_oltp.raw.reviews` using Postgres's `COPY`, not row-by-row
`INSERT` — at 547 MB / 1.09M rows for the reviews file, row-by-row inserts
would be orders of magnitude slower for no benefit.

Design points:
- **Script-based, not a manual DBeaver import** — this was a deliberate
  deviation from the reference project (whose own checklist calls manual
  import a gap). At 1.09M rows, manual import isn't practical anyway.
- **Credentials only from `.env`** via `python-dotenv`, never hardcoded.
- **Transactional, truncate-and-reload**: the whole load happens inside one
  transaction; if anything fails partway, it rolls back rather than leaving a
  half-loaded raw table. The raw schema is a landing zone for a full source
  export, not an incremental target — "load it again" means "make it match
  the file," not "append a second copy."
- **Row counts asserted against what `clean.py` reported** (8,494 / 1,093,371)
  — if `COPY` loads a different count, the whole load is rejected and rolled
  back rather than silently committing a partial load.

Result: both tables loaded in 15 seconds, counts matched exactly.

---

## 4. Building the 3NF OLTP layer (`sql/oltp/migrations/`)

This is genuinely the heart of "normalize the data" — 15 numbered,
append-only SQL migrations that build a `3nf` schema with **9 tables**, all
foreign keys actually enforced by Postgres (not just implied by naming).

### Why normalize at all
The raw layer has heavy redundancy: `brand_name` is repeated on all 8,494
product rows *and again* on all 1.09M review rows; the three category levels
repeat the same way; the four reviewer attributes are carried as free text on
every review row. Third normal form means every non-key attribute depends on
the key, the whole key, and nothing but the key — so each of those repeated
facts gets pulled out into its own table, referenced by a foreign key
instead of duplicated.

### The 9 tables, and the reasoning behind each:

**`brand`** (304 rows) — keyed on the source's own `brand_id` (not a new
surrogate key), because exploration already proved it's a stable 1:1 mapping.
`brand_name` moving here is *the* textbook 3NF removal: it was transitively
dependent on `brand_id`, not on `product_id`.

**`category`** (174 rows) — keyed on the **full (primary, secondary,
tertiary) triple** as a `SERIAL` id, deliberately **not** modeled as three
nested hierarchy levels (that's D1). Because one secondary category sits
under 7 different primaries, a parent-child hierarchy would assert a
relationship that doesn't exist in the data, and any rollup built on it would
silently produce wrong totals. Since `secondary_category`/`tertiary_category`
can be null (8 products have no secondary, 990 have no tertiary), the unique
constraint uses `NULLS NOT DISTINCT` — otherwise two products with the same
primary and both nulls would count as "different" and create duplicate
category rows, since plain SQL treats `NULL ≠ NULL`.

**`product`** (8,494 rows) — brand_name and the three category columns are
now gone, replaced by `brand_id`/`category_id` foreign keys. This is also
where several sparse/unnecessary columns were *cut* (not carried from raw):
`highlights` (descoped, see D3), `ingredients` (long free text, no locked
business question needs it), and four pricing columns that were 67–97% null
(`value_price_usd`, `sale_price_usd`, `child_max_price`, `child_min_price`),
plus `variation_desc` (85% null free text). `price_usd`, `loves_count`,
`child_count` all carry `CHECK` constraints (`> 0`, `>= 0`, `>= 0`) so bad
values fail the load instead of silently entering the warehouse later.

**`author`** (503,216 rows) — **identity only**. No skin_tone, skin_type,
eye_color, or hair_color columns here at all. This is the direct consequence
of the exploration finding above: those four attributes are not functionally
dependent on `author_id` (22,503 authors gave more than one answer). Putting
them here would force one value per person and silently discard the other
answers.

**`skin_tone` / `skin_type` / `eye_color` / `hair_color`** (13 / 4 / 5 / 7
rows) — four small lookup tables, each with a `UNIQUE` constraint on the
value itself. This is what makes the `'Grey'`/`'gray'` casing bug structurally
impossible to reintroduce: once collapsed in `clean.py` and enforced by a
unique constraint here, no second spelling can silently sneak back in without
tripping a foreign key failure.

**`review`** (1,093,371 rows) — the four reviewer attributes live *here*, as
nullable foreign keys to the four lookup tables, because review is the actual
grain at which they were recorded (that's D2 in a nutshell — more below).
Three columns were dropped at this boundary: `product_name`, `brand_name`,
`price_usd` — all three were 100% redundant with `product_info.csv` (verified
to agree on all 2,351 reviewed products), a textbook 3NF removal.
`review_text`/`review_title` are kept here and go **no further** (D6) — 350MB
of free text has no business being in a fact table, but dropping it entirely
here would break traceability. Two invariants from exploration became actual
`CHECK` constraints, not just documented observations:
`total_pos_feedback_count + total_neg_feedback_count = total_feedback_count`,
and `(helpfulness IS NULL) = (total_feedback_count = 0)`.
`UNIQUE(source_row_id, product_id)` is the idempotency key (D13).

### Loading raw → 3nf (migrations 8–12)

Each load is a straightforward `INSERT ... SELECT DISTINCT ... ON CONFLICT DO
NOTHING`, which makes every migration safe to re-run. Two details worth
calling out:

- Loading `product` requires joining back to the new `category` table using
  `IS NOT DISTINCT FROM` instead of plain `=`, specifically because of the
  nullable category levels — a plain `=` join would silently drop the 8
  products with no secondary category and the 990 with no tertiary category.
- Loading `review`'s four attribute foreign keys uses **`LEFT JOIN`**, not
  inner join — an inner join would drop every review that left an attribute
  blank (between 111K and 227K rows per attribute — the majority of the
  table once combined). A blank answer is still a review and must not
  disappear.

### The staging schema (migrations 13–14)

`staging.product` and `staging.review` are a **denormalized, analytics-ready
re-flattening** of the 3nf tables — brand and category joined back onto
product, the four attribute foreign keys resolved back to their text values.
This exists because 3nf is correct but awkward to query from — every
dimension attribute sits one or two joins away — so staging pre-joins them
once in SQL, keeping the later Python extract code a simple `SELECT` per
table instead of embedding join logic in Python.

This is also exactly where the null-handling policy changes on purpose: in
`3nf.review`, a missing reviewer attribute is correctly represented as a
`NULL` foreign key. In `staging.review`, those same nulls are coalesced to
the literal string `'Unknown'`. The reason is that `staging` feeds a junk
dimension downstream, and a junk dimension with `NULL` member columns can't
be joined to or filtered on properly in Power BI — `'Unknown'` has to be a
real, selectable dimension member.

### Reconciliation (migration 15)

A verification script comparing row counts at every layer (`raw` → `3nf` →
`staging`) plus six integrity checks (orphan reviews, products with no
brand/category, staging rows with a null attribute, duplicate idempotency
keys) that must all return exactly 0. All did.

---

## 5. Building the star-schema warehouse (`sql/datawarehouse/migrations/`)

A **second, separate Postgres database**, `sephora_dw`, schema `dw` (decision
D7: two physical databases, not two schemas in one, matching the reference
project's OLTP/DW separation). 7 migrations build 5 dimension tables and 1
fact table.

The philosophy is stated right at the top of the first migration:
*deliberately not normalized* — `dim_product` repeats brand name and all
three category levels on every row, which is the opposite of what the 3NF
layer just did. That redundancy is intentional: it buys single-join
dashboard queries instead of the multi-hop joins the OLTP layer requires. Two
layers, two different jobs.

**Grain of the fact table: one row per review.**

### The 5 dimensions:

**`dim_date`** — `date_key` is an `INTEGER` in `YYYYMMDD` form (the standard
Kimball convention, carried over from an earlier hand-written schema — D12),
not a `DATE` type. It's populated by Python, not a static migration, because
the date range is **derived from the actual data** (min/max submission date
plus 30 days of padding) rather than hardcoded — a hardcoded range would
silently go stale the moment newer reviews arrived.

**`dim_brand`** (304 rows) — straightforward, keyed on the source `brand_id`
as a business key so `ON CONFLICT` has a target.

**`dim_product`** (8,494 rows) — the three category levels are **flattened**
as plain text columns rather than snowflaked into their own `dim_category`
table (unlike the OLTP 3nf layer, where they're normalized into a real
table). The reasoning: the dashboard filters/groups on category constantly,
and a star schema is explicitly willing to pay redundancy for that. Brand,
however, **is** snowflaked (kept as an FK to `dim_brand`), because brand is a
genuine analytic entity in its own right — "rating by brand" is business
question 1 — and joining against only 304 rows is cheap. `price_band` is a
**derived attribute computed once in the ETL** (`etl/transform.py`), not
stored in the source, specifically so every dashboard visual that groups by
price uses identical bucket boundaries — computing bands per-visual inside
Power BI is exactly how two charts on the same dashboard end up disagreeing
with each other.

**`dim_customer`** (503,216 rows) — **identity only**: just a surrogate key
and the business key `customer_id`. No skin_tone, skin_type, eye_color, or
hair_color. This is explicitly called out in the migration's own comment as
"the single most important decision in this warehouse" (D2) and is a direct
correction of an earlier hand-written schema that got this wrong. The
reasoning, worth restating precisely: 22,503 authors (4.47%) recorded more
than one distinct value for at least one of those four attributes, across
149,788 reviews (13.69% of the dataset). If those attributes lived on
`dim_customer` behind a unique key, the design would silently force one
profile per person and **mis-tag roughly one review in seven** — with no
constraint violation, nothing downstream ever noticing. And it would corrupt
exactly the one business question (#4) those attributes exist to answer.

**`dim_reviewer_profile`** (1,896 rows loaded; 2,003 of 4,200 theoretically possible
combinations) — this is where those four attributes actually live: a **junk
dimension**, one row per distinct combination of skin_tone/skin_type/eye_color/hair_color,
at the grain they were genuinely recorded — per review. The alternative
(four separate dimension tables) would mean four more FK columns on a
1.09M-row fact table for no analytic benefit; carrying them as raw text
columns on the fact itself would mean repeating those strings 1.09M times.
Bundling low-cardinality correlated attributes into one junk dimension is the
standard Kimball answer, and 1,896 rows costs almost nothing to join against.
No `NULL` members — missing answers were already mapped to `'Unknown'` at the
staging boundary, and `'Unknown'` is treated as a real, meaningful answer
("reviewer chose not to say"), not a placeholder to be filtered out.

### The fact table — `fact_reviews`

One row per review, ~1.09M rows total. Foreign keys to `dim_product`,
`dim_customer`, `dim_reviewer_profile`, and `dim_date` — **deliberately no
`brand_key`** (D11): brand is functionally determined by product, so copying
it onto the fact would add zero information while creating a way for the fact
and the dimension to silently disagree after a bad load. Brand-level analysis
always joins through `dim_product`.

Measures: `rating` (`CHECK BETWEEN 1 AND 5`), `is_recommended` (nullable —
167,988 reviews don't answer it), `helpfulness` (nullable, never imputed —
D5), the three feedback counts, `review_length`. **No `review_text`** — 350MB
of free text has no place at this grain; `review_length` carries the one
analytically useful signal in 4 bytes.

`submission_date` is kept on the fact **alongside** `date_key`, even though
they're redundant with each other — because the incremental watermark needs
`MAX()` of a real date, and unpacking that from an integer `YYYYMMDD` key on
every incremental run is exactly the kind of cleverness that breaks quietly.

`UNIQUE(source_row_id, product_id)` drives `ON CONFLICT DO NOTHING`, making
every load idempotent. One index per FK column, plus one on
`submission_date` because the watermark query hits it on every incremental
run.

---

## 6. The ETL package (`etl/`) and `pipeline.py`

Four modules, each with one job, matching the reference project's module
boundaries:

- **`extract.py`** — a generic `extract(conn, sql, params=None)` helper, with
  a named function per table on top of it, each with `_full` /
  `_incremental` / `_all` variants where relevant. Reads from
  `sephora_oltp.staging`.
- **`transform.py`** — turns extracted DataFrames into exactly the shape each
  warehouse table needs: resolves natural keys to surrogate keys via lookup
  merges, computes derived columns (`price_band`), and every place a merge
  key fails to resolve funnels through one function, `_drop_unmatched`, which
  logs every dropped row — a single choke point so a silent row-drop can
  never happen invisibly. `build_fact_reviews` does **four merges in one
  pass**: product, customer, the reviewer-profile junk dimension (matched on
  all four attributes *together*, which is what makes it a junk-dimension
  lookup rather than four separate ones), and date. Surrogate keys are
  explicitly cast to `int64` after merging — a merge that produces any `NaN`
  silently upgrades pandas' int column to `float64`, and a float landing in
  an `INTEGER` column is a type error, not a formatting detail.
- **`quality.py`** — a **gate, not a fixer**. It only ever raises
  `DataQualityError`; it never repairs bad data (repairing belongs in
  `clean.py`, where it's logged and counted — a check that quietly fixes what
  it finds can never fail, so it can never tell you anything useful). Checks
  available: row count, no-null-keys, no-negative-values, value-range,
  referential-integrity, unique-key. An **empty DataFrame skips the gate
  rather than failing it** — an incremental run with nothing new to load is a
  valid, expected outcome, not a fault.
- **`load.py`** — the `_records`/`_execute` helper pair; every insert targets
  a natural or business key with `ON CONFLICT ... DO NOTHING`, so any load
  can be safely re-run.

`pipeline.py` is the local (non-Airflow) runner, wiring these four modules
together with 4 run modes (full dimension reload, incremental fact load,
full fact reload, etc.), all verified working.

**8 fault-injection tests** (`tests/test_quality.py`) prove the quality gate
actually *rejects* bad data — null keys, negative values, out-of-range
ratings, duplicate business keys, and so on — not just that it accepts good
data. All 8 pass.

---

## 7. Running the pipeline — measured results

- **Full load** (`pipeline.py --full-reload`): 1,043,868 fact rows inserted
  (everything before 2023-01-01); dimensions loaded 304 brands / 8,494
  products / 503,216 customers / 1,896 reviewer profiles seen in that batch /
  5,379 dates. Fact load took 62 seconds.
- **Idempotency, real case**: re-running the full load offered the same
  1,043,868 rows again and inserted **0** — proving `ON CONFLICT DO NOTHING`
  actually works end to end, not just in theory.
- **Incremental load**: watermark read as 2022-12-31, extracted and inserted
  all **49,503** rows from 2023.
- **Idempotency, empty case**: re-running the incremental load with the
  watermark now at 2023-03-21 extracted **0** rows, and the quality gate
  correctly skipped rather than failing on an empty frame.
- **Final warehouse state**: `fact_reviews` holds **1,093,371** rows — an
  exact match to `staging.review`, date range 2008-08-28 → 2023-03-21,
  average rating **4.2990**.

---

## 8. Orchestrating with Airflow (`dags/sephora_dw_pipeline_staged.py`)

A single **staged DAG** (Airflow 3.3.0, LocalExecutor, Docker Compose) that
wraps the same `etl/` functions `pipeline.py` calls, but arranged as
independently retryable tasks rather than one big Python callable.

**Why staged rather than one task per table**: every extract/load pair is
independently retryable, a load failure doesn't need to re-hit the OLTP
database, and the Airflow Graph view names the exact stage that failed
instead of showing one undifferentiated red box.

Shape of the DAG:
- Three dimension branches (brand, customer, reviewer_profile) run **in
  parallel**, each generated from a small config list (`DIM_CONFIGS`) rather
  than hand-copied three times — so the three can't drift apart from each
  other in behavior, while still getting their own distinct, individually
  retryable task IDs in the Airflow UI.
- `dim_product` has its own extract/load pair because it depends on
  `dim_brand` being loaded first (it needs brand surrogate keys) — so it's
  wired to run *after* the brand branch, not in parallel with it.
- `dim_date` has no source table at all — it's generated purely from the
  min/max date range read out of OLTP, with 30 days of padding, exactly as
  described above (D12).
- The **fact table gets 4 separate staged tasks**: extract → transform →
  quality → load, each writing its intermediate result to a small Postgres
  staging table (`dw.stg_fact_extract`, `dw.stg_fact_transformed`, etc.)
  tagged with the DAG run's own `batch_id`, so retries of one stage don't
  duplicate or corrupt another stage's data.
- The **incremental watermark is captured inside `extract_fact_to_staging`,
  before this run writes anything** — this ordering matters: reading the
  watermark any later in the run risks reading a value the same run has
  already advanced past.
- The quality-check task raises `AirflowFailException` on a genuine data
  quality failure (rather than a plain exception) — this makes Airflow fail
  the task immediately instead of burning its 2-retry budget on something
  that isn't transient and will never pass on retry.
- `load_fact_from_staging` reads and writes **in chunks of 100,000 rows**
  rather than one pass. This is a direct fix for a real failure encountered
  during testing (documented as D15): the very first full-reload attempt got
  SIGKILLed, because reading all 1,043,868 rows into one DataFrame and then
  building a Python list of tuples from it meant two full in-memory copies of
  the batch existing simultaneously inside the container. Chunking caps peak
  memory at a fixed size regardless of how large the total batch is.
- `cleanup_staging` runs with `trigger_rule="all_done"` (not the default
  `all_success`) — a **failed** run still has to clean up its own staged rows,
  or they'd sit in the staging tables forever and corrupt the next run.

**Runs, both verified green:**
- **Full reload**: all tasks green, 1,043,868 fact rows loaded (after the
  chunking fix above).
- **Incremental**: all tasks green in **22 seconds**, 49,503 new rows
  bringing the total to 1,093,371.
- Staging cleanup left all 6 staging tables at 0 rows after both runs.

---

## 9. Analytics views (`sql/analytics/views/`)

Ten SQL views expose the warehouse at dashboard-ready grains. Keeping the
definitions in versioned SQL means the Streamlit app and the validation script
share one source of truth.

1. **`vw_rating_by_brand`** — BQ1 brand performance with explicit sample size.
2. **`vw_rating_by_category`** — BQ1 category performance at the useful
   secondary-category level (D16).
3. **`vw_review_trend_monthly`** — BQ5 monthly rating and volume trend.
4. **`vw_rating_by_price_band`** — BQ3 ordered price bands and rating spread.
5. **`vw_rating_by_skin_type`** — BQ4 skin-type comparison through the junk
   dimension created for review-level profiles.
6. **`vw_kpi_summary`** — the single-row dashboard KPI strip.
7. **`vw_hype_vs_reality`** — BQ2 product love/rating gap for products with at
   least 50 reviews.
8. **`vw_review_volume_by_month`** — rolling volume, cumulative volume, growth,
   and the partial-month flag using window functions.
9. **`vw_rating_by_skin_tone`** — BQ4 skin-tone comparison without hiding the
   `Unknown` group.
10. **`vw_rating_by_review_length`** — mutually exclusive review-length buckets,
    rating variation, and the 1-star/5-star tails.

`sql/validation/dashboard_checks.sql` is deliberately separate from the view
DDL. It changes nothing; it re-runs headline queries and reconciles every
full-population view to `fact_reviews`.

### Headline findings

- **Overall**: 1,093,371 reviews, average rating **4.2990**, and **83.99%**
  recommend.
- **BQ3**: price and satisfaction form an inverted U. The $50–100 band peaks at
  **4.3335**; $100+ falls to **4.2708**. Rating variation also narrows as price
  rises.
- **BQ2**: The Ordinary Vitamin C Suspension combines 132,601 loves with a
  **3.4456** rating, the largest measured hype gap at the default floor.
- **BQ1**: MARA leads eligible brands at 4.8608; Topicals trails at 3.6590.
  Cleansers lead the high-volume secondary categories at 4.3443, while
  Sunscreen is lowest at 4.1665.
- **BQ4**: skin-type and skin-tone differences are real but small; the
  skin-type spread is only 0.038 stars and is presented as a weak signal.
- **BQ5**: volume peaked at 215,278 reviews in 2020 while rating reached its
  lowest yearly average, 4.2075; ratings recovered by 2022.
- **Review length**: longer reviews are more moderate, not more negative. Both
  the 1-star and 5-star shares shrink and rating standard deviation falls from
  1.2555 to 1.0589.

---

## 10. Documentation and process discipline

Throughout, three documents were kept as living records rather than written
retroactively at the end:

- **`docs/09_decision_log.md`** — 23 numbered decisions (D1–D23), each with
  its reasoning, written at the point the decision was made.
- **`docs/10_production_readiness_checklist.md`** — a 13-section production-readiness checklist
  (ingestion, cleaning, modeling, incremental loading, idempotency,
  modularity, logging, query/performance, orchestration, quality testing,
  version control, analytics output, documentation) checked off item by item
  against what was actually verified — not aspirational.
- **`CLAUDE.md`** — the running checkpoint, updated at the end of every
  stage with the actual measured numbers from that stage's run, never
  estimated.

Git history mirrors this discipline: one branch per project phase, merged to
`main` with `--no-ff` so the phase structure stays visible in the graph
(`git log` shows discrete merge commits for phases 3, 4, 5, and 6–8).

---

## 11. Where things stand right now

Exploration, cleaning, the 3NF OLTP database, the star-schema warehouse, the
ETL package, all three load modes, the 16-task Airflow DAG, 10 analytics views,
and the two-page Streamlit dashboard are **built, run, and verified** with
measured numbers. The host suite has 51 passing tests, and the container-side
DAG verifier has 11 passing assertions.

The remaining delivery work is presentation packaging: capture the final DAG
and dashboard evidence, assemble the eight-minute deck, and merge the completed
dashboard branch. External enrichment, a `highlights` bridge, and an
`EXPLAIN ANALYZE` benchmark remain deliberate out-of-scope items rather than
unfinished pipeline requirements.
