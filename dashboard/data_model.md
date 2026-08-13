# What the dashboard reads

The app touches **only** the `dw` schema of `sephora_dw`, and only through
curated views wherever one exists. It never reads `sephora_oltp`, never touches
`raw` or `3nf`, and issues no `INSERT`/`UPDATE`/`DELETE` of any kind.

## Views consumed

The dashboard is one page (D25), so the ordering below is the order a reader
meets each view scrolling down.

| View | Feeds | Grain |
|---|---|---|
| `vw_kpi_summary` | The 5-metric KPI row and the live watermark | 1 row |
| `vw_review_volume_by_month` | BQ5 volume bars, monthly + rolling rating lines | 1 row per month (176) |
| `vw_rating_by_brand` | BQ1 brands-against-the-average diverging bars, unfiltered | 1 row per brand (304) |
| `vw_rating_by_brand_category` | The same chart when a Category filter is on | 1 row per (brand, secondary category) |
| `vw_rating_by_category` | BQ1b category dot plot | 1 row per category triple (174) |
| `vw_rating_by_price_band` | BQ3 rating line and spread line | 1 row per band (5) |
| `vw_hype_vs_reality` | BQ2 hype scatter and both ranked tables | 1 row per product with ≥50 reviews (1,660) |
| `vw_rating_by_skin_type` | BQ4 skin-type dot plot | skin_type × category |
| `vw_rating_by_review_length` | BQ4 review-length small multiples | 1 row per length bucket (6) |
| `vw_hype_vs_reality` | Also backs the **Explore** product table (brand picker + name search) | 1 row per product with ≥50 reviews (1,660) |

`vw_rating_by_skin_tone` is no longer read by a chart. It is still validated by
`sql/validation/dashboard_checks.sql` and still reconciles to `fact_reviews`;
the skin-tone breakdown was cut from the page because it told the same weak
story as skin type and doubled the chart count to do it (D25).

## Base tables read directly

Since D25 removed the category and date filters, the only direct table reads
left are in the **data quality panel**, which exists precisely to re-derive row
accounting rather than trust a view:

| Table | Why |
|---|---|
| `fact_reviews` + the four dimensions | Orphan-key counts, duplicate idempotency keys, and the watermark |
| `raw.reviews`, `3nf.review`, `staging.review` | The row-accounting chain. **The only place the app touches `sephora_oltp`**, on a separate connection that degrades to a warning if that database is down |

No chart reads a base table.

## Underlying star schema

Everything above resolves to this. The dashboard does not join it by hand —
that is the views' job.

```
                        dw.dim_brand (304)
                              |
                              | brand_key
                              v
  dw.dim_date  <---------  dw.dim_product (8,494)
   (5,379)      date_key         |
       ^                         | product_key
       |                         v
       +---------------  dw.fact_reviews  ---------------+
                          (1,093,371)                     |
                          grain: one row per review       |
                               |                          |
                  customer_key |                          | reviewer_profile_key
                               v                          v
                    dw.dim_customer (503,216)   dw.dim_reviewer_profile (1,896)
                    identity only (D2)          junk dimension (D2)
```

Row counts verified against the live database on 2026-08-08.

## Two schema facts that shape what the dashboard can show

**`fact_reviews` has no `brand_key`** (D11). Brand is functionally determined by
product, so a copy on the fact would add no information while creating a way
for the two to disagree. Every brand-level view therefore joins
`fact_reviews → dim_product → dim_brand`. This is why `vw_rating_by_brand`
exists as a view rather than being assembled in the app.

**Reviewer attributes live on `dim_reviewer_profile`, not `dim_customer`**
(D2). They were recorded per *review*, not per person — 22,503 authors (4.47%)
gave more than one distinct answer across their reviews, covering 149,788
reviews (13.69%). Held on `dim_customer` behind a unique key, one profile would
have been forced per author and roughly one review in seven mis-tagged, with no
constraint violation and nothing downstream to notice. **The BQ4 charts are the
exact visual that would have been quietly wrong.**

## Freshness

`fact_reviews` is append-only via `ON CONFLICT (source_row_id, product_id) DO
NOTHING`. The dashboard caches query results for 5 minutes; **Refresh data**
clears that cache. Running the Airflow DAG in `incremental` mode and clicking
Refresh is what makes the pipeline's effect visible on screen.

## Permissions

The app connects with the credentials in `.env` (currently `postgres`). It only
ever issues `SELECT`. For anything beyond a local demo it should have a
read-only role:

```sql
CREATE ROLE dashboard_reader LOGIN PASSWORD '...';
GRANT USAGE ON SCHEMA dw TO dashboard_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA dw TO dashboard_reader;
```

Not applied here — noted as a real gap rather than presented as done.
