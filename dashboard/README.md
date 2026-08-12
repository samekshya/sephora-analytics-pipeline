# Dashboard

Streamlit app over `sephora_dw`. Two pages, five business questions, live
Postgres connection.

## Running it

```powershell
py -m pip install -r requirements.txt
py -m streamlit run dashboard/app.py
```

Opens on <http://localhost:8501>. Use
<http://localhost:8501/?page=deep-dive> for a direct link to Deep dive; the
sidebar radio remains the normal in-app navigation. Needs the warehouse container up
(`docker compose up -d`) and a `.env` at the repo root — see `.env.example`.

If the warehouse is unreachable the app shows the connection string it tried
and stops, rather than rendering empty charts that look like "no data".

## Why Streamlit rather than Power BI

Recorded as **D18** in `docs/09_decision_log.md`. Short version: the dashboard
is part of the repository. It is versioned, diffable, and reproducible by
anyone who clones the project and runs one command — no desktop application, no
licence, no `.pbix` binary whose logic can only be inspected by opening it.
Every query it runs is plain SQL against versioned views, so the analysis can
be reviewed in a pull request like any other code.

## The five business questions and the visual that answers each

| # | Question | Page | Visual | Source view |
|---|---|---|---|---|
| BQ1 | Which brands earn the highest ratings, and which underperform? | Overview | Paired horizontal bars — best 10 / worst 10 | `vw_rating_by_brand` |
| BQ1b | Which categories rate best? | Overview | Bubble scatter, volume vs rating | `vw_rating_by_category` |
| BQ2 | Hype vs reality — high loves, low rating | Deep dive | Scatter + two ranked tables | `vw_hype_vs_reality` |
| BQ3 | Does price predict satisfaction? | Deep dive | Bar by price band + std-dev line + product scatter with OLS trend | `vw_rating_by_price_band`, `vw_hype_vs_reality` |
| BQ4 | Do skin type / skin tone change ratings? | Deep dive | Two bar charts, side by side | `vw_rating_by_skin_type`, `vw_rating_by_skin_tone` |
| BQ5 | How do volume and rating trend over time? | Overview | Monthly volume bars + three rating lines | `vw_review_volume_by_month` |
| — | Does review length say anything about the rating? | Deep dive | Rating bar + 1★/5★ share bars | `vw_rating_by_review_length` |

## Interactive controls

Every one of these is a real query parameter — the value is bound into the SQL
and Postgres is asked again. None of them filter a dataframe after the fact,
which would look identical on screen and be a different claim entirely.
`tests/integration/test_dashboard_smoke.py` asserts this per control rather
than taking it on trust: each test moves one slider and requires the
corresponding caption to change.

### Sidebar — apply to both pages

| Control | What it does | Why it's there |
|---|---|---|
| **Category (secondary)** | Filters products by secondary category | Primary category is always `Skincare` in this dataset (D16), so secondary is the level that varies |
| **Review date range** | Bounds the trend chart | Lets you isolate the 2020 volume spike or the 2023 incremental batch |
| **Minimum reviews** | Floor on reviews per brand/product | The most important control on the page. Set it to 1 and "best brands" becomes brands with a single 5-star review |
| **Refresh data** | Clears the query cache and freezes the row-count baseline | Run the Airflow DAG, click this, watch the review count move — this is what makes "live" demonstrable |
| **How to read this** | Expander: the four conventions that are easy to misread | Truncated axes, review floors, `Unknown` as a category, where to reproduce a number |

### Deep dive — one per question, sitting above the chart it drives

| Control | Bound into | Range |
|---|---|---|
| **Minimum hype gap (percentile points)** | `WHERE hype_gap >= %s` on `vw_hype_vs_reality` — filters the scatter and the "most overhyped" table | Read from the view's own `min`/`max`, so the ends are data-derived. Defaults to the minimum, i.e. the whole catalogue |
| **Price range (USD)** | `WHERE price_usd BETWEEN %s AND %s` on the product scatter | `$3`–`$449`, read from the view. The OLS trend line refits to the selection, so narrowing genuinely changes the slope |
| **Minimum reviews per skin group** | `HAVING sum(review_count) >= %s` on both BQ4 charts | 0–25,000, default 1,000. Replaces a hardcoded `HAVING >= 1000` |

Two notes on deliberate non-behaviour. The **sleeper hits** table is not filtered
by the hype-gap slider: it is the opposite tail of the same distribution, so a
minimum gap would empty it the moment the slider left its floor. The **price
band** bar chart is not filtered by the price slider: its bands are the thing
being compared, and it comes from a different view.

