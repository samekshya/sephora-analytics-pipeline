# Pipeline guide (PDF)

A 12-page walkthrough of the whole project, stage by stage: the raw CSVs and
every column, what cleaning changed, the three OLTP schemas, the ETL modules
and load modes, the star schema, the quality gate, the Airflow DAG, and the
dashboard.

| File | What it is |
|---|---|
| [`Sephora_Pipeline_Guide.pdf`](Sephora_Pipeline_Guide.pdf) | The document. Print or hand over as-is |
| [`pipeline_guide.html`](pipeline_guide.html) | The source. Edit this, never the PDF |

## Rebuilding it

Chrome renders the HTML to PDF — no LaTeX, no Word, no Python dependency:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    --headless --disable-gpu --no-pdf-header-footer `
    --print-to-pdf="docs\guide\Sephora_Pipeline_Guide.pdf" `
    "file:///$($PWD -replace '\','/')/docs/guide/pipeline_guide.html"
```

Page size, margins and the print palette are set in the `@page` and `:root`
blocks at the top of the HTML.

## Keeping it honest

Every figure in the guide was measured from the running system, not copied
from an older document. If the warehouse is reloaded and the numbers move,
the ones to re-check are:

```powershell
docker exec -i leapfrog_sephora_postgres psql -U postgres -d sephora_dw `
    -f - < sql\validation\dashboard_checks.sql
```

The guide states 1,093,371 fact rows, 0 orphan keys, 0 duplicate idempotency
keys, and all full-population views reconciling exactly.
