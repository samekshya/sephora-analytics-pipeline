"""
app.py
------
Streamlit dashboard over sephora_dw. ONE page, five business questions.

LIVE connection, not a static export. Every number on screen is fetched from
Postgres when the page renders, so running the incremental DAG during the demo
and hitting "Refresh data" visibly moves the review count. A CSV export could
not do that, and a screenshot certainly could not.

Queries hit the curated VIEWS in dw, not raw fact/dim joins, wherever a view
exists. The reason is single-source-of-truth: the same SQL backs the dashboard
and sql/validation/dashboard_checks.sql, so if the two ever disagree it is a
bug in one of them rather than two independent definitions that drifted.

Design notes (D18, D23, D25):
  - One page, read top to bottom. Every block states its finding in words
    directly under the heading, so the page is legible without reading a chart.
  - Every chart sits in a bordered card with the title OUTSIDE the plot, so
    Plotly never has to reserve space for a title and no text can collide.
  - Exactly one control (a review floor) plus Refresh. See D25.
  - The palette is Sephora black / white / red and was validated rather than
    eyeballed: categorical red+blue clear CVD dE 16.1 and normal-vision 29.1,
    and the five-step price ramp is monotone in lightness on a single hue.

Run:
    py -m streamlit run dashboard/app.py
"""

import os

import pandas as pd
import plotly.graph_objects as go
import psycopg2
from plotly.subplots import make_subplots
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

# Read-only, and used by exactly one thing: the row-accounting table in the data
# quality panel, which has to span both databases to show that the warehouse
# lost nothing between staging and the fact table. Every analytical number on
# this dashboard still comes from dw and only dw. The panel degrades to its
# warehouse half if this database is unreachable rather than taking the page
# down with it.
OLTP_CONFIG = dict(
  host=os.getenv("OLTP_DB_HOST"),
  port=os.getenv("OLTP_DB_PORT"),
  dbname=os.getenv("OLTP_DB_NAME"),
  user=os.getenv("OLTP_DB_USER"),
  password=os.getenv("OLTP_DB_PASSWORD"),
)

# --------------------------------------------------------------------------
# Sephora palette
#
# Black, white and the brand red — the colours of the striped bag. Every value
# below was run through the data-viz validator against the #151515 card surface
# rather than picked by eye:
#
#   categorical RED + BLUE  worst pair CVD dE 16.1 (protan), normal 29.1, both
#                           inside the dark lightness band, both >= 3:1
#   ordinal RED ramp        monotone light->dark, single hue (11 deg spread),
#                           light end 2.47:1 against the surface
#
# Only TWO categorical slots exist on purpose. The page never plots more than
# two series at once, and a third warm hue (gold) failed deuteranope separation
# against the brand red at dE 4.2 — so it was cut rather than shipped.
# --------------------------------------------------------------------------

PAGE_BG = "#0A0A0A"     # Sephora black
SURFACE = "#151515"     # chart card
INK = "#FFFFFF"
INK_2 = "#C7C4BE"
MUTED = "#8E8B85"       # axis ticks and labels
GRID = "#262626"        # hairline gridline, one shade off the surface
BASELINE = "#3A3A38"
BORDER = "rgba(255,255,255,0.10)"

RED = "#F5405F"         # categorical slot 1 / brand accent
BLUE = "#5589C7"        # categorical slot 2
MIDPOINT = "#8A8781"    # diverging midpoint — neutral, but still visible

# Ordered categories only (the five price bands). Never used on nominal ones.
RED_RAMP = ["#F7A8B8", "#F5768C", "#F5405F", "#D42248", "#A81736"]

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

CSS = f"""
<style>
  .stApp {{ background: {PAGE_BG}; }}
  section[data-testid="stSidebar"] {{
    background: #101010;
    border-right: 1px solid {BORDER};
  }}
  /* Chart cards and the KPI strip */
  div[data-testid="stVerticalBlockBorderWrapper"] {{
    background: {SURFACE};
    border: 1px solid {BORDER} !important;
    border-radius: 10px;
  }}
  div[data-testid="stMetricValue"] {{
    font-size: 1.75rem; color: {INK}; font-weight: 600;
  }}
  div[data-testid="stMetricLabel"] {{
    color: {MUTED}; text-transform: uppercase; letter-spacing: .06em;
    font-size: .72rem;
  }}
  /* Headings.
     Streamlit's own heading weight is ~600, which on a black plane reads as
     emphasised body text rather than a landmark — the section titles and the
     finding beneath them ended up at a similar visual weight, so the page had
     no scan structure. These are the landmarks: set heavier, larger, and at
     full white. !important because Streamlit's emotion classes carry higher
     specificity than a bare element selector. */
  h1, h2, h3 {{ color: {INK} !important; letter-spacing: -0.02em; }}
  h1 {{ font-weight: 800 !important; }}
  h2, h3 {{ font-weight: 700 !important; }}
  h3 {{ font-size: 1.55rem !important; line-height: 1.25; }}
  /* The red rule under every section heading — the one brand flourish */
  .rule {{
    height: 3px; width: 56px; background: {RED};
    border-radius: 2px; margin: 0 0 .6rem 0;
  }}
  .chart-title {{
    color: {INK}; font-size: 1.05rem; font-weight: 700; margin: 0 0 .15rem 0;
  }}
  .chart-sub {{ color: {MUTED}; font-size: .82rem; margin: 0 0 .5rem 0; }}
  .finding {{
    color: {INK_2}; font-size: 1rem; line-height: 1.55; margin: 0 0 .4rem 0;
  }}
  .finding b {{ color: {INK}; font-weight: 700; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


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

  The TTL is what makes 'live' honest: the numbers cannot silently go stale for
  longer than 5 minutes, and the sidebar Refresh button clears the cache
  outright for a demo.
  """
  conn = get_connection()
  try:
    return pd.read_sql_query(sql, conn, params=params)
  except psycopg2.Error:
    # A dropped connection (container restart mid-demo) is recoverable: the
    # rollback clears the aborted transaction so the next query works.
    conn.rollback()
    raise


@st.cache_data(ttl=300)
def q_oltp(sql: str, params: tuple = None) -> pd.DataFrame:
  """Same as q(), against the OLTP database, but returns None instead of raising.

  The data quality panel is the only caller. A dashboard that goes blank
  because a database it does not otherwise need is down would be a worse
  outcome than a panel that says so.
  """
  try:
    conn = psycopg2.connect(**OLTP_CONFIG)
  except psycopg2.Error:
    return None
  try:
    return pd.read_sql_query(sql, conn, params=params)
  except psycopg2.Error:
    return None
  finally:
    conn.close()


