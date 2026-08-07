"""
app.py
------
Streamlit dashboard over sephora_dw. Two pages, five business questions.

LIVE connection, not a static export. Every number on screen is fetched from
Postgres when the page renders, so running the incremental DAG during the demo
and hitting "Refresh data" visibly moves the review count. A CSV export could
not do that, and a screenshot certainly could not.

Queries hit the curated VIEWS in dw, not raw fact/dim joins, wherever a view
exists. The reason is single-source-of-truth: the same SQL backs the dashboard
and sql/validation/dashboard_checks.sql, so if the two ever disagree it is a
bug in one of them rather than two independent definitions that drifted.

Run:
    py -m streamlit run dashboard/app.py
"""

import math
import os

import pandas as pd
import plotly.express as px
import psycopg2
import streamlit as st
from dotenv import load_dotenv

# Anchored to the repo root rather than bare load_dotenv(). python-dotenv walks
# up from the CALLING FILE's directory, which works when Streamlit is launched
# from the repo root and silently loads nothing when it isn't — leaving every
# connection setting None and the app pointing at localhost:5432, which on this
# machine is a different project's database entirely.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(REPO_ROOT, ".env"))

st.set_page_config(
  page_title="Sephora Reviews Analytics",
  page_icon="💄",
  layout="wide",
)

DW_CONFIG = dict(
  host=os.getenv("DW_DB_HOST"),
  port=os.getenv("DW_DB_PORT"),
  dbname=os.getenv("DW_DB_NAME"),
  user=os.getenv("DW_DB_USER"),
  password=os.getenv("DW_DB_PASSWORD"),
)

# Colour-blind safe. The rating scale is sequential (more is better) and the
# hype scale is diverging (zero is meaningful in both directions) - using one
# palette for both would imply they mean the same thing.
SEQ = "Viridis"
DIV = "RdBu_r"


# --------------------------------------------------------------------------
# Data access
# --------------------------------------------------------------------------

@st.cache_resource
def get_connection():
  """One pooled connection for the session.

  cache_resource, not cache_data: a connection is a handle, not a value, and
  reopening it on every rerun would cost a round trip per widget interaction.
  """
  return psycopg2.connect(**DW_CONFIG)


@st.cache_data(ttl=300)
def q(sql: str, params: tuple = None) -> pd.DataFrame:
  """Run a query and cache the RESULT for 5 minutes.

  The TTL is what makes 'live' honest: filter changes are instant, but the
  numbers cannot silently go stale for longer than 5 minutes, and the sidebar
  Refresh button clears the cache outright for a demo.
  """
  conn = get_connection()
  try:
    return pd.read_sql_query(sql, conn, params=params)
  except psycopg2.Error:
    # A dropped connection (container restart mid-demo) is recoverable: the
    # rollback clears the aborted transaction so the next query works.
    conn.rollback()
    raise


def kpi_row():
  return q("SELECT * FROM dw.vw_kpi_summary").iloc[0]


# --------------------------------------------------------------------------
# Live warehouse status
# --------------------------------------------------------------------------

def live_status_strip(k):
  """Show the warehouse watermark and row count, with a delta across refreshes.

  Reads the SAME vw_kpi_summary row the KPI metrics above it use — deliberately
  not a second `SELECT max(submission_date) FROM dw.fact_reviews`, which would be
  a query path that could disagree with the view under caching.

  The delta is the point of the demo: load `historical` mode, trigger the
  incremental DAG, click Refresh, and the count visibly jumps. The baseline is
  frozen by the Refresh button (see sidebar_filters), NOT updated on every
  render — otherwise moving any slider would silently reset the comparison and
  the jump would never be visible.
  """
  current = int(k["total_reviews"])
  baseline = st.session_state.get("reviews_baseline")

  # Recorded for the Refresh button to pick up on the NEXT rerun. Session state
  # survives reruns, so at click time this still holds what was last displayed.
  st.session_state["reviews_current"] = current

  delta = None
  if baseline is not None and current != baseline:
    delta = f"{current - baseline:+,} since last refresh"

  with st.container(border=True):
    c1, c2, c3 = st.columns([1, 1, 2])
    c1.metric("Warehouse watermark", str(k["latest_review"]))
    c2.metric("Rows in fact_reviews", f"{current:,}", delta=delta)
    with c3:
      st.markdown("**Live connection — not an export**")
      st.caption(
        "Run the Airflow DAG in incremental mode, then click **Refresh data** "
        "in the sidebar — this number moves live. The watermark is "
        "`max(submission_date)`, which is also what the pipeline reads to decide "
        "where the next incremental load starts."
      )