The slider end-points deliberately do *not* narrow when you change the category
filter. A control whose range moves while you are using it cannot be reasoned
about mid-demo.

## The live status strip

Sits directly under the KPI row on the Overview page and shows the warehouse
watermark (`max(submission_date)`) and the `fact_reviews` row count, both read
from the same `vw_kpi_summary` row the KPIs above use — not a second query that
could disagree with it under caching.

The row count carries a **delta**. The baseline is frozen when you press
**Refresh data**, not updated on every render: otherwise moving any slider would
reset the comparison before the jump was visible. Load `historical` mode, run
the incremental DAG, press Refresh, and the strip reads `+49,503 since last
refresh`.

## The data quality panel

An expander under the status strip: **"Data quality & what we dropped (and
why)"**. Everything in it is recomputed at render time — `etl/reconcile.py`
logs its counts, it does not persist them, so there is no stored summary to
read and nothing here can be stale.

- **Row accounting** across `raw.reviews` → `3nf.review` → `staging.review` →
  `dw.fact_reviews`, with the change at each step. This is the only thing in
  the app that touches the OLTP database; it degrades to the warehouse half
  with a warning if `sephora_oltp` is down rather than taking the page with it.
- **Drops by reason** — the four names `etl/transform.py` may drop a fact row
  under, each re-checked against the loaded warehouse. The *total* is measured
  as `staging.review` minus `fact_reviews`, not inferred from the four.
- **Kept, not dropped** — 561,061 undefined helpfulness scores, 167,714
  unanswered recommend flags, and the four `Unknown` reviewer attributes. These
  shape every chart above and are otherwise invisible.
- **Integrity, re-asserted just now** — orphan rows, duplicate idempotency
  keys, and how many full-population views still reconcile. That last figure
  runs the same `UNION` as `dashboard_checks.sql` and is *counted*, so it
  cannot keep claiming 8 after someone adds a ninth view.

One number in the panel is labelled **not live**: the 1,040 duplicate reviews
`clean.py` removed on `(author_id, product_id, submission_time)` before
anything reached Postgres (D4). Neither database can be queried for it. It is
stated anyway, and labelled, because the panel's claim is about what happened
to every row — not only the parts that are convenient to query.

## Reading each visual

**Review volume by month** — bars are raw monthly counts. The final month is
flagged `partial month`: data ends 21 March 2023, so its bar is short because
the month is incomplete, not because demand collapsed.

**Average rating: monthly vs smoothed** — three lines. The monthly line is
noisy in the early years when volume was a few hundred reviews a month. The
rolling 3-month and cumulative lines are SQL window functions in
`vw_review_volume_by_month`, not chart smoothing — the same numbers appear in
`sql/validation/dashboard_checks.sql`.

**Best / worst brands** — the caption states how many of the 304 brands clear
the current floor, so the sample the chart is drawn from is visible rather than
implied.

**Hype vs reality** — `loves_count` is a wishlist add, recorded *before*
purchase; rating is recorded *after*. Raw loves are dominated by category and
price, so both are converted to percentile ranks in SQL and compared. Red
points are loved far more than their rating justifies. Minimum 50 reviews per
product, because a "worst offender" list built on 3 reviews is a list of
accidents.

**Price vs rating** — **the y-axis is deliberately truncated.** The entire
spread across five price bands is about a tenth of a star; a zero-based axis
would render five identical bars and hide the finding. The truncation is called
out in the caption on the page itself. The std-dev line beside it is the
sturdier result: rating variance falls steadily as price rises.

**Skin type / skin tone** — axes truncated for the same reason. `Unknown` is
kept rather than filtered: it means the reviewer declined to answer, which is a
real answer and a large share of the data. Hiding it would overstate how much
is actually known.

**Review length vs rating** — two charts, and the left one is the less
interesting of the pair. Average rating is flat across every length bucket
(0.056 of a star, less than the price effect), so **the common assumption that
unhappy customers write longer reviews is not supported by this data.** The
signal is in the right-hand chart: as reviews get longer the share of 1-star
reviews falls from 8.2% to 3.7% *and* the share of 5-star reviews falls from
67.3% to 62.5%. Short reviews are polarised, long reviews are moderate, and the
two extremes cancel in the mean — which is exactly why the left chart looks
like nothing is happening. `rating_stddev` falling monotonically across the
same buckets is the same fact stated a second way.

The numbers in that caption are read off the view at render time rather than
written into the prose, so the incremental load cannot leave them stale.
Bucket boundaries come from the measured distribution (p25 172, median 263,
p75 402, p95 752 characters), not from round numbers picked by eye. Rows with
no recorded length are kept as an `Unknown` bucket — 1,444 of them — so the
view still sums to `fact_reviews` exactly; they are left out of the two charts
because `Unknown` is not a length.