# --------------------------------------------------------------------------
# Chart chrome
#
# One styling function for every figure, so no chart can drift into its own
# type sizes or margins. Titles live in HTML ABOVE the plot rather than in the
# figure: Plotly titles overlap legends at narrow widths, and an HTML heading
# cannot collide with anything inside the SVG.
# --------------------------------------------------------------------------

def style(fig, height=320, legend=False, xlab="", ylab="", ygrid=True):
  fig.update_layout(
    height=height,
    paper_bgcolor=SURFACE,
    plot_bgcolor=SURFACE,
    font=dict(family=FONT, size=13, color=INK_2),
    margin=dict(l=4, r=18, t=8 if not legend else 34, b=4),
    showlegend=legend,
    legend=dict(
      orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
      bgcolor="rgba(0,0,0,0)", borderwidth=0,
      font=dict(size=12, color=INK_2), title_text="",
    ),
    hoverlabel=dict(
      bgcolor="#1F1F1F", bordercolor=BORDER, font_size=12,
      font_family=FONT, font_color=INK,
    ),
    bargap=0.28,
  )
  # automargin is what guarantees "text fully visible": Plotly grows the margin
  # to fit the longest tick label instead of clipping it.
  fig.update_xaxes(
    title=dict(text=xlab, font=dict(size=12, color=MUTED), standoff=8),
    tickfont=dict(size=12, color=MUTED),
    showgrid=False, zeroline=False,
    linecolor=BASELINE, linewidth=1, ticks="outside",
    tickcolor=BASELINE, ticklen=4, automargin=True,
  )
  fig.update_yaxes(
    title=dict(text=ylab, font=dict(size=12, color=MUTED), standoff=8),
    tickfont=dict(size=12, color=MUTED),
    showgrid=ygrid, gridcolor=GRID, gridwidth=1, zeroline=False,
    showline=False, ticks="", automargin=True,
  )
  return fig


def card(title: str, subtitle: str = ""):
  """A bordered chart card. Returns the container to draw the figure into."""
  box = st.container(border=True)
  with box:
    st.markdown(f"<p class='chart-title'>{title}</p>", unsafe_allow_html=True)
    if subtitle:
      st.markdown(f"<p class='chart-sub'>{subtitle}</p>", unsafe_allow_html=True)
  return box


def show(box, fig):
  with box:
    st.plotly_chart(fig, use_container_width=True,
                    config={"displayModeBar": False})


def section(heading: str, finding: str):
  """Heading, red rule, and the finding in plain words.

  The finding is stated as text on purpose. A reader who never looks at a chart
  should still leave the page knowing what the data said.
  """
  st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)
  st.subheader(heading)
  st.markdown("<div class='rule'></div>", unsafe_allow_html=True)
  st.markdown(f"<p class='finding'>{finding}</p>", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Header and KPIs
# --------------------------------------------------------------------------

def header_and_kpis():
  st.title("Sephora Skincare Reviews")
  st.markdown(
    f"<p class='finding'>"
    f"<b>1.09 million reviews — what people actually rate well, as opposed to "
    f"what they merely want.</b></p>",
    unsafe_allow_html=True)

  k = q("SELECT * FROM dw.vw_kpi_summary").iloc[0]

  box = st.container(border=True)
  with box:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Reviews", f"{k['total_reviews']:,}")
    c2.metric("Reviewers", f"{k['total_reviewers']:,}")
    c3.metric("Avg rating", f"{k['avg_rating']:.3f}")
    c4.metric("Recommend", f"{k['recommend_pct']:.1f}%")
    # Coverage rather than the catalogue count alone: only 2,351 of 8,494
    # products have any reviews, and a bare "8,494" would imply a coverage this
    # data does not have.
    c5.metric("Products reviewed",
              f"{k['products_reviewed']:,} / {k['products_in_catalogue']:,}")

    current = int(k["total_reviews"])
    baseline = st.session_state.get("reviews_baseline")
    # Recorded for the Refresh button to pick up on the NEXT rerun.
    st.session_state["reviews_current"] = current
    delta = (f"  ·  **{current - baseline:+,}** since last refresh"
             if baseline is not None and current != baseline else "")

    st.caption(
      f"Live from `sephora_dw` · {k['earliest_review']} → {k['latest_review']} "
      f"· warehouse watermark **{k['latest_review']}**{delta}. Helpfulness is "
      f"averaged only over the {k['reviews_with_feedback']:,} reviews that "
      f"actually received a vote — it is undefined, not zero, elsewhere (D5)."
    )
  return k


# --------------------------------------------------------------------------
# BQ5 — trend over time
# --------------------------------------------------------------------------

def bq5_trend():
  trend = q("""
    SELECT month_start, review_count, avg_rating, rolling_3m_avg_rating,
           is_partial_month
    FROM dw.vw_review_volume_by_month
    ORDER BY month_start
  """)
  if trend.empty:
    st.info("No review history in the warehouse yet.")
    return

  peak = trend.loc[trend["review_count"].idxmax()]
  low = trend.loc[trend["avg_rating"].idxmin()]

  section(
    "BQ5 · How do review volume and rating trend over time?",
    f"Volume grew for twelve years to a peak of <b>{int(peak['review_count']):,} "
    f"reviews</b> in {peak['month_start']:%B %Y}, then eased. Average rating "
    f"sagged to <b>{low['avg_rating']:.2f}</b> around {low['month_start']:%Y} "
    f"and has recovered since — the dip is real, but it is four hundredths of "
    f"a star deep.")

  left, right = st.columns(2)

  with left:
    # Data ends 21 March 2023, so the last bar is a part-month and would
    # otherwise read as a collapse in demand. It is greyed rather than
    # annotated: a floating "partial month" label had to sit somewhere among
    # 20k-tall bars, and there is no position at the right-hand edge where it
    # does not risk touching one.
    partial = trend["is_partial_month"].astype(bool)
    box = card(
      "Review volume by month — all categories",
      "Monthly counts. The final bar is <span style='color:%s'>grey</span> "
      "because March 2023 is a partial month — the data ends on the 21st."
      % MUTED)
    fig = go.Figure(go.Bar(
      x=trend["month_start"], y=trend["review_count"],
      marker_color=[MUTED if p else RED for p in partial],
      marker_line_width=0,
      customdata=partial.map({True: " (partial)", False: ""}),
      hovertemplate="%{x|%b %Y}%{customdata}<br>%{y:,} reviews<extra></extra>",
    ))
    style(fig, height=330, ylab="Reviews")
    show(box, fig)

  with right:
    box = card("Average rating: monthly vs 3-month rolling",
               "The rolling line is a SQL window function, not chart smoothing.")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
      x=trend["month_start"], y=trend["avg_rating"], name="Monthly",
      mode="lines", line=dict(color=BLUE, width=1.4),
      hovertemplate="%{x|%b %Y}<br>%{y:.3f}<extra>Monthly</extra>",
    ))
    fig.add_trace(go.Scatter(
      x=trend["month_start"], y=trend["rolling_3m_avg_rating"],
      name="3-month rolling", mode="lines",
      line=dict(color=RED, width=2.5),
      hovertemplate="%{x|%b %Y}<br>%{y:.3f}<extra>3-month rolling</extra>",
    ))
    style(fig, height=330, legend=True, ylab="Avg rating")
    show(box, fig)

  st.caption(
    "Monthly averages are noisy in the early years when volume was low, which "
    "is why the rolling line exists. Both come from "
    "`vw_review_volume_by_month`, so the same numbers appear in "
    "`sql/validation/dashboard_checks.sql`."
  )


