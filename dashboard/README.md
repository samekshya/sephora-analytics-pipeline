# Dashboard

Streamlit app over `sephora_dw`. **One page**, five business questions, live
Postgres connection, Sephora black/white/red (**D25**).

## Running it

```powershell
py -m pip install -r requirements.txt
py -m streamlit run dashboard/app.py
```

Opens on <http://localhost:8501>. There is no navigation — the whole dashboard
is one scrolling page, so a demo cannot land on the wrong view. Needs the
warehouse container up (`docker compose up -d`) and a `.env` at the repo root —
see `.env.example`. Theme colours live in `.streamlit/config.toml` so Streamlit's
own widgets match the charts.

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

Read top to bottom. Each section states its finding **in words** under the
heading, so the page can be read without interpreting a single chart.

| # | Question | Visual | Source view |
|---|---|---|---|
| Q5 | How do volume and rating trend over time? | Monthly volume bars (partial month greyed) + monthly vs 3-month rolling rating lines | `vw_review_volume_by_month` |
| Q1 | Which brands rate best, and which underperform? | Diverging horizontal bars: each brand's distance from the 4.299 overall average | `vw_rating_by_brand` |
| Q1b | Which categories rate best? | Horizontal **dot plot**, ordered | `vw_rating_by_category` |
| Q3 | Does price predict satisfaction? | Line across the ordered price bands (the inverted U) + a spread line | `vw_rating_by_price_band` |
| Q2 | Hype vs reality — high loves, low rating | Diverging scatter, three worst direct-labelled, plus two ranked tables in an expander | `vw_hype_vs_reality` |
| Q4 | Does who reviews, or how much they write, change the rating? | Skin-type **dot plot** + review-length **small multiples** | `vw_rating_by_skin_type`, `vw_rating_by_review_length` |

### Why dots and lines rather than bars

Most effects in this data are a tenth of a star, so the axis has to be truncated
to show them at all. **A truncated axis under bars misleads**: bar length is read
from zero, so on the old price chart "Under $15" (4.2383) was drawn about six
times shorter than "$50–100" (4.3335) — a 2% difference rendered as 600%. A dot
or a line point encodes *position*, so the same truncation is honest. The
category, price and skin-type charts all changed form for this reason (D25).

Review length is **small multiples** for a related reason: the 1★ share (3–8%)
and 5★ share (61–67%) are on different scales, and sharing one axis flattened the
1★ decline — half the finding — into a strip along the baseline. A second y-axis
would be worse, not better.

### The palette

Two series colours only — red `#F5405F` and blue `#5589C7` — because the page
never plots more than two series at once. Both were run through a
colour-vision-deficiency validator against the actual card surface (worst-pair
CVD ΔE 16.1, normal-vision 29.1). A third warm hue was tried and cut: it failed
deuteranope separation against the brand red. The five price bands use a
single-hue ordinal red ramp; the hype scatter uses red↔blue with a visible
neutral midpoint.

## Interactive controls

**Four**, plus Refresh. Every one binds into the SQL and Postgres is asked
again — none filters a dataframe after the fact, which would look identical on
screen and be a different claim entirely.

| Control | Bound into | Scopes |
|---|---|---|
| **Category** (sidebar) | `secondary_category = ANY(%s)` | Brands, categories, hype, skin type, product explorer |
| **Brand** (sidebar) | `(%s = 0 OR brand_name = ANY(%s))` | The brand chart, hype vs reality, product explorer |
| **Minimum reviews per brand** (sidebar) | `WHERE review_count >= %s` | The brand chart. Without a floor the "best brand" is whichever has a single 5-star review |
| **Product name contains** (Explore section) | `product_name ILIKE %s` | The product table |
| **Refresh data** | Clears the query cache, freezes the row-count baseline | Everything — this is what makes "live" demonstrable |

### What Category does and does not scope

`vw_review_volume_by_month` and `vw_rating_by_price_band` aggregate the category
column away, so a category predicate on them is a **no-op**. Rather than let the
page look filtered when it is not, those two cards are titled *— all
categories*, the sidebar carries a note listing exactly what responds, and
selecting a subset raises a banner naming the categories in force.

The brand chart responds because **`vw_rating_by_brand_category`** was added for
it: `vw_rating_by_brand` groups by brand alone, so filtering it would silently do
nothing. Brand figures are re-aggregated from that view with a review-count
**weighted** mean, not an average of averages.

### What Brand does and does not scope