# --------------------------------------------------------------------------
# Sidebar — the interactive filters
# --------------------------------------------------------------------------

def sidebar_filters():
  st.sidebar.title("Filters")
  st.sidebar.caption(
    "These are real query parameters — every chart below re-queries Postgres "
    "when you change them."
  )

  categories = q("""
    SELECT DISTINCT secondary_category
    FROM dw.dim_product
    WHERE secondary_category IS NOT NULL
      AND product_key IN (SELECT DISTINCT product_key FROM dw.fact_reviews)
    ORDER BY 1
  """)["secondary_category"].tolist()

  selected_categories = st.sidebar.multiselect(
    "Category (secondary)",
    options=categories,
    default=categories,
    help="Primary category is always 'Skincare' in this dataset (D16), so "
         "secondary is the level that actually varies.",
  )

  bounds = q("""
    SELECT min(submission_date) AS lo, max(submission_date) AS hi
    FROM dw.fact_reviews
  """).iloc[0]

  date_range = st.sidebar.slider(
    "Review date range",
    min_value=bounds["lo"],
    max_value=bounds["hi"],
    value=(bounds["lo"], bounds["hi"]),
    format="YYYY-MM",
  )

  min_reviews = st.sidebar.number_input(
    "Minimum reviews per brand/product",
    min_value=1, max_value=5000, value=500, step=50,
    help="Without a floor, a 'top brand' list is just brands with one 5-star "
         "review. This is the single most important control on the page.",
  )

  st.sidebar.divider()
  if st.sidebar.button("Refresh data", use_container_width=True):
    # Freeze whatever is currently on screen as the comparison point BEFORE
    # clearing the cache, so the status strip can show how far the warehouse
    # moved while the DAG was running.
    st.session_state["reviews_baseline"] = st.session_state.get("reviews_current")
    st.cache_data.clear()
    st.rerun()

  st.sidebar.caption(
    "Click Refresh after running the Airflow DAG to see new rows appear."
  )

  return selected_categories, date_range, min_reviews


# --------------------------------------------------------------------------
# Page 1 — Overview
# --------------------------------------------------------------------------

