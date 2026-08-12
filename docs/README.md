# Documentation index

Read in order for the full story, or jump to what you need.

| # | Document | Answers |
|---|---|---|
| 01 | [Problem statement](01_problem_statement.md) | What is being built, for which questions, and what is explicitly out of scope |
| 02 | [Data quality findings](02_data_quality_findings.md) | What was wrong with the raw data, measured before anything was built on it |
| 03 | [Architecture](03_architecture.md) | How data flows from CSV to dashboard, and why the shape is what it is |
| 04 | [Schema documentation](04_schema_documentation.md) | Every table in both databases: grain, keys, columns, constraints |
| 05 | [ETL and incremental loading](05_etl_and_incremental_loading.md) | The three load modes, the watermark, reconciliation, the quality gate |
| 06 | [Airflow runbook](06_airflow_runbook.md) | How to start it, trigger each mode, and read a failed run |
| 07 | [Dashboard insights](07_dashboard_insights.md) | Every finding, with the number behind it |
| 08 | [Testing evidence](08_testing_evidence.md) | What each of the 49 tests proves, and the known gaps |
| 09 | [Decision log](09_decision_log.md) | 23 decisions, with the reasoning and what was ruled out |
| 10 | [Production readiness checklist](10_production_readiness_checklist.md) | Self-audit, including the five deliberately unchecked items |
| 11 | [Project walkthrough](11_project_walkthrough.md) | Narrative account of the whole build, start to finish |

## Elsewhere in the repo

| Document | Covers |
|---|---|
| [`../README.md`](../README.md) | Setup and quickstart |
| [`../dashboard/README.md`](../dashboard/README.md) | What each visual shows and how to read it |
| [`../dashboard/data_model.md`](../dashboard/data_model.md) | Which tables and views the dashboard reads |
| [`../data/README.md`](../data/README.md) | Where to get the source CSVs and where to put them |
| [`../presentation/README.md`](../presentation/README.md) | Eight-minute deck, PDF, timing guide, and rebuild command |
| [`screenshots/`](screenshots/) | Presentation captures — filenames the other docs link to |
| [`archive/`](archive/) | Superseded documents, kept rather than deleted |

## For the 8-minute presentation

| Requirement | Where the material is |
|---|---|
| 1. Introduction to the data source | [01](01_problem_statement.md), [02](02_data_quality_findings.md) §1 |
| 2. Data flow architecture | [03](03_architecture.md) |
| 3. Design decisions | [09](09_decision_log.md) — lead with **D2** (junk dimension), it is the strongest |
| 4. Airflow DAG, incremental and full | [06](06_airflow_runbook.md) — run the demo sequence live |
| 5. Data visualization: KPIs, trends, insights | [07](07_dashboard_insights.md) — lead with **BQ3**, the inverted U |
