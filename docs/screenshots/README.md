# Screenshots

Drop the presentation screenshots here with these exact filenames — the other
documents link to them by name.

| Filename | What to capture |
|---|---|
| `airflow_historical_run.png` | Graph view of a `load_mode = historical` run, all tasks green, `watch_for_failure` **skipped** (pale, not red) |
| `airflow_incremental_run.png` | Graph view of a `load_mode = incremental` run. Worth including the duration — the incremental run finishes in ~22 seconds against ~4 minutes for historical |
| `streamlit_overview.png` | Dashboard page 1: the KPI row plus the volume-over-time chart |
| `streamlit_analysis.png` | Dashboard page 2: the price-band chart and the hype-vs-reality scatter |

All four required captures were refreshed on **2026-08-12** from the live
project environment:

- `airflow_historical_run.png` — run `verification_historical_20260812`,
  success, **164 seconds**, 15 successful tasks + skipped watcher.
- `airflow_incremental_run.png` — run `verification_incremental_20260812`,
  success, **27 seconds**, 15 successful tasks + skipped watcher.
- `streamlit_overview.png` — live 1,093,371-row warehouse, KPI strip and both
  monthly trend charts fully rendered.
- `streamlit_analysis.png` — live Deep dive with hype scatter, ranked product
  tables, and price analysis visible.

## Two worth capturing beyond the required four

- **`airflow_watcher_failed.png`** — a run where a task failed, showing
  `watch_for_failure` **red** and the DAG marked FAILED. This is the single
  most persuasive screenshot in the set: it demonstrates the bug that was fixed
  rather than describing it. Force one by pointing `SRC_CONN_ID` at a
  nonexistent database, or stopping Postgres mid-run.
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