def page_overview(categories, date_range, min_reviews):
  st.title("Sephora Skincare Reviews — Overview")

  k = kpi_row()
  c1, c2, c3, c4, c5 = st.columns(5)
  c1.metric("Reviews", f"{k['total_reviews']:,}")
  c2.metric("Reviewers", f"{k['total_reviewers']:,}")
  c3.metric("Avg rating", f"{k['avg_rating']:.3f}")
  c4.metric("Recommend", f"{k['recommend_pct']:.1f}%")
  # Deliberately shows coverage rather than the catalogue count alone: only
  # 2,351 of 8,494 products have any reviews, and a bare "8,494" would imply
  # a coverage this data does not have.
  c5.metric("Products reviewed",
            f"{k['products_reviewed']:,} / {k['products_in_catalogue']:,}")

  st.caption(
    f"Data range {k['earliest_review']} → {k['latest_review']}. "
    f"Helpfulness averaged only over the {k['reviews_with_feedback']:,} reviews "
    f"that actually received a vote — it is undefined, not zero, elsewhere (D5)."
  )

  live_status_strip(k)

  st.divider()

  # ---- BQ5: volume over time -------------------------------------------
  st.subheader("BQ5 — How do review volume and rating trend over time?")

  trend = q("""
    SELECT month_start, review_count, avg_rating, rolling_3m_avg_rating,
           cumulative_avg_rating, is_partial_month
    FROM dw.vw_review_volume_by_month
    WHERE month_start BETWEEN %s AND %s
    ORDER BY month_start
  """, (date_range[0], date_range[1]))

  if trend.empty:
    st.info("No reviews in the selected range.")
  else:
    left, right = st.columns([3, 2])

    with left:
      fig = px.bar(trend, x="month_start", y="review_count",
                   title="Review volume by month",
                   labels={"month_start": "", "review_count": "Reviews"})
      # The final month is partial (data ends 21 March 2023). Flagging it stops
      # the drop being read as a collapse in demand.
      if bool(trend.iloc[-1]["is_partial_month"]):
        fig.add_annotation(
          x=trend.iloc[-1]["month_start"], y=trend.iloc[-1]["review_count"],
          text="partial month", showarrow=True, arrowhead=2, yshift=10)
      st.plotly_chart(fig, use_container_width=True)

    with right:
      melted = trend.melt(
        id_vars="month_start",
        value_vars=["avg_rating", "rolling_3m_avg_rating",
                    "cumulative_avg_rating"],
        var_name="series", value_name="rating")
      fig = px.line(melted, x="month_start", y="rating", color="series",
                    title="Average rating: monthly vs smoothed",
                    labels={"month_start": "", "rating": "Avg rating"})
      st.plotly_chart(fig, use_container_width=True)

    st.caption(
      "Monthly averages are noisy in the early years when volume was low. The "
      "rolling 3-month and cumulative lines are SQL window functions in "
      "`vw_review_volume_by_month`, not chart smoothing — the same numbers "
      "appear in the validation script."
    )

  st.divider()

  # ---- BQ1: brands ------------------------------------------------------
  st.subheader("BQ1 — Which brands earn the highest ratings, and which "
               "underperform?")

  brands = q("""
    SELECT brand_name, review_count, avg_rating, recommend_pct, avg_price_usd
    FROM dw.vw_rating_by_brand
    WHERE review_count >= %s
    ORDER BY avg_rating DESC
  """, (int(min_reviews),))

  if brands.empty:
    st.info(f"No brand has at least {min_reviews:,} reviews. Lower the filter.")
  else:
    top = brands.head(10).iloc[::-1]
    bottom = brands.tail(10)

    left, right = st.columns(2)
    with left:
      fig = px.bar(top, x="avg_rating", y="brand_name", orientation="h",
                   color="avg_rating", color_continuous_scale=SEQ,
                   title=f"Best-rated brands (min {min_reviews:,} reviews)",
                   labels={"avg_rating": "Avg rating", "brand_name": ""})
      fig.update_layout(coloraxis_showscale=False)
      st.plotly_chart(fig, use_container_width=True)
    with right:
      fig = px.bar(bottom, x="avg_rating", y="brand_name", orientation="h",
                   color="avg_rating", color_continuous_scale=SEQ,
                   title=f"Worst-rated brands (min {min_reviews:,} reviews)",
                   labels={"avg_rating": "Avg rating", "brand_name": ""})
      fig.update_layout(coloraxis_showscale=False)
      st.plotly_chart(fig, use_container_width=True)

    st.caption(
      f"{len(brands)} of 304 brands clear the {min_reviews:,}-review floor. "
      "Drop the floor to 1 and the top of this chart becomes brands with a "
      "single 5-star review — which is why the control exists."
    )

  # ---- BQ1b: categories -------------------------------------------------
  st.subheader("BQ1b — Which categories rate best?")

  cats = q("""
    SELECT secondary_category,
           sum(review_count)                                           AS reviews,
           round(sum(avg_rating * review_count) / sum(review_count), 4) AS avg_rating
    FROM dw.vw_rating_by_category
    WHERE secondary_category = ANY(%s)
    GROUP BY secondary_category
    ORDER BY reviews DESC
  """, (categories,))

  if cats.empty:
    st.info("Select at least one category in the sidebar.")
  else:
    fig = px.scatter(cats, x="reviews", y="avg_rating", size="reviews",
                     color="avg_rating", color_continuous_scale=SEQ,
                     text="secondary_category",
                     title="Category volume vs average rating",
                     labels={"reviews": "Reviews", "avg_rating": "Avg rating"})
    fig.update_traces(textposition="top center")
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
      "Grouped on SECONDARY category: every reviewed product in this dataset "
      "is 'Skincare' at the primary level, so a primary-category chart would "
      "be a single bar (D16)."
    )


