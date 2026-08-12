# 08 — Testing Evidence

**51 tests, 51 passing**, plus 11 DAG structural assertions verified inside the
Airflow container. Last full run: **2026-08-12**.

```
tests/unit/test_quality.py                   15 tests   no database needed
tests/unit/test_transform.py                 17 tests   no database needed
tests/integration/test_pipeline_reconciliation.py  9 tests   needs Postgres
tests/integration/test_dashboard_smoke.py    10 tests   needs Postgres + streamlit
tests/test_dag_structure.py                  12 tests   needs airflow (skips locally)
tests/verify_dag_in_container.py             11 asserts runs inside the container
```

---

## Running them

```powershell
py -m pip install -r requirements.txt -r requirements-dev.txt

py -m pytest -q                     # everything    -> 51 passed, 1 skipped
py -m pytest -m "not integration"   # unit only, no database needed
py -m pytest tests/unit/test_quality.py -q -k rating    # one concern

# DAG structure, where Airflow actually lives
docker cp tests/verify_dag_in_container.py leapfrog_airflow_scheduler:/tmp/
docker exec leapfrog_airflow_scheduler python /tmp/verify_dag_in_container.py
```

The `integration` marker exists so the unit suite runs on a machine with no
database. Integration tests **skip themselves** with a stated reason if Postgres
is unreachable, rather than failing — but `addopts = -ra` means a skip is always
printed, so a skipped test is visibly skipped rather than quietly absent from
the count.

---

## What each test proves

### `tests/unit/test_quality.py` — fault injection (15)

The point is **not** that clean data passes; every pipeline run proves that.
The point is that dirty data **fails**. A gate never observed to fail is
indistinguishable from a gate that cannot fail.

Each test starts from one valid frame and breaks exactly one thing, so a
failure names the defect instead of leaving you to guess which of six
differences mattered.

| Test | Proves |
|---|---|
| `test_valid_frame_passes` | The baseline — without this, every failure below proves nothing |
| `test_null_foreign_key_halts` ×4 | A null `product_key` / `customer_key` / `reviewer_profile_key` / `date_key` halts before load, naming the column instead of surfacing a bare Postgres `NOT NULL` violation mid-insert |
| `test_rating_below_one_halts` | Rating 0 rejected |
| `test_rating_above_five_halts` | Rating 6 rejected |
| `test_negative_feedback_count_halts` | A negative count means the transform corrupted something |
| `test_duplicate_source_key_halts` | Duplicate `(source_row_id, product_id)`. Survivable — `ON CONFLICT` would absorb it — but then loaded and extracted counts disagree silently, which is the gap reconciliation exists to close |
| `test_unresolved_product_reference_is_detected` | A `product_key` absent from `dim_product` is flagged before the FK rejects it |
| `test_high_null_rate_warns_but_does_not_halt` | **A warning does not stop the pipeline.** `is_recommended` is legitimately ~15% null |
| `test_null_rate_within_threshold_does_not_warn` | No false alarms on normal data |
| `test_hard_failure_wins_over_warning` | When both fire, the run still dies. Guards a regression where collecting warnings swallows the raise |
| `test_empty_frame_skips_gate_without_failing` | An incremental run with nothing new is a clean no-op. Without this, every quiet Tuesday pages somebody |
| `test_null_rate_on_empty_frame_is_zero` | No divide-by-zero on an empty batch |

### `tests/unit/test_transform.py` — keys and reconciliation (17)

| Test | Proves |
|---|---|
| `test_resolves_surrogate_keys_to_correct_members` | P1→10 and P2→20 specifically, not merely "some key". A merge that mis-joins produces a warehouse that is internally consistent and completely wrong |
| `test_surrogate_keys_are_integers_not_floats` | Any NaN in a merge upgrades the column to `float64`; a float in an `INTEGER` column is a type error, not a formatting one |
| `test_all_drop_reasons_present_even_when_zero` | "Nothing was dropped" is distinguishable from "this was never checked" |
| `test_unresolved_product_is_counted` | Categorized, not silent |
| `test_unresolved_customer_is_counted` | " |
| `test_unresolved_reviewer_profile_is_counted` | " |
| `test_out_of_range_date_is_counted` | Should be structurally impossible (`dim_date` is padded ±30 days) — which is why it is counted rather than assumed |
| `test_dim_product_counts_unresolved_brand` | Same discipline on the dimension path |
| `test_empty_input_returns_typed_empty_frame` | Empty batch is a no-op, not a crash |
| `test_price_bands_use_shared_boundaries` | Left-closed: $30.00 is `$30-50`, not `$15-30`. Computed once so every visual agrees |
| `test_reconcile_transform_balances` | The identity holds on honest input |
| **`test_reconcile_transform_raises_on_unexplained_loss`** | **5 rows vanish with no reason attached → the run dies.** The single most important test in the suite |
| `test_reconcile_transform_raises_when_counts_exceed_input` | Can't transform more rows than arrived |
| `test_extracted_vs_transformed_mismatch_is_caught` | End-to-end: a real drop reconciles, lying about the extracted count does not |
| `test_reconcile_load_reports_already_present` | `offered − inserted` |
| `test_reconcile_load_idempotent_rerun` | 1,000 offered, 0 inserted — the idempotency signature |
| `test_reconcile_load_raises_if_table_grew_more_than_offered` | Detects concurrent writes or a miscounted load |

### `tests/integration/test_pipeline_reconciliation.py` — against the live database (9)

