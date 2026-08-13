"""
build_charts.py
---------------
Renders the deck's trend figure straight from the warehouse.

Why generated rather than screenshotted: the two price charts on the results
slide are cropped dashboard captures, which works because they are small and
static. The trend needs the full 2008-2023 span, and a screenshot of it either
comes out too wide for a slide or too small to read the 2020 dip. Rendering it
here gives a vector figure at the deck's own proportions, from the same view
the dashboard reads (`dw.vw_review_volume_by_month`), so the numbers cannot
drift apart.

Two panels sharing one time axis rather than one dual-axis chart. Volume and
rating have nothing to do with each other dimensionally, and a second y-axis
invites the reader to see a relationship in where the two lines cross - which
is an artefact of axis scaling, not the data.

    py .\\presentation\\build_charts.py

Writes presentation/assets/chart_trend.svg.
"""

import os
import sys

import pandas as pd
import plotly.graph_objects as go
import psycopg2
from dotenv import load_dotenv
from plotly.subplots import make_subplots

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(REPO_ROOT, ".env"))

OUT = os.path.join(REPO_ROOT, "presentation", "assets", "chart_trend.svg")

# The dashboard's palette, so the deck figure and the live page are visibly the
# same product. Values are copied from dashboard/app.py rather than re-derived.
SURFACE = "#151515"
INK = "#FFFFFF"
MUTED = "#8E8B85"
GRID = "#262626"
RED = "#F5405F"
BLUE = "#5589C7"
FAINT_BAR = "#4A2733"     # the partial final month, muted so it is not read as a fall

FONT = "Archivo, system-ui, -apple-system, Segoe UI, sans-serif"

QUERY = """
    SELECT month_start, review_count, avg_rating, rolling_3m_avg_rating,
           is_partial_month
    FROM dw.vw_review_volume_by_month
    ORDER BY month_start
"""


def fetch():
  conn = psycopg2.connect(
    host=os.getenv("DW_DB_HOST"), port=os.getenv("DW_DB_PORT"),
    dbname=os.getenv("DW_DB_NAME"), user=os.getenv("DW_DB_USER"),
    password=os.getenv("DW_DB_PASSWORD"))
  try:
    return pd.read_sql_query(QUERY, conn)
  finally:
    conn.close()


def build(df):
  fig = make_subplots(
    rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.09,
    row_heights=[0.55, 0.45])

  # Panel 1 - volume. The final month is March 2023, cut off on the 21st; left
  # the same colour it would read as a collapse in demand rather than a partial
  # month, which is the single most misreadable point on the chart.
  colours = [FAINT_BAR if p else RED for p in df["is_partial_month"]]
  fig.add_trace(go.Bar(
    x=df["month_start"], y=df["review_count"],
    marker_color=colours, marker_line_width=0,
    hovertemplate="%{x|%b %Y}<br>%{y:,} reviews<extra></extra>"),
    row=1, col=1)

  # Panel 2 - rating. Monthly is noisy in the early years when volume was in the
  # hundreds, so the rolling line carries the trend and the raw series sits
  # behind it as evidence rather than being hidden.
  fig.add_trace(go.Scatter(
    x=df["month_start"], y=df["avg_rating"], mode="lines",
    line=dict(color=BLUE, width=1), opacity=0.55, name="Monthly",
    hoverinfo="skip"), row=2, col=1)
  fig.add_trace(go.Scatter(
    x=df["month_start"], y=df["rolling_3m_avg_rating"], mode="lines",
    line=dict(color=RED, width=2.4), name="3-month rolling",
    hovertemplate="%{x|%b %Y}<br>%{y:.3f} avg<extra></extra>"), row=2, col=1)

  fig.update_layout(
    template="plotly_dark",
    paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
    font=dict(family=FONT, size=15, color=MUTED),
    showlegend=False,
    bargap=0.12,
    margin=dict(l=68, r=24, t=46, b=40),
    width=1180, height=680,
    annotations=[
      dict(text="Reviews per month", x=0, y=1.055, xref="paper", yref="paper",
           showarrow=False, font=dict(size=16, color=INK), xanchor="left"),
      dict(text="Average rating — monthly, and 3-month rolling",
           x=0, y=0.415, xref="paper", yref="paper",
           showarrow=False, font=dict(size=16, color=INK), xanchor="left"),
    ])

  fig.update_xaxes(showgrid=False, linecolor=GRID, ticks="outside",
                   tickcolor=GRID, tickfont=dict(size=14))
  fig.update_yaxes(gridcolor=GRID, zeroline=False, tickfont=dict(size=14))
  fig.update_yaxes(tickformat=",d", row=1, col=1)
  fig.update_yaxes(tickformat=".2f", row=2, col=1)
  return fig


def main():
  df = fetch()
  if df.empty:
    sys.exit("vw_review_volume_by_month returned no rows - is the warehouse loaded?")

  fig = build(df)
  fig.write_image(OUT)

  span = f"{df['month_start'].min():%b %Y} to {df['month_start'].max():%b %Y}"
  peak = df.loc[df["review_count"].idxmax()]
  print(f"wrote {os.path.relpath(OUT, REPO_ROOT)}")
  print(f"  {len(df)} months, {span}")
  print(f"  peak {int(peak['review_count']):,} reviews in {peak['month_start']:%b %Y}")
  print(f"  rating range {df['rolling_3m_avg_rating'].min():.4f} "
        f"to {df['rolling_3m_avg_rating'].max():.4f}")


if __name__ == "__main__":
  main()
