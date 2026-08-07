"""
test_dashboard_smoke.py
-----------------------
Runs dashboard/app.py through Streamlit's own AppTest harness.

Why this exists: `curl` against a running Streamlit server returns HTTP 200
even when the script raises, because the error is rendered client-side. A
dashboard that 200s and shows a red traceback is not a working dashboard. This
executes the script the way Streamlit does and fails on any uncaught exception.

Marked integration: it needs the warehouse, because the app queries it on
import of the first page.
"""

import os

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("streamlit", reason="streamlit not installed")

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = os.path.join(
  os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
  "dashboard", "app.py")

# Generous: the first run warms every cache and issues ~9 queries, one of which
# scans 1.09M fact rows.
TIMEOUT = 180


def _run(page=None):
  at = AppTest.from_file(APP, default_timeout=TIMEOUT)
  at.run()

  if at.exception:
    pytest.fail(f"app raised on first render: {[e.value for e in at.exception]}")

  # The app st.stop()s with an st.error if the warehouse is unreachable.
  if at.error:
    pytest.skip(f"warehouse unreachable: {[e.value for e in at.error]}")

  if page is not None:
    at.sidebar.radio[0].set_value(page).run()
    if at.exception:
      pytest.fail(f"'{page}' raised: {[e.value for e in at.exception]}")

  return at


def test_overview_page_renders():
  at = _run("Overview")

  # The KPI row is the one thing every viewer reads first.
  assert len(at.metric) >= 5, "KPI metrics missing"
  labels = [m.label for m in at.metric]
  assert "Reviews" in labels
  assert "Avg rating" in labels


def test_overview_kpi_matches_the_warehouse():
  """The dashboard must not display a number the warehouse disagrees with."""
  at = _run("Overview")

  reviews = next(m for m in at.metric if m.label == "Reviews")
  rating = next(m for m in at.metric if m.label == "Avg rating")

  import psycopg2
  from dotenv import load_dotenv

  root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
  load_dotenv(os.path.join(root, ".env"))
  conn = psycopg2.connect(
    host=os.getenv("DW_DB_HOST"), port=os.getenv("DW_DB_PORT"),
    dbname=os.getenv("DW_DB_NAME"), user=os.getenv("DW_DB_USER"),
    password=os.getenv("DW_DB_PASSWORD"))
  try:
    with conn.cursor() as cur:
      cur.execute("SELECT count(*), round(avg(rating), 3) FROM dw.fact_reviews")
      fact_rows, fact_rating = cur.fetchone()
  finally:
    conn.close()

  assert reviews.value == f"{fact_rows:,}", (
    f"dashboard shows {reviews.value} reviews, warehouse has {fact_rows:,}")
  assert rating.value == f"{fact_rating:.3f}"


def test_deep_dive_page_renders():
  at = _run("Deep dive")

  assert at.dataframe, "hype vs reality tables missing"
  headers = " ".join(h.value for h in at.subheader)
  assert "BQ3" in headers
  assert "BQ4" in headers


def test_min_reviews_filter_is_live():
  """Changing the floor must re-query, not just re-draw a cached picture."""
  at = _run("Overview")

  captions_before = " ".join(c.value for c in at.caption)
  assert "of 304 brands clear" in captions_before

  at.sidebar.number_input[0].set_value(50).run()
  assert not at.exception

  captions_after = " ".join(c.value for c in at.caption)
  assert captions_after != captions_before, (
    "lowering the review floor changed nothing — the filter is not wired to "
    "the query")