# --------------------------------------------------------------------------
# Page 2 — Deep dive
# --------------------------------------------------------------------------

def page_analysis(categories, date_range, min_reviews):
  st.title("Deep dive — price, hype and skin profile")

  # ---- BQ2: hype vs reality --------------------------------------------
  st.subheader("BQ2 — Hype vs reality: which products are loved more than "
               "they deserve?")

  # Slider bounds come from the view itself, so even the range of the control
  # traces back to the data rather than to a guessed constant. Deliberately NOT
  # narrowed by the category filter: a slider whose end-points jump every time
  # you tick a category is impossible to reason about mid-demo.
  gap_bounds = q("""
    SELECT min(hype_gap) AS lo, max(hype_gap) AS hi, count(*) AS products
    FROM dw.vw_hype_vs_reality
  """).iloc[0]
  gap_lo = int(math.floor(float(gap_bounds["lo"]) * 100))
  gap_hi = int(math.ceil(float(gap_bounds["hi"]) * 100))

  min_gap = st.slider(
    "Minimum hype gap (percentile points)",
    min_value=gap_lo, max_value=gap_hi, value=gap_lo, step=1,
    help="hype_gap is loves-percentile minus rating-percentile. 0 means a "
         "product is loved exactly as much as its rating justifies; +40 means "
         "it sits 40 percentile points higher on loves than on rating. Starts "
         "at the minimum so the scatter opens on the full catalogue.",
  )

  hype = q("""
    SELECT product_name, brand_name, secondary_category, price_usd,
           loves_count, review_count, avg_rating, hype_gap
    FROM dw.vw_hype_vs_reality
    WHERE secondary_category = ANY(%s)
      AND hype_gap >= %s
    ORDER BY hype_gap DESC
  """, (categories, min_gap / 100.0))

  if hype.empty:
    st.info("No products clear that hype gap in the selected categories.")
  else:
    fig = px.scatter(
      hype, x="loves_count", y="avg_rating",
      size="review_count", color="hype_gap",
      color_continuous_scale=DIV, color_continuous_midpoint=0,
      hover_data=["product_name", "brand_name", "price_usd"],
      title="Loves (intention) vs average rating (satisfaction)",
      labels={"loves_count": "Loves / wishlist adds",
              "avg_rating": "Avg rating", "hype_gap": "Hype gap"},
    )
    st.plotly_chart(fig, use_container_width=True)

    st.caption(
      "`loves_count` is recorded BEFORE purchase (a wishlist add); rating is "
      "recorded after. Red = far more loved than its rating justifies. Both "
      "signals are percentile-ranked in SQL so a cheap moisturizer and a $300 "
      "serum are comparable. Minimum 50 reviews per product. "
      f"**{len(hype):,} of {int(gap_bounds['products']):,}** products clear the "
      f"current hype-gap threshold ({min_gap:+d} points) — drag the slider "
      "right and the cloud thins to the worst offenders."
    )

    # The sleeper-hit tail is queried separately and NOT filtered by the
    # slider. It is the opposite end of the same distribution, so a
    # "minimum hype gap" would empty it the moment the slider left its floor,
    # which reads as a bug rather than as a filter doing its job.
    sleepers = q("""
      SELECT product_name, brand_name, loves_count, review_count,
             avg_rating, hype_gap
      FROM dw.vw_hype_vs_reality
      WHERE secondary_category = ANY(%s)
      ORDER BY hype_gap ASC
      LIMIT 10
    """, (categories,))

    left, right = st.columns(2)
    with left:
      st.markdown("**Most overhyped** — high loves, low rating")
      st.dataframe(
        hype.head(10)[["product_name", "brand_name", "loves_count",
                       "review_count", "avg_rating", "hype_gap"]],
        hide_index=True, use_container_width=True)
      st.caption("Filtered by the hype-gap slider above.")
    with right:
      st.markdown("**Sleeper hits** — better than their love count suggests")
      st.dataframe(sleepers, hide_index=True, use_container_width=True)
      st.caption("The opposite tail — not affected by the slider.")

  st.divider()

  # ---- BQ3: price vs rating --------------------------------------------
  st.subheader("BQ3 — Does price predict satisfaction?")

  bands = q("""
    SELECT price_band, band_order, review_count, product_count,
           avg_rating, recommend_pct, rating_stddev
    FROM dw.vw_rating_by_price_band
    ORDER BY band_order
  """)

  left, right = st.columns(2)
  with left:
    fig = px.bar(bands, x="price_band", y="avg_rating",
                 color="avg_rating", color_continuous_scale=SEQ,
                 title="Average rating by price band",
                 labels={"price_band": "", "avg_rating": "Avg rating"})
    # The signal is a ~0.1 star spread. A zero-based axis would flatten it into
    # five identical bars and hide the finding entirely.
    fig.update_yaxes(range=[bands["avg_rating"].min() - 0.05,
                            bands["avg_rating"].max() + 0.05])
    fig.update_layout(coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)

  with right:
    fig = px.line(bands, x="price_band", y="rating_stddev", markers=True,
                  title="Rating spread (std dev) by price band",
                  labels={"price_band": "", "rating_stddev": "Std dev"})
    st.plotly_chart(fig, use_container_width=True)

  st.caption(
    "Not a straight line — an inverted U peaking at $50-100 and falling back "
    "above $100. The steadily falling standard deviation is the sturdier "
    "finding: expensive products are not just rated slightly higher, they are "
    "rated far more CONSISTENTLY. Note the truncated y-axis on the left: the "
    "whole spread is about a tenth of a star."
  )

  # ---- product-level scatter -------------------------------------------
  price_bounds = q("""
    SELECT min(price_usd) AS lo, max(price_usd) AS hi
    FROM dw.vw_hype_vs_reality
  """).iloc[0]
  price_lo = int(math.floor(float(price_bounds["lo"])))
  price_hi = int(math.ceil(float(price_bounds["hi"])))

  price_range = st.slider(
    "Price range (USD) — filters the product scatter below",
    min_value=price_lo, max_value=price_hi,
    value=(price_lo, price_hi), step=1, format="$%d",
    help="Bounds the scatter only. The banded chart above is left whole on "
         "purpose: it comes from vw_rating_by_price_band, whose bands are the "
         "thing being compared.",
  )

  scatter = q("""
    SELECT price_usd, avg_rating, review_count, product_name, brand_name,
           secondary_category
    FROM dw.vw_hype_vs_reality
    WHERE secondary_category = ANY(%s)
      AND price_usd BETWEEN %s AND %s
  """, (categories, price_range[0], price_range[1]))

  if scatter.empty:
    st.info("No products in that price range for the selected categories.")
  else:
    fig = px.scatter(
      scatter, x="price_usd", y="avg_rating", size="review_count",
      color="secondary_category", hover_data=["product_name", "brand_name"],
      trendline="ols", trendline_scope="overall",
      title="Every product: price vs rating (with trend line)",
      labels={"price_usd": "Price (USD)", "avg_rating": "Avg rating"},
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
      "The banded view above aggregates this cloud. At product level the "
      "relationship is weak — price explains very little of the variation in "
      "satisfaction, which is itself the answer to BQ3. "
      f"Showing {len(scatter):,} products between ${price_range[0]} and "
      f"${price_range[1]}; the OLS trend line is refitted to whatever the "
      "slider selects, so narrowing the range genuinely changes the slope."
    )

  st.divider()

  # ---- BQ4: skin profile ------------------------------------------------
  st.subheader("BQ4 — Do reviewers with different skin profiles rate "
               "differently?")

  # Replaces a hardcoded HAVING >= 1000. The floor was always a judgement call;
  # making it a parameter lets the audience watch the judgement being made -
  # drop it to 0 and 'ebony' appears with 3 reviews and a wild average.
  min_group_reviews = st.slider(
    "Minimum reviews per skin group",
    min_value=0, max_value=25000, value=1000, step=500,
    help="Applied as HAVING sum(review_count) >= this, in SQL, to both charts. "
         "A group of 3 reviews produces an average that swings a full star on "
         "one more review — visible noise, not a finding.",
  )

  left, right = st.columns(2)

  with left:
    skin_type = q("""
      SELECT skin_type,
             sum(review_count)                                            AS reviews,
             round(sum(avg_rating * review_count) / sum(review_count), 4) AS avg_rating
      FROM dw.vw_rating_by_skin_type
      WHERE secondary_category = ANY(%s)
      GROUP BY skin_type
      HAVING sum(review_count) >= %s
      ORDER BY avg_rating DESC
    """, (categories, int(min_group_reviews)))

    if skin_type.empty:
      st.info(f"No skin type has {min_group_reviews:,} reviews. Lower the floor.")
    else:
      fig = px.bar(skin_type, x="skin_type", y="avg_rating",
                   color="avg_rating", color_continuous_scale=SEQ,
                   title=f"Average rating by skin type "
                         f"(min {min_group_reviews:,} reviews)",
                   labels={"skin_type": "", "avg_rating": "Avg rating"})
      fig.update_yaxes(range=[skin_type["avg_rating"].min() - 0.05,
                              skin_type["avg_rating"].max() + 0.05])
      fig.update_layout(coloraxis_showscale=False)
      st.plotly_chart(fig, use_container_width=True)

  with right:
    skin_tone = q("""
      SELECT skin_tone,
             sum(review_count)                                            AS reviews,
             round(sum(avg_rating * review_count) / sum(review_count), 4) AS avg_rating
      FROM dw.vw_rating_by_skin_tone
      WHERE secondary_category = ANY(%s)
      GROUP BY skin_tone
      HAVING sum(review_count) >= %s
      ORDER BY avg_rating DESC
    """, (categories, int(min_group_reviews)))

    if skin_tone.empty:
      st.info(f"No skin tone has {min_group_reviews:,} reviews. Lower the floor.")
    else:
      fig = px.bar(skin_tone, x="skin_tone", y="avg_rating",
                   color="avg_rating", color_continuous_scale=SEQ,
                   title=f"Average rating by skin tone "
                         f"(min {min_group_reviews:,} reviews)",
                   labels={"skin_tone": "", "avg_rating": "Avg rating"})
      fig.update_yaxes(range=[skin_tone["avg_rating"].min() - 0.05,
                              skin_tone["avg_rating"].max() + 0.05])
      fig.update_layout(coloraxis_showscale=False)
      st.plotly_chart(fig, use_container_width=True)

  st.caption(
    "This is the question the junk dimension exists for. Holding these four "
    "attributes on dim_customer would have forced one profile per person and "
    "mis-tagged 13.69% of reviews — this exact chart would have been quietly "
    "wrong (D2). 'Unknown' is kept rather than filtered: it means the reviewer "
    "declined to say, which is a real answer. Note the truncated axes — the "
    "spread is real but small (~0.04), a weak signal, not a headline. "
    f"At the current floor, {len(skin_type)} skin type(s) and "
    f"{len(skin_tone)} skin tone(s) qualify; pull the floor to 0 and the two "
    "smallest tone groups reappear with a handful of reviews between them, "
    "which is what the floor is there to prevent."
  )

  st.divider()

  # ---- review length ----------------------------------------------------
  st.subheader("Does review length say anything about the rating?")

  length = q("""
    SELECT length_bucket, bucket_order, review_count, avg_review_length,
           avg_rating, recommend_pct, rating_stddev,
           pct_1_star, pct_5_star, pct_extreme
    FROM dw.vw_rating_by_review_length
    ORDER BY bucket_order
  """)

  # The Unknown bucket (no recorded length) is kept in the view so it reconciles
  # to the fact table, but it is not a LENGTH, so plotting it on an ordered
  # length axis would be a category error. It stays visible in the table below.
  plotted = length[length["length_bucket"] != "Unknown"]

  left, right = st.columns(2)
  with left:
    fig = px.bar(plotted, x="length_bucket", y="avg_rating",
                 color="avg_rating", color_continuous_scale=SEQ,
                 title="Average rating by review length",
                 labels={"length_bucket": "", "avg_rating": "Avg rating"})
    # Truncated for the same reason as the price and skin charts: the spread is
    # ~0.06 of a star. Stated in the caption rather than left to be noticed.
    fig.update_yaxes(range=[plotted["avg_rating"].min() - 0.02,
                            plotted["avg_rating"].max() + 0.02])
    fig.update_layout(coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)

  with right:
    melted = plotted.melt(
      id_vars="length_bucket", value_vars=["pct_1_star", "pct_5_star"],
      var_name="share", value_name="pct")
    fig = px.bar(melted, x="length_bucket", y="pct", color="share",
                 barmode="group",
                 title="Share of 1-star and 5-star reviews by length",
                 labels={"length_bucket": "", "pct": "% of reviews",
                         "share": ""})
    st.plotly_chart(fig, use_container_width=True)

  # Read off the view rather than written into the prose. The incremental load
  # moves these by a hundredth of a point, and a caption that quotes a number
  # the chart beside it no longer shows is worse than no caption.
  shortest, longest = plotted.iloc[0], plotted.iloc[-1]
  spread = float(plotted["avg_rating"].max() - plotted["avg_rating"].min())

  st.caption(
    "The common assumption is that unhappy customers write longer reviews. "
    "**This data does not support it.** Average rating is essentially flat "
    "across every length bucket — the left chart has a truncated y-axis and the "
    f"whole spread is still only {spread:.3f} of a star, less than the price "
    "effect. The right chart is where the signal is: going from the shortest "
    "bucket to the longest, the share of 1-star reviews falls "
    f"({shortest['pct_1_star']:.1f}% → {longest['pct_1_star']:.1f}%) **and** so "
    f"does the share of 5-star reviews ({shortest['pct_5_star']:.1f}% → "
    f"{longest['pct_5_star']:.1f}%). Short reviews are polarised; long reviews "
    "are moderate. The two extremes shrink together, which is precisely why the "
    "mean barely moves. Rating standard deviation falls across the same buckets "
    f"({shortest['rating_stddev']:.4f} → {longest['rating_stddev']:.4f}) — the "
    "same fact, stated a second way."
  )

  with st.expander("The numbers behind those two charts"):
    st.dataframe(
      length[["length_bucket", "review_count", "avg_review_length",
              "avg_rating", "recommend_pct", "rating_stddev",
              "pct_1_star", "pct_5_star", "pct_extreme"]],
      hide_index=True, use_container_width=True)
    st.caption(
      f"All {int(length['review_count'].sum()):,} rows, including the "
      f"{int(length.loc[length['length_bucket'] == 'Unknown', 'review_count'].iloc[0]):,} "
      "with no recorded length — kept so `vw_rating_by_review_length` sums back "
      "to `fact_reviews` exactly in `sql/validation/dashboard_checks.sql`, and "
      "excluded from the charts above because 'Unknown' is not a length."
    )


# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------

def main():
  try:
    get_connection()
  except psycopg2.Error as exc:
    st.error(
      f"Cannot reach the warehouse at "
      f"{DW_CONFIG['host']}:{DW_CONFIG['port']}/{DW_CONFIG['dbname']}.\n\n"
      f"{exc}\n\n"
      f"Start it with `docker compose up -d` and check your .env."
    )
    st.stop()

  categories, date_range, min_reviews = sidebar_filters()

  page = st.sidebar.radio("Page", ["Overview", "Deep dive"])
  if page == "Overview":
    page_overview(categories, date_range, min_reviews)
  else:
    page_analysis(categories, date_range, min_reviews)

  st.sidebar.divider()
  st.sidebar.caption(
    "Every figure is queried live from `sephora_dw`. Numbers here are "
    "reproducible with `sql/validation/dashboard_checks.sql` — if the two "
    "disagree, this dashboard is wrong."
  )


if __name__ == "__main__":
  main()