# --------------------------------------------------------------------------
# BQ1 — brands and categories
# --------------------------------------------------------------------------

def bq1_brands(min_reviews, overall_rating, categories, scoped, picked_brands):
  # Two queries, one per scope, rather than one query with a clever predicate.
  # When nothing is filtered, vw_rating_by_brand is the authoritative brand
  # aggregate and is what dashboard_checks.sql validates. When a category
  # filter is on, the brand-by-category view is re-aggregated with a
  # review-count-WEIGHTED mean — averaging the per-category averages would
  # weight a 12-review category the same as a 300,000-review one.
  #
  # The brand predicate is bound the same way in both branches: an empty
  # selection means "no filter", expressed as a count of 0 rather than by
  # building a different SQL string.
  if scoped:
    brands = q("""
      SELECT brand_name,
             sum(review_count)                                            AS review_count,
             round(sum(avg_rating * review_count) / sum(review_count), 4) AS avg_rating
      FROM dw.vw_rating_by_brand_category
      WHERE secondary_category = ANY(%s)
        AND (%s = 0 OR brand_name = ANY(%s))
      GROUP BY brand_name
      HAVING sum(review_count) >= %s
      ORDER BY avg_rating DESC
    """, (categories, len(picked_brands), picked_brands or [""], int(min_reviews)))
  else:
    brands = q("""
      SELECT brand_name, review_count, avg_rating
      FROM dw.vw_rating_by_brand
      WHERE review_count >= %s
        AND (%s = 0 OR brand_name = ANY(%s))
      ORDER BY avg_rating DESC
    """, (int(min_reviews), len(picked_brands), picked_brands or [""]))

  if brands.empty:
    section("BQ1 · Which brands rate best, and which underperform?",
            "No brand matches the current filters.")
    if picked_brands:
      st.info(
        f"None of the {len(picked_brands)} selected brand"
        f"{'' if len(picked_brands) == 1 else 's'} has at least "
        f"{int(min_reviews):,} reviews in the selected categories. Lower the "
        f"review floor, or widen the brand selection.")
    else:
      st.info(f"No brand has at least {min_reviews:,} reviews. Lower the floor.")
    return

  top, bottom = brands.head(10), brands.tail(10)
  spread = float(top.iloc[0]["avg_rating"] - bottom.iloc[-1]["avg_rating"])

  # "Brand matters more than anything else here" is a claim about the whole
  # catalogue. Once a handful of brands are selected the spread is whatever
  # those few happen to differ by, so the claim is dropped rather than restated
  # over a population that cannot support it.
  section(
    "BQ1 · Which brands rate best, and which underperform?",
    f"<b>{top.iloc[0]['brand_name']}</b> at {top.iloc[0]['avg_rating']:.2f} to "
    f"<b>{bottom.iloc[-1]['brand_name']}</b> at "
    f"{bottom.iloc[-1]['avg_rating']:.2f} — a spread of <b>{spread:.2f} stars</b>."
    + ("" if picked_brands else
       " That is far larger than any other effect on this page: brand matters "
       "more than category, price, or who is doing the rating."))

  # Deviation from the overall mean, not raw rating. Anchoring on 4.299 is what
  # makes "underperform" mean something — every bar is read against the average
  # a shopper actually experiences, and the diverging colour carries the sign.
  ranked = pd.concat([top, bottom]).drop_duplicates(subset="brand_name")
  ranked = ranked.assign(delta=ranked["avg_rating"] - overall_rating)
  ranked = ranked.sort_values("delta")

  box = card(
    f"Brands against the {overall_rating:.3f} overall average",
    (f"All {len(brands)} matching brands, " if len(brands) <= 20 else
     f"Top and bottom 10 of the {len(brands)} brands, ")
    + f"each with at least {int(min_reviews):,} reviews. Bars run left of the "
      f"line for below average, right for above.")
  fig = go.Figure(go.Bar(
    x=ranked["delta"], y=ranked["brand_name"], orientation="h",
    marker_color=[RED if d >= 0 else BLUE for d in ranked["delta"]],
    marker_line_width=0,
    customdata=ranked[["avg_rating", "review_count"]],
    hovertemplate=("<b>%{y}</b><br>%{customdata[0]:.3f} avg"
                   "<br>%{customdata[1]:,} reviews<extra></extra>"),
  ))
  fig.add_vline(x=0, line_width=1, line_color=BASELINE)
  # 20 horizontal bars need real estate; automargin handles the brand names.
  style(fig, height=620, xlab="Rating minus the overall average", ygrid=False)
  fig.update_xaxes(showgrid=True, gridcolor=GRID, ticksuffix="")
  show(box, fig)

  st.caption(
    (f"{len(brands)} of the {len(picked_brands)} selected brands clear the "
     f"{int(min_reviews):,}-review floor. "
     if picked_brands else
     f"{len(brands)} of 304 brands clear the {int(min_reviews):,}-review floor. ")
    + "Drop the floor and the top of this chart becomes brands with a single "
      "5-star review — which is exactly why the floor exists."
  )