| Test | Proves |
|---|---|
| **`test_fact_row_count_matches_staging`** | **`fact_reviews` = `staging.review` exactly.** The headline reconciliation — 1,093,371 = 1,093,371 |
| `test_no_orphan_dimension_keys` | Every fact FK resolves; 0 orphans |
| `test_idempotency_key_is_unique` | 0 duplicate `(source_row_id, product_id)` |
| `test_historical_and_incremental_partition_full` | The two modes partition the data with no overlap and no gap. If these don't add up, one mode is lying |
| **`test_full_mode_has_no_date_bound`** | **`full` really means full.** Guards the exact bug this remediation fixed — the old `--full-reload` stopped at 2023 |
| `test_historical_mode_stops_at_the_cutoff` | `max(submission_date) < 2023-01-01` |
| `test_unknown_mode_raises` | A typo'd mode fails loudly, not silently as "incremental" |
| `test_empty_incremental_batch_is_clean_noop` | Watermark current → 0 extracted → transform, reconcile and load all handle zero without raising |
| `test_watermark_matches_max_fact_date` | The watermark cannot disagree with the data it describes, because it is read from it |

### `tests/integration/test_dashboard_smoke.py` — the app actually runs (10)

Runs `dashboard/app.py` through Streamlit's `AppTest` harness.

> An HTTP check would not catch a broken dashboard: **Streamlit returns 200 and
> renders the traceback client-side.** A page that 200s and shows a red error
> is not a working page.

| Test | Proves |
|---|---|
| `test_overview_page_renders` | Page 1 executes with no exception; KPI metrics present |
| **`test_overview_kpi_matches_the_warehouse`** | **The displayed review count and average rating equal `SELECT count(*), round(avg(rating),3) FROM dw.fact_reviews`.** The dashboard cannot show a number the warehouse disagrees with |
| `test_deep_dive_page_renders` | Page 2 executes; BQ3 and BQ4 sections present |
| `test_min_reviews_filter_is_live` | Changing the floor changes the output — the filter re-queries rather than redrawing a cached picture |
| `test_hype_gap_slider_is_live` | Changing the hype-gap threshold changes the SQL-backed product set |
| `test_price_range_slider_is_live` | Price bounds are bound into the warehouse query rather than filtering a preloaded frame |
| `test_skin_group_floor_is_live` | The minimum skin-group sample size changes both BQ4 result sets |
| `test_review_length_section_renders` | The review-length evidence and both supporting visuals render without an exception |
| `test_review_length_view_reconciles_to_the_fact_table` | Every fact row lands in exactly one review-length bucket |
| `test_data_quality_panel_reports_the_row_accounting` | The live panel re-derives source, warehouse, and integrity counts rather than reading a stored status claim |

### DAG structure (12 pytest / 11 in-container)

| Assertion | Proves |
|---|---|
| `dag_imports_without_errors` | No syntax or import breakage |
| `expected_tasks_present` | Exactly 16 tasks, named as designed |
| `retry_policy` | 2 retries, 5-minute delay |
| `load_mode_param_offers_three_modes` | Enum `[full, historical, incremental]`, defaulting to the cheap one |
| `cleanup_runs_even_after_failure` | `trigger_rule = all_done` |
| `watcher_uses_one_failed` | `trigger_rule = one_failed` |
| `watcher_does_not_retry` | `retries = 0` |
| **`watcher_is_the_only_leaf`** | **The critical one.** Airflow derives run state from leaves; any leaf besides the watcher can mask a failure |
| **`watcher_watches_every_other_task`** | `one_failed` evaluates *direct* upstreams only, so a task missing from the watcher's upstream set is a failure it cannot see. Easy to break by adding a task and forgetting to wire it — and the failure mode is invisible |
| `cleanup_precedes_watcher` | A failed run still cleans up before being marked failed |
| `fact_is_split_into_four_stages` | extract → transform → quality → load, separately retryable |
| `product_waits_for_brand` | `dim_product` resolves `brand_key`, so brand must load first |

---

## Verified pipeline behaviour (not from the test suite)

Measured from actual runs and recorded here as evidence rather than assertion:

| Scenario | Result |
|---|---|
| Historical load | 1,043,868 fact rows; fact stage 62s |
| Re-run of a completed load | 1,043,868 offered, **0 inserted** |
| Incremental, watermark 2022-12-31 | 49,503 extracted, **49,503 inserted** |
| Re-run incremental, watermark 2023-03-21 | **0 extracted**, gate skipped, 0 inserted |
| Final warehouse | **1,093,371** = `staging.review` exactly |
| Airflow historical run | All tasks green (after the D15 chunking fix) |
| Airflow incremental run | All tasks green in **22 seconds** |
| Staging tables between runs | All 6 at **0 rows** |
| All 8 full-population views | Reconcile to 1,093,371 exactly |

---

## Known gaps

Stated rather than left for someone to notice:

- **No test forces a real DAG task to fail** to observe the watcher going red
  end-to-end. The wiring is asserted structurally; the runtime behaviour is
  Airflow's documented `one_failed` semantics.
- **No `EXPLAIN ANALYZE` capture.** Indexes were created deliberately with
  stated reasons, but no before/after performance comparison was recorded.
- **No coverage measurement.** Test count is not coverage.
- **`test_dag_structure.py` skips locally**, which is why
  `verify_dag_in_container.py` exists — a test that only ever skips proves
  nothing.