## Trust and verification

Every number the dashboard shows is reproducible from
`sql/validation/dashboard_checks.sql`. **If the two disagree, the dashboard is
wrong** — the views and the fact table are the authority.

```powershell
docker exec -i leapfrog_sephora_postgres psql -U postgres -d sephora_dw -q -f - < sql/validation/dashboard_checks.sql
py -m pytest tests/integration/test_dashboard_smoke.py -q
```

The smoke tests execute the app through Streamlit's `AppTest` harness and
assert the KPI row matches `SELECT count(*), avg(rating) FROM dw.fact_reviews`.
A plain HTTP check would not catch this: Streamlit returns 200 even when the
script raises, because the traceback renders client-side.

## The live-refresh demo, end to end

The point being demonstrated: this is a live connection to a warehouse an
orchestrator is loading, not an export. Budget about four minutes.

**Before the audience is watching** — put the warehouse back to the historical
baseline.

```powershell
docker compose up -d                     # warehouse, if it isn't running
docker compose -f docker-compose-airflow.yml up -d
```

Then reset the fact table. **Which command you need depends on where the
warehouse currently is**, and this is the step that ruins the demo if you get
it wrong:

```powershell
# The warehouse is already fully loaded (1,093,371 rows) — the usual case
# after a rehearsal. Give the 2023 rows back to the incremental run:
docker exec leapfrog_sephora_postgres psql -U postgres -d sephora_dw -c `
  "DELETE FROM dw.fact_reviews WHERE submission_date >= '2023-01-01'"

# Starting from an empty or partial warehouse instead — ~2 min:
py pipeline.py --mode historical
```

`py pipeline.py --mode historical` **does not reset a full warehouse.** Every
load is `ON CONFLICT DO NOTHING` and nothing in the pipeline truncates, so
running it against 1,093,371 rows inserts 0 and leaves the count exactly where
it was — the property that makes the pipeline safe to re-run is the same one
that makes it useless as a reset. Use the `DELETE` above.

Confirm the baseline before you start talking:

```powershell
docker exec leapfrog_sephora_postgres psql -U postgres -d sephora_dw -c `
  "SELECT count(*), max(submission_date) FROM dw.fact_reviews"
```

Expect **1,043,868** and a watermark of **2022-12-31**.

**Live:**

1. `py -m streamlit run dashboard/app.py` → <http://localhost:8501>. The status
   strip reads **1,043,868 rows**, watermark **2022-12-31**. Say what the
   watermark is *for*: it is what the next run reads to decide where to start.
   Open the data quality panel while you are here — at the baseline it reports
   the warehouse as 49,503 rows behind staging and states that they were held
   back rather than lost, which sets up step 5.
2. Open <http://localhost:8081> (Airflow), DAG `sephora_dw_pipeline_staged` →
   **Trigger** → set `load_mode` to `incremental` → Trigger.
3. Talk over it. The incremental run takes about **22 seconds**; the graph goes
   green a task at a time. This is the moment to point at `cleanup_staging` —
   the dotted teardown edge — and explain that it cleans up after failures
   without being able to report success on the run's behalf (D24).
4. Back on the dashboard, click **Refresh data** in the sidebar.
5. The strip now reads **1,093,371** with **+49,503 since last refresh**, and
   the watermark has moved to **2023-03-21**. The BQ5 trend chart has grown
   three months of 2023, and the data quality panel's gap has closed to zero.

**Then close the loop on idempotency** — this is the part people remember.
Trigger the same DAG again, in `incremental` mode, unchanged. It goes green in
seconds, Refresh again, and the count does **not** move: the watermark is now
past the end of the data, 0 rows are extracted, and `UNIQUE(source_row_id,
product_id)` would have rejected them anyway (D13). A pipeline that is safe to
re-run is worth thirty seconds of an eight-minute talk.

To reset for a second run-through, repeat the `DELETE` above.

Both halves of this were verified end to end on 8 August 2026 — the `DELETE`
lands on exactly 1,043,868 / 2022-12-31, and the incremental restores exactly
49,503 rows with `0 already present`.

## Caching

- `@st.cache_resource` — the Postgres connection. A handle, not a value;
  reopening it per rerun would cost a round trip on every widget interaction.
- `@st.cache_data(ttl=300)` — query results. Filter changes stay instant while
  the numbers can never be more than five minutes stale. **Refresh data**
  clears it outright for a live demo.
