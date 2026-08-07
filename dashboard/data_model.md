# What the dashboard reads

The app touches **only** the `dw` schema of `sephora_dw`, and only through
curated views wherever one exists. It never reads `sephora_oltp`, never touches
`raw` or `3nf`, and issues no `INSERT`/`UPDATE`/`DELETE` of any kind.

## Views consumed

| View | Page | Feeds | Grain |
|---|---|---|---|
| `vw_kpi_summary` | Overview | The 5-metric KPI row | 1 row |
| `vw_review_volume_by_month` | Overview | Volume bars, rating lines | 1 row per month (176) |
| `vw_rating_by_brand` | Overview | Best/worst brand bars | 1 row per brand (304) |
| `vw_rating_by_category` | Overview | Category bubble scatter | 1 row per category triple (174) |
| `vw_hype_vs_reality` | Deep dive | Hype scatter, both tables, price scatter | 1 row per product with ≥50 reviews (1,660) |
| `vw_rating_by_price_band` | Deep dive | Price band bars, std-dev line | 1 row per band (5) |
| `vw_rating_by_skin_type` | Deep dive | Skin type bars | skin_type × category |
| `vw_rating_by_skin_tone` | Deep dive | Skin tone bars | skin_tone × category |

## Base tables read directly

Only two, and only for populating filter widgets — never for a chart:

| Table | Why |
|---|---|
| `dim_product` | Distinct `secondary_category` values for the category filter, restricted to products that actually have reviews |
| `fact_reviews` | `min`/`max(submission_date)` for the date slider bounds |

Both are cheap: the first hits `idx_dim_product_primary_cat`, the second
`idx_fact_reviews_submission`.

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