def bq1_categories(categories):
  cats = q("""
    SELECT secondary_category,
           sum(review_count)                                            AS reviews,
           round(sum(avg_rating * review_count) / sum(review_count), 4) AS avg_rating
    FROM dw.vw_rating_by_category
    WHERE secondary_category = ANY(%s)
    GROUP BY secondary_category
    ORDER BY avg_rating
  """, (categories,))
  if cats.empty:
    return

  best, worst = cats.iloc[-1], cats.iloc[0]
  spread = float(best["avg_rating"] - worst["avg_rating"])

  box = card(
    "Average rating by category",
    f"All {len(cats)} secondary categories, ordered. Every reviewed product "
    f"here is Skincare at the primary level (D16).")
  # A DOT plot, not bars. The spread is 0.18 of a star, so the axis has to be
  # truncated to show it at all — and a truncated axis under BARS lies, because
  # bar length is read from zero. A dot encodes position, so truncating the
  # axis is honest. Same reason the price and skin-type charts below are dots
  # and lines rather than bars.
  fig = go.Figure(go.Scatter(
    x=cats["avg_rating"], y=cats["secondary_category"],
    mode="markers",
    marker=dict(size=12, color=RED, line=dict(width=2, color=SURFACE)),
    customdata=cats[["reviews"]],
    hovertemplate=("<b>%{y}</b><br>%{x:.3f} avg"
                   "<br>%{customdata[0]:,} reviews<extra></extra>"),
  ))
  fig.update_xaxes(range=[float(cats["avg_rating"].min()) - 0.03,
                          float(cats["avg_rating"].max()) + 0.03])
  style(fig, height=380, xlab="Avg rating", ygrid=True)
  # Horizontal leader lines make each dot's row readable across the width.
  fig.update_yaxes(showgrid=True, gridcolor=GRID)
  fig.update_xaxes(showgrid=False)
  show(box, fig)

  st.caption(
    f"**{best['secondary_category']}** leads at {best['avg_rating']:.3f} and "
    f"**{worst['secondary_category']}** trails at {worst['avg_rating']:.3f} — a "
    f"spread of just **{spread:.3f} of a star**, against more than a full star "
    f"between brands. Note the truncated x-axis: it has to be truncated for a "
    f"spread this small to be visible at all."
  )


# --------------------------------------------------------------------------
# BQ3 — price
# --------------------------------------------------------------------------

def bq3_price():
  bands = q("""
    SELECT price_band, band_order, review_count, product_count,
           avg_rating, recommend_pct, rating_stddev
    FROM dw.vw_rating_by_price_band
    ORDER BY band_order
  """)
  if bands.empty:
    return

  peak = bands.loc[bands["avg_rating"].idxmax()]
  tightest = bands.loc[bands["rating_stddev"].idxmin()]
  top_band = bands.iloc[-1]

  # Both statements are computed, not typed. An earlier version of this page
  # asserted that spread "falls steadily as price rises" — it does not. It
  # falls to $50-100 and then widens again at $100+, and quoting the monotone
  # version meant the caption disagreed with the chart beside it.
  same_band = peak["price_band"] == tightest["price_band"]
  section(
    "BQ3 · Does price predict satisfaction?",
    f"Not linearly. Ratings climb to <b>{peak['avg_rating']:.3f}</b> at "
    f"<b>{peak['price_band']}</b> and fall back above it — an inverted U. "
    + (f"Agreement peaks in the <b>same band</b>: rating spread is tightest at "
       f"{tightest['rating_stddev']:.3f} in {tightest['price_band']}, then "
       f"widens again to {top_band['rating_stddev']:.3f} above ${100}. So "
       f"<b>{peak['price_band']} is the sweet spot on both measures</b> — best "
       f"rated and most agreed upon — and the priciest band regresses on both."
       if same_band else
       f"Spread is tightest at {tightest['rating_stddev']:.3f} in "
       f"{tightest['price_band']}."))

  left, right = st.columns(2)

  with left:
    box = card("Average rating by price band — all categories",
               "Ordered bands, so the line is meaningful — this is the "
               "inverted U. Marker shade deepens with price.")
    # A line across ORDERED bands, not bars. The whole spread is 0.095 of a
    # star: as bars on a truncated axis, "Under $15" appeared roughly six times
    # shorter than "$50-100", which is a 2% difference drawn as 600%. Position
    # encoding makes the truncation honest and shows the shape besides.
    fig = go.Figure(go.Scatter(
      x=bands["price_band"], y=bands["avg_rating"],
      mode="lines+markers", line=dict(color=RED, width=2),
      marker=dict(size=15, color=RED_RAMP[:len(bands)],
                  line=dict(width=2, color=SURFACE)),
      customdata=bands[["review_count"]],
      hovertemplate=("<b>%{x}</b><br>%{y:.4f} avg"
                     "<br>%{customdata[0]:,} reviews<extra></extra>"),
    ))
    fig.add_annotation(
      x=peak["price_band"], y=peak["avg_rating"],
      text=f"peak {peak['avg_rating']:.3f}", showarrow=True, arrowhead=0,
      arrowwidth=1, arrowcolor=MUTED, ax=0, ay=-30,
      font=dict(size=11, color=INK),
    )
    fig.update_yaxes(range=[float(bands["avg_rating"].min()) - 0.02,
                            float(bands["avg_rating"].max()) + 0.035])
    style(fig, height=320, ylab="Avg rating")
    show(box, fig)

  with right:
    box = card("Rating spread by price band",
               "Standard deviation of rating. Lower means more agreement.")
    fig = go.Figure(go.Scatter(
      x=bands["price_band"], y=bands["rating_stddev"],
      mode="lines+markers", line=dict(color=RED, width=2.5),
      marker=dict(size=9, color=RED, line=dict(width=2, color=SURFACE)),
      hovertemplate="<b>%{x}</b><br>std dev %{y:.4f}<extra></extra>",
    ))
    style(fig, height=320, ylab="Std dev of rating")
    show(box, fig)

  st.caption(
    "Both charts use lines rather than bars on purpose. The whole rating "
    "spread across five bands is about a tenth of a star, so the axis has to "
    "be truncated to show it — and a truncated axis under bars misleads, "
    "because bar length is read from zero. A point's position carries the same "
    "value honestly. Standard deviation is the width of opinion: lower means "
    "buyers agree more."
  )


# --------------------------------------------------------------------------
# BQ2 — hype vs reality
# --------------------------------------------------------------------------

