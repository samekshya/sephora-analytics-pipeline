# Dashboard

Streamlit app over `sephora_dw`. Two pages, five business questions, live
Postgres connection.

## Running it

```powershell
py -m pip install -r requirements.txt
py -m streamlit run dashboard/app.py
```

Opens on <http://localhost:8501>. Needs the warehouse container up
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

## Interactive controls

All three are real query parameters — every chart re-queries Postgres when they
change. `tests/integration/test_dashboard_smoke.py::test_min_reviews_filter_is_live`
asserts this rather than taking it on trust.

| Control | What it does | Why it's there |
|---|---|---|
| **Category (secondary)** | Filters products by secondary category | Primary category is always `Skincare` in this dataset (D16), so secondary is the level that varies |
| **Review date range** | Bounds the trend chart | Lets you isolate the 2020 volume spike or the 2023 incremental batch |
| **Minimum reviews** | Floor on reviews per brand/product | The most important control on the page. Set it to 1 and "best brands" becomes brands with a single 5-star review |
| **Refresh data** | Clears the query cache | Run the Airflow DAG, click this, watch the review count move — this is what makes "live" demonstrable |

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

## Caching

- `@st.cache_resource` — the Postgres connection. A handle, not a value;
  reopening it per rerun would cost a round trip on every widget interaction.
- `@st.cache_data(ttl=300)` — query results. Filter changes stay instant while
  the numbers can never be more than five minutes stale. **Refresh data**
  clears it outright for a live demo.