Only three views carry `brand_name` — `vw_rating_by_brand`,
`vw_rating_by_brand_category` and `vw_hype_vs_reality` — so the brand filter
reaches exactly three sections. The category chart, price bands, skin type,
review length and the monthly trend all aggregate brand away entirely; there is
no column to filter on. They stay catalogue-wide, and the banner says so rather
than leaving the reader to assume the whole page narrowed.

Two claims stand down when a brand selection is active: Q1 stops asserting that
brand outweighs every other effect (with three brands selected the spread is
whatever those three happen to differ by), and Q2's widest gap is described as
the widest *in the current selection* rather than in the catalogue.

Brand lives in the sidebar with the other scope filters. It was previously a
second multiselect inside the Explore section, which meant two brand controls
could disagree with no way to tell which one the charts above were obeying —
`test_brand_filter_scopes_the_brand_chart_and_the_explorer` asserts a second one
has not come back. **Product name contains** stays in the Explore section,
directly above the only table it scopes.

Still removed from the earlier design: the date-range, hype-gap, price-range and
skin-group sliders (D25).

## The live status strip

Folded into the KPI card itself since D25: the caption under the five metrics
carries the data range, the warehouse watermark (`max(submission_date)`) and the
row-count delta. All of it reads from the same `vw_kpi_summary` row the metrics
above use — not a second query that could disagree with it under caching.

The delta's baseline is frozen when you press **Refresh data**, not updated on
every render: otherwise any rerun would reset the comparison before the jump was
visible. Load `historical` mode, run the incremental DAG, press Refresh, and it
reads `+49,503 since last refresh`.

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

**Review volume by month** — bars are raw monthly counts. The final bar is
**grey**: data ends 21 March 2023, so March is short because the month is
incomplete, not because demand collapsed. Greyed rather than annotated, because
a floating label had nowhere to sit among 20k-tall bars without touching one.

**Monthly vs 3-month rolling rating** — two lines, not three. The monthly line
is noisy in the early years when volume was a few hundred reviews a month; the
rolling line is a SQL window function in `vw_review_volume_by_month`, not chart
smoothing. The cumulative line was dropped: three lines on one axis was clutter,
and the cumulative average answers a question nobody asked.

**Brands against the overall average** — bars measure each brand's *distance
from 4.299*, so "underperform" means something concrete. Red is above average,
blue below, and the zero line is the average a shopper actually experiences.
The caption states how many of the 304 brands clear the current floor, so the
sample the chart is drawn from is visible rather than implied.

**Categories** — a dot plot, ordered. The whole spread is 0.18 of a star against
more than a full star between brands, which is the finding: **category matters
far less than brand.**

**Price vs rating** — a line across the ordered bands, and the shape is the
point: ratings climb to 4.3335 at `$50–100` and fall back to 4.2708 above $100.
The spread line beside it turns in the **same** band — tightest at 1.0996, then
widening to 1.1366 above $100. So `$50–100` is the sweet spot on both measures.
(An earlier version of this file claimed spread "falls steadily as price rises".
It does not — see D25.)

**Hype vs reality** — `loves_count` is a wishlist add, recorded *before*
purchase; rating is recorded *after*. Raw loves are dominated by category and
price, so both are converted to percentile ranks in SQL and compared. Red points
are loved far more than their rating justifies, blue the reverse. The three worst
are direct-labelled by **product**, not brand — The Ordinary holds two of them,
so brand-only labels printed the same name twice. Minimum 50 reviews per product,
because a "worst offender" list built on 3 reviews is a list of accidents.

**Skin type** — a dot plot, axis truncated. `Unknown` is kept rather than
filtered: it means the reviewer declined to answer, which is a real answer and a
large share of the data. Hiding it would overstate how much is actually known.

**Review length** — two stacked panels, and the reason they are stacked is the
finding. Average rating is flat across every length bucket, so **the common
assumption that unhappy customers write longer reviews is not supported by this
data.** What is happening is that as reviews get longer the 1★ share falls from
8.15% to 3.73% *and* the 5★ share falls from 67.35% to 62.52%. Short reviews are
polarised, long ones moderate, and the two extremes cancel in the mean. On a
shared axis the 1★ panel — half the finding — was a flat strip against 65% bars.

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
py scripts/pipeline.py --mode historical
```

`py scripts/pipeline.py --mode historical` **does not reset a full warehouse.** Every
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
   the watermark has moved to **2023-03-21**. The Q5 trend chart has grown
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