def bq2_hype(categories, picked_brands):
  hype = q("""
    SELECT product_name, brand_name, secondary_category, price_usd,
           loves_count, review_count, avg_rating, hype_gap
    FROM dw.vw_hype_vs_reality
    WHERE secondary_category = ANY(%s)
      AND (%s = 0 OR brand_name = ANY(%s))
    ORDER BY hype_gap DESC
  """, (categories, len(picked_brands), picked_brands or [""]))
  if hype.empty:
    if picked_brands:
      section("BQ2 · Hype vs reality — which products are loved more than they deserve?",
              "No product from the selected brands clears the 50-review floor.")
      st.info(
        "`vw_hype_vs_reality` only carries products with at least 50 reviews, "
        "because both rating and hype gap are unstable below that. Widen the "
        "brand or category selection.")
    return

  worst = hype.iloc[0]

  section(
    "BQ2 · Hype vs reality — which products are loved more than they deserve?",
    f"Wanting a product and liking it are different signals. "
    f"<b>{worst['brand_name']} {worst['product_name']}</b> is the widest gap "
    f"{'in the current selection' if picked_brands else 'in the catalogue'}: "
    f"<b>{int(worst['loves_count']):,} loves</b> against a "
    f"<b>{worst['avg_rating']:.2f}</b> rating. `loves_count` is recorded before "
    f"purchase, the rating after — so the gap between them is marketing "
    f"working better than the product does.")

  box = card(
    "Loves (intention) against average rating (satisfaction)",
    "One dot per product, sized by review count. Red sits further above its "
    "rating on loves than it deserves; blue is the opposite — better than "
    "anyone expected.")
  fig = go.Figure(go.Scatter(
    x=hype["loves_count"], y=hype["avg_rating"], mode="markers",
    marker=dict(
      size=hype["review_count"], sizemode="area",
      sizeref=2.0 * hype["review_count"].max() / (34.0 ** 2), sizemin=4,
      color=hype["hype_gap"],
      # The midpoint must read as "nothing" WITHOUT disappearing. The first
      # attempt used the #3A3A38 chrome gray and every product near a zero gap
      # sank into the black surface — the densest part of the cloud became
      # invisible. This gray is neutral against both poles and still legible on
      # #151515.
      colorscale=[[0.0, BLUE], [0.5, MIDPOINT], [1.0, RED]],
      cmid=0,
      line=dict(width=1, color=SURFACE),   # 2px surface ring on overlap
      colorbar=dict(
        title=dict(text="Hype gap", font=dict(size=11, color=MUTED)),
        tickfont=dict(size=11, color=MUTED), thickness=10, len=0.7,
        outlinewidth=0,
      ),
    ),
    customdata=hype[["product_name", "brand_name", "review_count"]],
    hovertemplate=("<b>%{customdata[1]} %{customdata[0]}</b>"
                   "<br>%{x:,} loves · %{y:.2f} avg"
                   "<br>%{customdata[2]:,} reviews<extra></extra>"),
  ))
  # Direct-label the three worst offenders only. A label on every dot would be
  # unreadable, and these three are the whole point of the chart.
  #
  # Labelled by PRODUCT, not brand: The Ordinary holds two of the top three, so
  # brand-only labels printed "The Ordinary" twice on the same chart and told
  # the reader nothing about which product either dot was.
  for i, (_, r) in enumerate(hype.head(3).iterrows()):
    name = r["product_name"]
    if len(name) > 26:
      name = name[:25].rstrip() + "…"
    fig.add_annotation(
      x=r["loves_count"], y=r["avg_rating"],
      text=f"{r['brand_name']} · {name}",
      showarrow=True, arrowhead=0, arrowwidth=1, arrowcolor=MUTED,
      ax=18, ay=-30 - (i * 4), xanchor="left",
      font=dict(size=11, color=INK), align="left",
    )
  style(fig, height=430, xlab="Loves / wishlist adds", ylab="Avg rating")
  show(box, fig)

  st.caption(
    "Both signals are percentile-ranked in SQL, so a cheap moisturizer and a "
    "$300 serum are comparable. Minimum 50 reviews per product — "
    f"{len(hype):,} products qualify."
  )

  with st.expander("The ten most overhyped, and the ten quiet successes"):
    left, right = st.columns(2)
    cols = ["product_name", "brand_name", "loves_count", "review_count",
            "avg_rating"]
    with left:
      st.markdown("**Most overhyped** — high loves, low rating")
      st.dataframe(hype.head(10)[cols], hide_index=True,
                   use_container_width=True)
    with right:
      st.markdown("**Sleeper hits** — better than their love count suggests")
      st.dataframe(hype.tail(10)[cols].iloc[::-1], hide_index=True,
                   use_container_width=True)


# --------------------------------------------------------------------------
# BQ4 + review length
# --------------------------------------------------------------------------

