# Screenshots

Drop the presentation screenshots here with these exact filenames — the other
documents link to them by name.

| Filename | What to capture | State |
|---|---|---|
| `airflow_dag_graph.png` | Graph view of the DAG itself — all 15 tasks, `cleanup_staging` last | **Current** — used by deck slide 7 |
| `chart_price_rating.png` | Dashboard: average rating by price band, cropped to the plot area | **Current** — used by deck slide 9 |
| `chart_price_spread.png` | Dashboard: rating spread by price band, cropped to the plot area | **Current** — used by deck slide 9 |
| `chart_price_pair.png` | Both price charts together, uncropped | Current, unused by the deck |
| `airflow_historical_run.png` | Graph view of a `load_mode = historical` run, all 15 tasks green | **Stale** — see below |
| `airflow_incremental_run.png` | Graph view of a `load_mode = incremental` run. Worth including the duration — incremental finishes in ~22 seconds against ~2 minutes for historical | **Stale** — see below |
| `streamlit_overview.png` | Dashboard page 1: the KPI row plus the volume-over-time chart | **Stale** — see below |
| `streamlit_analysis.png` | Dashboard page 2: the price-band chart and the hype-vs-reality scatter | **Stale** — see below |

The four stale captures are used only by `build_deck.ps1`, the superseded PowerPoint build.
The nine-slide HTML deck does not read them — it uses the three current captures above plus
the generated diagrams in [`../diagrams/`](../diagrams/).

> ## ⚠ The two Airflow captures are STALE
>
> They were taken on 2026-08-12 from the **16-task** DAG and show
> `watch_for_failure`, which no longer exists — the failure watcher was replaced
> by a teardown (**D24**). The graph in those images does not match the code.
>
> **Re-capture both before presenting.** The runs already exist — nothing needs
> re-running, just open each URL and capture with `Win + Shift + S`:
>
> | Save as | Open | Result |
> |---|---|---|
> | `airflow_historical_run.png` | [`…/runs/teardown_historical_20260812`](http://localhost:8081/dags/sephora_dw_pipeline_staged/runs/teardown_historical_20260812) | success, **134s** |
> | `airflow_incremental_run.png` | [`…/runs/teardown_incremental_20260812`](http://localhost:8081/dags/sephora_dw_pipeline_staged/runs/teardown_incremental_20260812) | success, **22s** |
> | `airflow_failed_run.png` | [`…/runs/failure_proof_v2_20260812`](http://localhost:8081/dags/sephora_dw_pipeline_staged/runs/failure_proof_v2_20260812) | **FAILED** — 3 `upstream_failed`, cleanup green |
>
> Start Airflow first if it is down:
> `docker compose -f docker-compose-airflow.yml up -d`
>
> **The two Streamlit captures are stale as well.** The dashboard was rebuilt as
> a single Sephora-themed page (D25) — the old images show two pages, five
> sidebar controls, and bar charts that were replaced because a truncated axis
> under bars misleads. Recapture by scrolling the one page:
>
> | Save as | Capture |
> |---|---|
> | `streamlit_overview.png` | Top of the page — KPI card, BQ5 volume bars and the rating trend |
> | `streamlit_analysis.png` | Further down — the price line pair and the hype scatter |
>
> ```powershell
> py -m streamlit run dashboard/app.py     # http://localhost:8501
> ```
>
> The filenames are unchanged so `build_deck.ps1` needs no edit; only what they
> show changes. The underlying data is the same (1,093,371 rows, watermark
> 2023-03-21).

**A third Airflow capture is now available and worth taking**: run
`failure_proof_v2_20260812` is a genuinely **FAILED** run showing three tasks
`upstream_failed`, `cleanup_staging` **green**, and the run marked FAILED. Save it
as `airflow_failed_run.png`. It demonstrates the D20/D24 guarantee rather than
describing it — a green cleanup sitting beside a red run is the exact case that
used to report success.

## Two worth capturing beyond the required four

- **`airflow_failed_run.png`** — see the note above; the run already exists.
  To force a fresh one, note that the Airflow connections come from **environment
  variables** in `docker-compose-airflow.yml`, so `airflow connections add` will
  not override them. Either stop Postgres mid-run, or pause the DAG, trigger it,
  set one task's state to `failed` in the metadata database, and unpause.
  Retries are 2 × 5 minutes, so a genuinely failing task takes ~11 minutes to
  settle.
- **`validation_output.png`** — terminal output of
  `sql/validation/dashboard_checks.sql` showing every view at
  `diff_from_fact = 0`. Proof the dashboard numbers reconcile.

## Capturing them

```powershell
# Airflow
docker compose -f docker-compose-airflow.yml up -d
# http://localhost:8081 -> sephora_dw_pipeline_staged -> Graph

# Dashboard
py -m streamlit run dashboard/app.py
# http://localhost:8501
```

Use `Win + Shift + S` to capture a region.

> Kept out of git otherwise — `.gitignore` excludes nothing here, so the PNGs
> **will** be committed. That is intentional: they are the presentation
> evidence, and they are small.
