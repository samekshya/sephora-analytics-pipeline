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


def _dw_connection():
  """A direct warehouse connection, for assertions the app must agree with."""
  import psycopg2
  from dotenv import load_dotenv

  root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
  load_dotenv(os.path.join(root, ".env"))
  return psycopg2.connect(
    host=os.getenv("DW_DB_HOST"), port=os.getenv("DW_DB_PORT"),
    dbname=os.getenv("DW_DB_NAME"), user=os.getenv("DW_DB_USER"),
    password=os.getenv("DW_DB_PASSWORD"))


def _run():
  """Render the single page. There is no page selector any more (D25)."""
  at = AppTest.from_file(APP, default_timeout=TIMEOUT)
  at.run()

  if at.exception:
    pytest.fail(f"app raised on first render: {[e.value for e in at.exception]}")

  # The app st.stop()s with an st.error if the warehouse is unreachable.
  # st.error is also used by the data quality panel for a genuine shortfall, so
  # match on the connection message rather than on "any error present".
  unreachable = [e.value for e in at.error if "Cannot reach the warehouse" in e.value]
  if unreachable:
    pytest.skip(f"warehouse unreachable: {unreachable}")

  return at


def test_the_page_is_a_single_page():
  """D25: one page, so there must be no page selector left behind."""
  at = _run()
  assert not at.sidebar.radio, (
    "a radio remains in the sidebar — the dashboard is meant to be one page")


def test_page_renders_with_kpis():
  at = _run()

  # The KPI row is the one thing every viewer reads first.
  assert len(at.metric) >= 5, "KPI metrics missing"
  labels = [m.label for m in at.metric]
  assert "Reviews" in labels
  assert "Avg rating" in labels


def test_kpis_match_the_warehouse():
  """The dashboard must not display a number the warehouse disagrees with."""
  at = _run()

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


def test_all_five_business_questions_are_on_the_one_page():
  """Every BQ must be reachable without navigating (D25)."""
  at = _run()

  headers = " ".join(h.value for h in at.subheader)
  for bq in ("BQ1", "BQ2", "BQ3", "BQ4", "BQ5"):
    assert bq in headers, f"{bq} is missing from the page"


def test_min_reviews_filter_is_live():
  """Changing the floor must re-query, not just re-draw a cached picture."""
  at = _run()

  captions_before = " ".join(c.value for c in at.caption)
  assert "of 304 brands clear" in captions_before

  at.sidebar.number_input[0].set_value(50).run()
  assert not at.exception

  captions_after = " ".join(c.value for c in at.caption)
  assert captions_after != captions_before, (
    "lowering the review floor changed nothing — the filter is not wired to "
    "the query")


def _caption_containing(at, needle):
  """Find a caption by content, not index.

  Captions are returned in render order, so indexing would silently repoint at
  a different one the moment a section is added above it — and the test would
  keep passing.
  """
  return next(c.value for c in at.caption if needle in c.value)


def test_category_filter_scopes_the_brand_chart():
  """The category filter must reach the brand query, not just the category one.

  `vw_rating_by_brand` has no category column, so a naive implementation
  filters the category chart and silently leaves the brand chart catalogue-wide
  — which looks like it works. The brand chart is served by
  `vw_rating_by_brand_category` precisely so this holds.
  """
  at = _run()
  before = _caption_containing(at, "brands clear the")

  at.sidebar.multiselect[0].set_value(["Cleansers"]).run()
  assert not at.exception

  after = _caption_containing(at, "brands clear the")
  assert after != before, (
    "narrowing to one category left the brand chart unchanged — the filter is "
    "not reaching vw_rating_by_brand_category")


def test_brand_filter_scopes_the_brand_chart_and_the_explorer():
  """The brand filter must reach the queries, like every other control (D23).

  Brands are read from the warehouse rather than hardcoded: a literal brand
  name would make this test fail for a data reason rather than a code reason
  the first time the catalogue changed.
  """
  conn = _dw_connection()
  try:
    with conn.cursor() as cur:
      cur.execute("""
        SELECT brand_name FROM dw.vw_rating_by_brand
        WHERE review_count >= 500 ORDER BY review_count DESC LIMIT 2
      """)
      picked = [r[0] for r in cur.fetchall()]
  finally:
    conn.close()

  assert len(picked) == 2, "warehouse has fewer than 2 brands over the floor"

  at = _run()
  brands_before = _caption_containing(at, "brands clear the")
  products_before = _caption_containing(at, "products match")

  # multiselect[1] is Brand; [0] is Category.
  at.sidebar.multiselect[1].set_value(picked).run()
  assert not at.exception

  assert _caption_containing(at, "brands clear the") != brands_before, (
    "selecting brands left the brand chart unchanged — the filter is not "
    "reaching vw_rating_by_brand")
  assert _caption_containing(at, "products match") != products_before, (
    "selecting brands left the product explorer unchanged")

  # The explorer's own brand control was removed when the filter moved to the
  # sidebar; two brand controls could disagree with no way to tell which one
  # the charts above were obeying.
  assert len(at.sidebar.multiselect) == 2, "sidebar should hold Category and Brand"
  assert len(at.multiselect) == 2, (
    "a second brand control has come back into the page body")


def test_product_search_is_live():
  """The product search must be an ILIKE in SQL, not a frame filter."""
  at = _run()
  before = _caption_containing(at, "products match")

  at.text_input[0].set_value("cleanser").run()
  assert not at.exception

  after = _caption_containing(at, "products match")
  assert after != before, "the product search is not reaching the query"


def test_review_length_finding_is_stated():
  at = _run()

  captions = " ".join(c.value for c in at.caption)
  assert "This data does not support it" in captions, (
    "the review-length caption must keep stating that the obvious hypothesis "
    "fails on this data")


def test_review_length_view_reconciles_to_the_fact_table():
  """The new view is a full-population view: it must lose nothing.

  Rows with no recorded length are bucketed as Unknown rather than dropped
  precisely so this holds. Excluding them would be the easy thing to do and
  would put the view permanently 1,444 rows short of every other one.
  """
  conn = _dw_connection()
  try:
    with conn.cursor() as cur:
      cur.execute("""
        SELECT (SELECT sum(review_count) FROM dw.vw_rating_by_review_length),
               (SELECT count(*) FROM dw.fact_reviews)
      """)
      view_total, fact_total = cur.fetchone()

      # Bucket boundaries must partition the range - no row in two buckets,
      # none in none.
      cur.execute("""
        SELECT count(DISTINCT bucket_order), count(DISTINCT length_bucket)
        FROM dw.vw_rating_by_review_length
      """)
      orders, labels = cur.fetchone()
  finally:
    conn.close()

  assert view_total == fact_total, (
    f"vw_rating_by_review_length sums to {view_total}, fact_reviews has "
    f"{fact_total}")
  assert orders == labels, "bucket_order and length_bucket are not 1:1"


def test_data_quality_panel_reports_the_row_accounting():
  at = _run()

  labels = {m.label: m.value for m in at.metric}
  assert labels.get("Orphan fact rows") == "0"
  assert labels.get("Duplicate idempotency keys") == "0"

  # "N of N" - every full-population view still reconciles. Computed by the
  # app, so this catches a view added without being registered.
  reconciling = labels.get("Views reconciling to fact_reviews", "")
  matched, _, total = reconciling.partition(" of ")
  assert matched and matched == total, (
    f"only {reconciling} views reconcile to fact_reviews")