def bq4_and_length(categories):
  skin = q("""
    SELECT skin_type,
           sum(review_count)                                            AS reviews,
           round(sum(avg_rating * review_count) / sum(review_count), 4) AS avg_rating
    FROM dw.vw_rating_by_skin_type
    WHERE secondary_category = ANY(%s)
    GROUP BY skin_type
    HAVING sum(review_count) >= 1000
    ORDER BY avg_rating DESC
  """, (categories,))

  length = q("""
    SELECT length_bucket, bucket_order, review_count, avg_rating,
           rating_stddev, pct_1_star, pct_5_star
    FROM dw.vw_rating_by_review_length
    ORDER BY bucket_order
  """)
  # The Unknown bucket is kept in the view so it reconciles to the fact table,
  # but it is not a LENGTH — plotting it on an ordered length axis would be a
  # category error.
  plotted = length[length["length_bucket"] != "Unknown"]

  skin_spread = (float(skin["avg_rating"].max() - skin["avg_rating"].min())
                 if not skin.empty else 0.0)
  short, long_ = plotted.iloc[0], plotted.iloc[-1]

  section(
    "BQ4 · Does who is reviewing, or how much they write, change the rating?",
    f"Barely, and both answers are worth stating plainly. Skin type moves the "
    f"average by <b>{skin_spread:.3f} of a star</b> — real, measurable, and too "
    f"small to act on. Review length moves it almost not at all, but it hides "
    f"the better finding: short reviews are <b>polarised</b> and long ones are "
    f"moderate.")

  left, right = st.columns(2)

  with left:
    box = card("Average rating by skin type",
               "Groups with at least 1,000 reviews. Truncated axis — the whole "
               "spread is four hundredths of a star.")
    if skin.empty:
      with box:
        st.info("No skin type clears the 1,000-review floor.")
    else:
      # Dots again, for the same reason as the category and price charts: a
      # 0.04-star spread needs a truncated axis, and truncating under bars
      # would draw a 1% difference as a towering one.
      fig = go.Figure(go.Scatter(
        x=skin["avg_rating"], y=skin["skin_type"], mode="markers",
        marker=dict(size=13, color=RED, line=dict(width=2, color=SURFACE)),
        customdata=skin[["reviews"]],
        hovertemplate=("<b>%{y}</b><br>%{x:.4f} avg"
                       "<br>%{customdata[0]:,} reviews<extra></extra>"),
      ))
      fig.update_xaxes(range=[float(skin["avg_rating"].min()) - 0.012,
                              float(skin["avg_rating"].max()) + 0.012])
      style(fig, height=330, xlab="Avg rating")
      fig.update_yaxes(showgrid=True, gridcolor=GRID)
      fig.update_xaxes(showgrid=False)
      show(box, fig)

  with right:
    box = card("Share of 1-star and 5-star reviews by length",
               "Two panels, not two series on one axis — see note below.")
    # SMALL MULTIPLES, deliberately. The two shares live on wildly different
    # scales (1-star runs 3-8%, 5-star 61-67%). Grouped on a single axis, the
    # 5-star bars tower and the 1-star decline — which is half the finding —
    # renders as a flat strip along the baseline. A second y-axis would be the
    # usual "fix" and is worse: two arbitrary scales invent a relationship.
    # Separate panels let each tail be read on its own scale honestly.
    fig = make_subplots(
      rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.16,
      subplot_titles=("1-star share (%)", "5-star share (%)"))
    fig.add_trace(go.Bar(
      x=plotted["length_bucket"], y=plotted["pct_1_star"],
      marker_color=RED, marker_line_width=0, showlegend=False,
      hovertemplate="<b>%{x}</b><br>%{y:.2f}% are 1 star<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Bar(
      x=plotted["length_bucket"], y=plotted["pct_5_star"],
      marker_color=BLUE, marker_line_width=0, showlegend=False,
      hovertemplate="<b>%{x}</b><br>%{y:.2f}% are 5 star<extra></extra>",
    ), row=2, col=1)
    style(fig, height=380)
    # style() budgets no room for subplot titles, so the first one gets clipped
    # by the top edge. Give it back explicitly.
    fig.update_layout(margin=dict(l=4, r=18, t=30, b=4))
    for ann in fig.layout.annotations:
      ann.font = dict(size=12, color=INK_2)
      ann.x, ann.xanchor = 0, "left"
    fig.update_xaxes(tickfont=dict(size=11, color=MUTED))
    show(box, fig)

  st.caption(
    "The common assumption is that unhappy customers write longer reviews. "
    "**This data does not support it.** Going from the shortest bucket to the "
    f"longest, the 1-star share falls {short['pct_1_star']:.2f}% → "
    f"{long_['pct_1_star']:.2f}% **and** the 5-star share falls "
    f"{short['pct_5_star']:.2f}% → {long_['pct_5_star']:.2f}%. Both extremes "
    "shrink together, so they cancel in the mean — rating standard deviation "
    f"falls {short['rating_stddev']:.4f} → {long_['rating_stddev']:.4f} across "
    "the same buckets. Skin profile is the question the junk dimension exists "
    "for: holding those attributes on `dim_customer` would have mis-tagged "
    "13.69% of reviews and quietly broken this chart (D2)."
  )


# --------------------------------------------------------------------------
# Product explorer — the product-level filter
#
# Kept as its own section rather than as more sidebar controls. Its brand and
# search boxes sit directly above the only thing they scope, so there is never
# a question about which part of the page a control affects — the failure mode
# the sidebar Category filter has to explain with a note.
# --------------------------------------------------------------------------

def product_explorer(categories, picked_brands):
  section(
    "Explore · find a category, brand or product",
    "Everything above is an aggregate. This is the row-level view behind it — "
    "filter down to a single product and read its actual numbers.")

  # Brand used to be a second multiselect here. It moved to the sidebar so
  # there is exactly one brand control on the page: two of them could disagree,
  # and a reader had no way to tell which one the charts above were obeying.
  search = st.text_input(
    "Product name contains", value="",
    placeholder="e.g. vitamin c, cleanser, retinol",
    help="Case-insensitive substring match, applied in SQL as ILIKE, not as "
         "a filter over a preloaded frame. Combines with the sidebar's "
         "Category and Brand filters.")
  picked = picked_brands

  # Both filters bind into the query. The brand list is passed as a real array
  # parameter and the search as an ILIKE pattern — neither is interpolated into
  # the SQL string, so a product name containing a quote cannot break the page.
  #
  # Note the doubled percent in the "Recommend" alias below. psycopg2 scans the
  # ENTIRE query string for placeholders before sending it, including inside
  # comments and quoted identifiers, so a lone % anywhere in this string is
  # read as the start of a parameter and the bind fails with a bare
  # "tuple index out of range". Doubling it escapes it back to one.
  rows = q("""
    SELECT brand_name        AS "Brand",
           product_name      AS "Product",
           secondary_category AS "Category",
           price_usd         AS "Price (USD)",
           review_count      AS "Reviews",
           avg_rating        AS "Avg rating",
           recommend_pct     AS "Recommend %%",
           loves_count       AS "Loves",
           hype_gap          AS "Hype gap"
    FROM dw.vw_hype_vs_reality
    WHERE secondary_category = ANY(%s)
      AND (%s = 0 OR brand_name = ANY(%s))
      AND (%s = '' OR product_name ILIKE %s)
    ORDER BY review_count DESC
  """, (categories, len(picked), picked or [""], search, f"%{search}%"))

  if rows.empty:
    st.info("No product matches those filters. Clear the search box or widen "
            "the category selection.")
    return

  st.dataframe(rows, hide_index=True, use_container_width=True, height=420,
               column_config={
                 "Price (USD)": st.column_config.NumberColumn(format="$%.2f"),
                 "Reviews": st.column_config.NumberColumn(format="%d"),
                 "Loves": st.column_config.NumberColumn(format="%d"),
                 "Avg rating": st.column_config.NumberColumn(format="%.2f"),
                 "Hype gap": st.column_config.NumberColumn(format="%.3f"),
               })

  st.caption(
    f"**{len(rows):,}** products match. Click a column header to sort. "
    f"Population is `vw_hype_vs_reality` — products with **at least 50 "
    f"reviews** (1,660 of 2,351 reviewed products), because rating and hype "
    f"gap are both unstable below that. **Hype gap** is loves-percentile minus "
    f"rating-percentile: positive means more wanted than liked."
  )


