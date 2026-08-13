# Sephora Skincare Reviews — 8-minute speaking guide

Written against [`sephora_pipeline_deck.html`](sephora_pipeline_deck.html), nine slides.
The timings below total exactly **8:00**.

| Slide | Topic | Time |
|---|---|---|
| 1 | Title | 0:20 |
| 2 | The problem | 0:50 |
| 3 | The data source | 0:55 |
| 4 | OLTP schema | 0:55 |
| 5 | Star schema | 1:00 |
| 6 | Architecture | 0:50 |
| 7 | Airflow DAG | 1:15 |
| 8 | Design decisions | 0:50 |
| 9 | Dashboard | 1:05 |

---

## Slide 1 — Title (0:20)

An end-to-end analytics pipeline over the Sephora catalogue and 1.09 million skincare
reviews: raw CSV, a normalized OLTP database, a star-schema warehouse, Airflow, and a live
dashboard. Everything shown is measured against a loaded database, not estimated.

## Slide 2 — The problem (0:50)

The reviews already exist — the problem is that nothing lets you compare with them. You can
read one product page at a time, and a star rating on its own is not an answer: a product
with twelve reviews and one with 130,000 sit side by side, weighted the same, with no way to
hold price band or skin type steady.

There is also a signal buried in the data that no product page separates. `loves_count` is
recorded *before* purchase and the rating *after* it — wanting and liking are different
things, so the most marketed product reads as the best product.

This project makes each of those comparisons a single query, for shoppers, for brand and
category managers, and for analysts.

## Slide 3 — The data source (0:55)

A public Kaggle dataset: one product catalogue and five review files, fifteen years of
reviews from August 2008 to March 2023. 1,094,411 raw review rows, 8,494 products, 304
brands, 503,216 authors.

I profiled before writing a single cleaning rule — fourteen checks. Three findings shaped
the work. There are 1,040 duplicates on author, product *and* date, but 5,525 on author and
product alone, so the difference is legitimate re-reviews and the narrower key is the right
one. `helpfulness` is null exactly when the feedback count is zero, so those nulls are
undefined rather than missing and are never imputed. And `(source_row_id, product_id)`
collides zero times across all five files, which gives the fact table a real idempotency key.

Cleaning carries 1,093,371 rows forward and drops **no columns** — column trimming is a
scope decision and happens later, explicitly.

## Slide 4 — OLTP schema (0:55)

Nine tables in third normal form, foreign keys enforced. Two transitive dependencies come
out: `brand_name` depends on `brand_id`, not on the product, and the category triple likewise
— both move off `product` and are reached by foreign key. That is the 3NF change.

Category is keyed on the whole primary–secondary–tertiary triple, because one secondary
category appears under as many as seven different primaries. It is not a real hierarchy.

The choice to point out is on the right of the diagram: skin tone, skin type, eye and hair
colour hang off **review**, not **author**, because that is where they were recorded. `author`
holds identity and nothing else.

Three layers, each with one job: `raw` mirrors the CSVs for traceability, `3nf` enforces the
relationships, `staging` flattens them back into one predictable shape for the ETL. Zero row
gap across all three.

## Slide 5 — Star schema (1:00)

One fact, five dimensions, one grain: one row per review.

The reason `dim_customer` carries only an identity is measured, not stylistic. 22,503
authors — 4.47% — recorded more than one profile across their reviews, and those authors
wrote 149,788 reviews, about one in seven. Hanging skin tone and type off a per-author
dimension would attach the wrong profile to one review in seven, with no constraint violated
and nothing downstream to notice. Instead the four correlated attributes bundle into a
1,896-row junk dimension at review grain.

Note what is *not* on the fact table: there is no `brand_key`. Brand is functionally
determined by product, so a copy on a 1.09-million-row fact adds no information and creates a
way for the two to disagree after a bad load. Brand analysis joins through `dim_product`.

## Slide 6 — Architecture (0:50)

Left to right: `clean.py` and `ingest.py` take the CSVs into the OLTP database; the `etl`
package extracts, transforms, reconciles, quality-checks and loads the warehouse; eleven SQL
views are the dashboard's only read surface.

Two physical databases, deliberately, so the normalized model and the dimensional one cannot
quietly become one thing. Three named load modes — full, historical, and watermark-driven
incremental — share one implementation and one set of quality checks. And nothing is dropped
silently: every dropped row is counted against a named reason, and an unexplained gap raises
`ReconciliationError` and stops the run.

## Slide 7 — Airflow DAG (1:15)

Fifteen tasks, as the running instance renders them. The four dimensions load in parallel;
product waits on brand for its foreign key. The fact path is split into four separate tasks —
extract, transform, quality gate, load — so a failure names itself instead of pointing at one
opaque step.

The part worth pausing on is failure, not success. Cleanup has to run after failures so
staging is never left stranded, which is what `all_done` is for — but that made cleanup the
only leaf task, and Airflow reads run state from leaves. A failed extract therefore reported
a **green run over an empty warehouse**. Marking cleanup a teardown excludes it from run-state
calculation, so `load_fact_from_staging` becomes the leaf again and the failure propagates.
Same guarantee, and the DAG went from sixteen tasks and thirty-three edges to fifteen and
twenty-one.

I proved it by forcing a failure rather than trusting the documentation — and that run
exposed a pre-existing race that stranded 513,606 staging rows, because cleanup had only been
waiting on the fact load. It now waits on every staging writer. Historical runs green in 134
seconds, incremental restores 49,503 rows in 22.

## Slide 8 — Design decisions (0:50)

Twenty-four decisions are logged with the measurement behind each. These four changed the
shape of the project: the junk dimension instead of a profile on the customer; no `brand_key`
on the fact, because redundancy is only worth it when it buys something; a failed run that
must look failed; and reconcile-everything, gate-don't-fix. The last one matters most — the
quality layer only ever raises or warns. A check that quietly repairs its own finding is a
check nobody can audit.

## Slide 9 — Dashboard (1:05)

The headline result: price does not predict satisfaction, at least not linearly. Ratings
climb from 4.238 under $15 to 4.334 at $50–100, then fall back to 4.271 above $100 — an
inverted U.

The second chart is the better one. Rating spread narrows to 1.100 in exactly the same band
and widens again above it, so $50–100 is the sweet spot on both measures: best rated and most
agreed upon. Expensive products are not disliked, they are *divisive*.

Both are lines rather than bars on purpose. The whole spread is a tenth of a star, so the
axis has to be truncated — and a truncated axis under bars misleads, because bar length is
read from zero.

And every filter on that dashboard is a SQL parameter, not a dataframe filter. A client-side
filter would look identical on screen and be a different claim.

---

## If asked for a live demo

`DELETE FROM dw.fact_reviews WHERE submission_date >= '2023-01-01'` drops the warehouse to
1,043,868 rows and the watermark to 2022-12-31. Trigger the incremental DAG run: it restores
exactly 49,503 rows in about 22 seconds, with zero already present. Then re-run it — zero
extracted, gate skipped, nothing inserted. Finish on `sql/validation/dashboard_checks.sql`,
which reconciles every full-population view back to 1,093,371.