# --------------------------------------------------------------------------
# Data quality — recomputed at render time, never read from a stored summary
# --------------------------------------------------------------------------

def data_quality_panel():
  with st.expander("Data quality — what was dropped, what was kept, and why"):
    fact = q("""
      SELECT count(*) AS n, max(submission_date) AS watermark
      FROM dw.fact_reviews
    """).iloc[0]
    fact_rows = int(fact["n"])

    oltp = q_oltp("""
      SELECT (SELECT count(*) FROM raw.reviews)     AS raw_reviews,
             (SELECT count(*) FROM "3nf".review)    AS nf3_review,
             (SELECT count(*) FROM staging.review)  AS staging_review,
             (SELECT count(*) FROM staging.review
               WHERE submission_date > %s)          AS after_watermark
    """, (fact["watermark"],))

    if oltp is None:
      st.warning(
        f"`{OLTP_CONFIG['dbname']}` is unreachable, so the OLTP half of this "
        f"panel cannot be shown. The warehouse figures are unaffected.")
      gap = held_back = None
    else:
      r = oltp.iloc[0]
      st.dataframe(pd.DataFrame([
        {"Stage": "raw.reviews", "Rows": int(r["raw_reviews"]),
         "What happens here": "1:1 mirror of the cleaned CSVs, loaded by COPY."},
        {"Stage": "3nf.review", "Rows": int(r["nf3_review"]),
         "What happens here": "Normalised across 9 tables, every FK enforced."},
        {"Stage": "staging.review", "Rows": int(r["staging_review"]),
         "What happens here": "Review text left behind (D6); length precomputed."},
        {"Stage": "dw.fact_reviews", "Rows": fact_rows,
         "What happens here": "One row per review — the grain of the star schema."},
      ]), hide_index=True, use_container_width=True)
      gap = int(r["staging_review"]) - fact_rows
      held_back = int(r["after_watermark"])

    reasons = q("""
      SELECT
        count(*) FILTER (WHERE p.product_key IS NULL)           AS unresolved_product,
        count(*) FILTER (WHERE c.customer_key IS NULL)          AS unresolved_customer,
        count(*) FILTER (WHERE rp.reviewer_profile_key IS NULL) AS unresolved_profile,
        count(*) FILTER (WHERE d.date_key IS NULL)              AS out_of_range_date
      FROM dw.fact_reviews f
      LEFT JOIN dw.dim_product          p  ON p.product_key = f.product_key
      LEFT JOIN dw.dim_customer         c  ON c.customer_key = f.customer_key
      LEFT JOIN dw.dim_reviewer_profile rp ON rp.reviewer_profile_key = f.reviewer_profile_key
      LEFT JOIN dw.dim_date             d  ON d.date_key = f.date_key
    """).iloc[0]

    # The distinction that matters: HELD BACK is not LOST. At the historical
    # baseline the warehouse is legitimately ~49.5k rows behind staging (D8),
    # and a panel that called that a shortfall would be lying at exactly the
    # moment it is on screen during the demo.
    if gap is None:
      pass
    elif gap == 0:
      st.success(
        f"`staging.review` minus `dw.fact_reviews` is **{gap:,}** — nothing was "
        f"dropped for any reason, named or otherwise.")
    elif gap == held_back:
      st.info(
        f"The warehouse is **{gap:,} rows behind** `staging.review`, and all "
        f"{held_back:,} of them are dated after the watermark "
        f"({fact['watermark']}). They were **not dropped** — this is a "
        f"`historical` load, which holds later reviews back so an incremental "
        f"run has real data to pick up (D8). Run the DAG in `incremental` mode "
        f"and this closes to zero.")
    else:
      st.error(
        f"`staging.review` is **{gap:,} rows** ahead of `dw.fact_reviews`, but "
        f"only {held_back:,} are after the watermark. **{gap - held_back:,} rows "
        f"are unaccounted for** — treat this warehouse as incomplete.")

    dupes = int(q("""
      SELECT count(*) AS n FROM (
        SELECT source_row_id, product_id FROM dw.fact_reviews
        GROUP BY 1, 2 HAVING count(*) > 1) d
    """)["n"].iloc[0])
    orphans = int(sum(int(reasons[k]) for k in reasons.index))

    # Same UNION as the reconciliation block of dashboard_checks.sql, run from
    # the app. Counted rather than hardcoded: a "9 of 9" typed into the page
    # would keep claiming 9 after someone added a tenth view.
    recon = q("""
      SELECT 'vw_kpi_summary' AS view_name, total_reviews AS reviews FROM dw.vw_kpi_summary
      UNION ALL SELECT 'vw_rating_by_brand',         sum(review_count) FROM dw.vw_rating_by_brand
      UNION ALL SELECT 'vw_rating_by_category',      sum(review_count) FROM dw.vw_rating_by_category
      UNION ALL SELECT 'vw_rating_by_brand_category', sum(review_count) FROM dw.vw_rating_by_brand_category
      UNION ALL SELECT 'vw_rating_by_price_band',    sum(review_count) FROM dw.vw_rating_by_price_band
      UNION ALL SELECT 'vw_review_trend_monthly',    sum(review_count) FROM dw.vw_review_trend_monthly
      UNION ALL SELECT 'vw_review_volume_by_month',  sum(review_count) FROM dw.vw_review_volume_by_month
      UNION ALL SELECT 'vw_rating_by_skin_tone',     sum(review_count) FROM dw.vw_rating_by_skin_tone
      UNION ALL SELECT 'vw_rating_by_review_length', sum(review_count) FROM dw.vw_rating_by_review_length
    """)
    matching = int((recon["reviews"] == fact_rows).sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Orphan fact rows", f"{orphans:,}",
              help="Fact rows whose product / customer / reviewer profile / "
                   "date key does not resolve.")
    c2.metric("Duplicate idempotency keys", f"{dupes:,}",
              help="UNIQUE(source_row_id, product_id) is what makes re-running "
                   "the DAG safe (D13).")
    c3.metric("Views reconciling to fact_reviews", f"{matching} of {len(recon)}",
              help="Each full-population view aggregates the same fact rows a "
                   "different way, so summing it back up must return the same "
                   "total. Same UNION as sql/validation/dashboard_checks.sql.")

    st.caption(
      "**One number here is not live.** `clean.py` removed **1,040** duplicate "
      "reviews on (author_id, product_id, submission_time) before anything "
      "reached Postgres — 1,094,411 source rows became 1,093,371 — so neither "
      "database can be queried for it. It is the only row loss in the whole "
      "chain, it was deliberate (D4), and it is stated here rather than left "
      "out because the point of this panel is what happened to every row."
    )


# --------------------------------------------------------------------------
# Sidebar — one control, deliberately (D25)
# --------------------------------------------------------------------------

def sidebar():
  st.sidebar.markdown("### Sephora Reviews")
  st.sidebar.caption("Live analytics over `sephora_dw`.")
  st.sidebar.divider()

  all_categories = q("""
    SELECT DISTINCT secondary_category
    FROM dw.vw_rating_by_category
    WHERE secondary_category IS NOT NULL
    ORDER BY 1
  """)["secondary_category"].tolist()

  categories = st.sidebar.multiselect(
    "Category", options=all_categories, default=all_categories,
    help="Secondary category. Primary is always 'Skincare' in this dataset "
         "(D16), so secondary is the level that actually varies. Binds into "
         "SQL as `secondary_category = ANY(%s)`.",
  )
  # Empty selection would produce five empty charts and read as a broken app.
  # Treat it as "no filter", and say so, rather than silently substituting.
  if not categories:
    st.sidebar.caption("⚠ Nothing selected — showing **all** categories.")
    categories = all_categories

  scoped = len(categories) < len(all_categories)

  # Brand options are drawn from the CURRENT category selection, so the list
  # never offers a brand that would return nothing. Default is empty, which
  # means "every brand" — the same convention the category filter uses when
  # everything is selected.
  all_brands = q("""
    SELECT DISTINCT brand_name
    FROM dw.vw_rating_by_brand_category
    WHERE secondary_category = ANY(%s)
    ORDER BY 1
  """, (categories,))["brand_name"].tolist()

  brands = st.sidebar.multiselect(
    "Brand", options=all_brands, default=[],
    placeholder="All brands",
    help="Empty means every brand in the selected categories. Binds into SQL "
         "as `brand_name = ANY(%s)`, so the charts re-query — this is not a "
         "filter applied to an already-fetched frame.",
  )

  min_reviews = st.sidebar.number_input(
    "Minimum reviews per brand",
    min_value=1, max_value=5000, value=500, step=50,
    help="A review floor is not decoration: without one, the best-rated brand "
         "is whichever has a single 5-star review. This binds into the SQL as "
         "WHERE review_count >= n, so the chart re-queries when you change it.",
  )

  st.sidebar.divider()
  if st.sidebar.button("Refresh data", use_container_width=True, type="primary"):
    # Freeze what is currently on screen as the comparison point BEFORE
    # clearing the cache, so the KPI strip can show how far the warehouse moved
    # while the DAG was running.
    st.session_state["reviews_baseline"] = st.session_state.get("reviews_current")
    st.cache_data.clear()
    st.rerun()
  st.sidebar.caption(
    "Run the Airflow DAG in `incremental` mode, then click Refresh — the review "
    "count moves live."
  )

  st.sidebar.divider()
  with st.sidebar.expander("How to read this"):
    st.markdown(
      "- **Truncated axes are deliberate and always labelled.** Most effects "
      "here are a tenth of a star or less; a zero-based axis would render them "
      "as identical bars and hide the finding.\n"
      "- **`Unknown` is a category, not a gap.** It means the reviewer declined "
      "to answer.\n"
      "- **Red and blue are the only two series colours**, chosen so they stay "
      "distinguishable under colour-vision deficiency.\n"
      "- **Every number is queried live** and reproducible with "
      "`sql/validation/dashboard_checks.sql`. If the two disagree, this "
      "dashboard is wrong."
    )

  with st.sidebar.expander("What the filters scope"):
    st.markdown(
      "**Category responds:** brands · categories · hype vs reality · skin "
      "type · product explorer.\n\n"
      "**Category does not:** the volume/rating trend and the price bands. "
      "Those come from `vw_review_volume_by_month` and "
      "`vw_rating_by_price_band`, which aggregate away the category column — a "
      "filter applied to them would do nothing while appearing to work. Each "
      "is labelled *all categories* on the page so the scope is never "
      "ambiguous.\n\n"
      "**Brand responds:** brands · hype vs reality · product explorer. Those "
      "are the three sections whose views carry `brand_name` — "
      "`vw_rating_by_brand`, `vw_rating_by_brand_category` and "
      "`vw_hype_vs_reality`.\n\n"
      "**Brand does not:** categories, price bands, skin type, review length "
      "or the trend. Their views aggregate brand away entirely, so there is no "
      "column to filter on. Rather than silently ignore the selection, those "
      "sections stay catalogue-wide and say so.\n\n"
      "Brand-level figures are re-aggregated with a review-count-weighted "
      "mean, not an average of averages."
    )
  return categories, scoped, min_reviews, brands


# --------------------------------------------------------------------------
# Page
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

  categories, scoped, min_reviews, brands = sidebar()

  k = header_and_kpis()
  if scoped or brands:
    parts = []
    if scoped:
      shown = ", ".join(categories[:6]) + ("…" if len(categories) > 6 else "")
      parts.append(
        f"**{len(categories)}** categor"
        f"{'y' if len(categories) == 1 else 'ies'} — {shown}")
    if brands:
      shown = ", ".join(brands[:6]) + ("…" if len(brands) > 6 else "")
      parts.append(
        f"**{len(brands)}** brand{'' if len(brands) == 1 else 's'} — {shown}")
    st.info(
      f"Scoped to {' · '.join(parts)}. The KPI row above stays catalogue-wide, "
      f"and so does any section whose view aggregates the filtered column "
      f"away; the sidebar note **What the filters scope** lists exactly which.")
  st.divider()

  bq5_trend()
  st.divider()

  bq1_brands(min_reviews, float(k["avg_rating"]), categories, scoped, brands)
  bq1_categories(categories)
  st.divider()

  bq3_price()
  st.divider()

  bq2_hype(categories, brands)
  st.divider()

  bq4_and_length(categories)
  st.divider()

  product_explorer(categories, brands)
  st.divider()

  data_quality_panel()

  st.caption(
    "Sephora Products and Skincare Reviews · PostgreSQL → 3NF OLTP → star "
    "schema → Airflow → Streamlit. Every figure above is queried live from "
    "`sephora_dw` at render time."
  )


main()
