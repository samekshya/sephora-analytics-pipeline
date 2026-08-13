# Sephora Reviews Analytics Warehouse
## Problem Statement & Raw Data Documentation

---

## 1. Problem Statement

### Background

Sephora sells thousands of products across hundreds of brands, and customers leave over a
million reviews against them. The product catalogue and the review stream live in different
files with different grains, and the review file repeats product attributes on every row.
Answering a basic question — *does a higher price actually buy a better-rated product?* —
means reconciling those files by hand every time.

### Goal

Build an end-to-end data engineering pipeline that explores, cleans, normalizes, models and
loads Sephora product and review data into an analytics-ready warehouse, with a BI dashboard
on top.

### Business questions this project must answer

1. Which brands and categories earn the highest ratings, and which underperform?
2. How do review volume and average rating trend over time?
3. Does price predict satisfaction — do expensive products actually rate better?
4. Do reviewers with different skin types rate the same skincare products differently?

A fifth question — *which product attributes (Vegan, Clean at Sephora…) correlate with
rating?* — was evaluated against the data and deliberately dropped. See Section 5 and
decision D3.

### Non-functional requirements

- **Traceability** — every warehouse row must trace back to a raw source record
- **Idempotency** — the pipeline must be safely re-runnable without duplicating data
- **Incremental capability** — new reviews must load without reprocessing the whole history
- **Visibility** — failures must be logged and diagnosable, not silent

### Explicitly out of scope

- Real-time/streaming ingestion — the source is a static batch export
- Sentiment analysis or NLP on review text — the text is stored in the OLTP layer for
  traceability, but no locked business question needs it (D6)
- `highlights` and `ingredients` — evaluated during exploration, then descoped (Section 5)
- Cloud deployment, Spark, object storage — noted as future work, not built
- Product recommendation modelling — an analytics/ML problem, not a data engineering one

---

## 2. Data Source Overview

**Source**: [Sephora Products and Skincare Reviews](https://www.kaggle.com/datasets/nadyinky/sephora-products-and-skincare-reviews)
(Kaggle), scraped from Sephora's US site in March 2023.

**Format**: CSV — one product catalogue file, and five review files split by product range.

**Scale**: 8,494 products · 1,094,411 reviews · 503,216 reviewers · 304 brands ·
reviews spanning 2008-08-28 to 2023-03-21.

**Why this dataset**: the two sides join cleanly on a real key (verified in Section 4), the
review volume is large enough to make incremental loading a genuine requirement rather than a
demonstration, and the reviewer attributes create a real modelling problem worth solving
(Section 4).

Every figure in this document was produced by `explore.py` against the actual files. Nothing
is taken from the dataset's own description.

---

## 3. Raw Data Description

### `product_info.csv`

- **Grain**: one row per product
- **Rows**: 8,494 · **Columns**: 27
- **Key columns**: `product_id`, `product_name`, `brand_id`, `brand_name`, `price_usd`,
  `rating`, `reviews`, `loves_count`, `primary_category`, `secondary_category`,
  `tertiary_category`, `size`, `highlights`, `ingredients`, and boolean flags
  (`limited_edition`, `new`, `online_only`, `out_of_stock`, `sephora_exclusive`)
- **Role**: source for `dim_brand`, `dim_product`, and the 3NF `brand` / `category` / `product`
  tables

**Quality profile**

| Check | Result |
|---|---|
| Duplicate `product_id` | 0 |
| `brand_id` → `brand_name` | strictly 1:1 across 304 brands |
| `price_usd <= 0` | 0 |
| `sale_price_usd > price_usd` | 0 |
| `rating` outside 1–5 | 0 |
| `price_usd` range | $3.00 – $1,900.00 |

**Null counts** (of 8,494): `sale_price_usd` 8,224 · `value_price_usd` 8,043 ·
`child_max_price` / `child_min_price` 5,740 · `highlights` 2,207 · `size` 1,631 ·
`variation_value` 1,598 · `variation_type` 1,444 · `tertiary_category` 990 ·
`ingredients` 945 · `rating` / `reviews` 278 · `secondary_category` 8.

The heavily-null pricing columns (`value_price_usd`, `sale_price_usd`, `child_*_price`) are
dropped at the staging boundary — 68–97% null and unused by any locked question.

### `reviews_0-250.csv`, `reviews_250-500.csv`, `reviews_500-750.csv`, `reviews_750-1250.csv`, `reviews_1250-end.csv`

- **Grain**: one row per review
- **Rows**: 602,130 + 206,725 + 116,262 + 119,317 + 49,977 = **1,094,411** · **Columns**: 18
- **Key columns**: `author_id`, `product_id`, `rating`, `is_recommended`, `helpfulness`,
  `total_feedback_count`, `total_pos_feedback_count`, `total_neg_feedback_count`,
  `submission_time`, `review_text`, `review_title`, `skin_tone`, `skin_type`, `eye_color`,
  `hair_color`
- **Role**: source for `fact_reviews`, `dim_customer` and `dim_reviewer_profile`

The files are split **by product range**, not by date — each product's reviews live entirely
in one file. This matters for the idempotency key (Section 4).

**Null counts** (of 1,094,411): `helpfulness` 561,592 · `review_title` 310,654 ·
`hair_color` 226,768 · `eye_color` 209,628 · `skin_tone` 170,539 · `is_recommended` 167,988 ·
`skin_type` 111,557 · `review_text` 1,444.

**Rating distribution** — heavily skewed positive, which any "average rating" visual has to
account for:

| Rating | Reviews |
|---|---|
| 5★ | 698,951 |
| 4★ | 199,389 |
| 3★ | 81,816 |
| 2★ | 53,032 |
| 1★ | 61,223 |

**Review volume by year** — growth is steep and recent, so a trend chart is meaningful:

| Year | Reviews | | Year | Reviews |
|---|---|---|---|---|
| 2008 | 2,761 | | 2016 | 33,137 |
| 2009 | 9,709 | | 2017 | 54,592 |
| 2010 | 13,485 | | 2018 | 97,996 |
| 2011 | 12,417 | | 2019 | 143,860 |
| 2012 | 11,800 | | 2020 | 215,449 |
| 2013 | 15,621 | | 2021 | 202,012 |
| 2014 | 18,224 | | 2022 | 192,227 |
| 2015 | 21,590 | | 2023 | 49,531 (to 21 March) |

**`review_text`**: 350 MB in total. Length runs 8 to 6,448 characters, median 263, mean 321.
This volume is why the text stops at the OLTP boundary and the warehouse stores
`review_length` instead (D6).

---

## 4. Verified Data Relationships

Five properties were tested empirically before anything was built on them.

### 4.1 Reviews → products: no orphans

```
Product IDs in product_info:      8,494
Distinct product IDs in reviews:  2,351
Orphan review rows:                   0
```

Every review points at a product that exists. Note that only 2,351 of the 8,494 catalogue
products have any reviews — the catalogue is far wider than the review coverage, which the
dashboard has to state rather than imply.

### 4.2 `UNIQUE(source_row_id, product_id)` is a valid idempotency key

The CSV row index restarts at 0 in every one of the five files, which looks like a collision
risk:

```
reviews_0-250.csv         0 .. 602,129
reviews_250-500.csv       0 .. 206,724
reviews_500-750.csv       0 .. 116,261
reviews_750-1250.csv      0 .. 119,316
reviews_1250-end.csv      0 ..  49,976
```

Tested rather than assumed: **0 duplicate `(source_row_id, product_id)` pairs** across all
1,094,411 rows. Because the files are split by product range, a given product appears in
exactly one file, so the pair cannot collide. The key is sound (D13).

### 4.3 Reviewer attributes belong to the review, not the reviewer

The single most consequential finding. `skin_tone`, `skin_type`, `eye_color` and `hair_color`
are **not** stable properties of an author:

| Attribute | Authors with more than one distinct value | Max distinct |
|---|---|---|
| `skin_tone` | 12,525 | 4 |
| `skin_type` | 8,387 | 4 |
| `hair_color` | 7,614 | 4 |
| `eye_color` | 827 | 3 |

```
Authors total:                         503,216
Authors whose profile is NOT constant:  22,503 (4.47%)
Reviews written by those authors:      149,788 (13.69%)
Distinct four-attribute combinations:    2,003 of 4,200 possible
```

A customer dimension keyed `UNIQUE` on the author, holding these four attributes, would force
one profile per person — silently mis-tagging roughly **one review in seven**, and breaking
precisely the business question the table exists to answer. Resolved with a junk dimension
(D2).

### 4.4 Duplicate reviews: the dedup key must include the date

```
Duplicates on (author_id, product_id):                   5,525
Duplicates on (author_id, product_id, submission_time):  1,040
Difference:                                              4,485
```

The 4,485-row difference is the same author reviewing the same product on **different dates** —
legitimate re-reviews. Deduplicating on the pair would delete real data; the triple is the
correct key (D4).

### 4.5 `helpfulness` is undefined, not missing

```
Rows with total_feedback_count = 0:  561,592
Rows with helpfulness NULL:          561,592
Rows where the two disagree:               0
Rows where pos + neg != total:             0
```

`helpfulness` is NULL exactly when nobody voted on the review — a perfect correspondence
across all 1.09M rows. It is a value that doesn't exist yet, not a value that went missing, so
it is never imputed (D5). The feedback counts are internally consistent everywhere.

---

## 5. Data Quality Issues Found

| Issue | Measured | Treatment |
|---|---|---|
| Duplicate reviews | 1,040 on (author, product, date) | Removed in `clean.py` |
| `eye_color` casing | Both `'Grey'` and `'gray'` present | Normalised to one value |
| `skin_tone` sentinel | `'notSureST'` — a "not sure" placeholder, not a skin tone | Mapped to `Unknown` |
| Redundant review columns | `product_name`, `brand_name`, `price_usd` repeat on every review row and disagree with `product_info.csv` on **0 of 2,351** products | Dropped at the staging boundary |
| Null reviewer attributes | 111K–227K per attribute | Mapped to `'Unknown'` so the junk dimension has no NULL members |
| Sparse pricing columns | 68–97% null | Dropped at the staging boundary |
| Category "hierarchy" | One `secondary_category` appears under up to **7** different primaries (`Value & Gift Sets` 7, `Mini Size` 5, then six others at 2) | Keyed on the full (primary, secondary, tertiary) triple — 174 distinct — rather than modelled as nested levels (D1) |

### `highlights` — evaluated, then descoped

`highlights` holds a stringified list of marketing tags:

```
"['Vegan', 'Hydrating', 'Cruelty-Free']"
```

Profiled before deciding:

```
Distinct tags:                            112
Products with no highlights:            2,207
Mean tags per product (of those with any): 4.8
Max tags on one product:                    9
Total product-tag pairs:               30,204
```

Top tags: Vegan (2,623 products) · Cruelty-Free (1,775) · Clean at Sephora (1,534) · Without
Parabens (1,414) · Good for: Dryness (1,221) · Hydrating (1,170).

A cell holding several values breaks **1NF**, so storing this column would require a
`highlight` table plus a `product_highlight` bridge in the OLTP layer, and a `dim_highlight`
plus a bridge in the warehouse. Keeping the raw list in a text column was never an option — it
would make the "3NF" claim false.

**Decision**: cut the column at the cleaning step, and drop business question #5 with it, to
keep scope proportionate to an 8-minute presentation and avoid many-to-many filter complexity
in Power BI. `explore.py::explore_highlights()` remains in the script so the decision is
visibly measured rather than accidental. See D3.

`ingredients` (945 nulls, unbounded free text, no locked question) is dropped on the same
basis, without the same analysis — no business question came close to needing it.

---

## 6. Incremental Load Design

The source is a static export, so incremental loading is demonstrated by splitting the real
data chronologically rather than generating synthetic rows.

```
Cutoff: 2023-01-01
Full load (before cutoff):   1,044,880 rows
Incremental (from cutoff):      49,531 rows

Incremental batch by month:
  2023-01   16,907
  2023-02   16,754
  2023-03   15,870
```

Three months of real data at meaningful volume, enough to show the watermark advancing across
multiple runs (D8). The full-load figure is before deduplication; the exact loaded count is
measured by `clean.py` and recorded in the project checkpoint.

**Grain check**: `submission_time` has a **non-midnight time component on 0 of 1,094,411
rows**. Every timestamp is date-only, so a date-grain key and a date-grain watermark lose
nothing (D12).

---

## 7. How to reproduce these figures

```bash
python scripts/explore.py
```

Uncomment the function(s) you want in `main()`. Each function answers one question and prints
its own findings:

| Function | Answers |
|---|---|
| `row_counts` | How big is each file? |
| `explore_products` | Columns, nulls, duplicates, price sanity |
| `explore_reviews` | Columns, nulls, rating spread, date range |
| `explore_review_text` | How much text volume is there? (D6) |
| `check_duplicates` | Which dedup key is correct? (D4) |
| `check_referential_integrity` | Do any reviews point at missing products? |
| `check_idempotency_key` | Is `(source_row_id, product_id)` unique? (D13) |
| `check_reviewer_profile_consistency` | Do reviewer attributes belong to the author? (D2) |
| `check_attribute_values` | What are the actual attribute values? (casing defects) |
| `check_category_hierarchy` | Is the category hierarchy real? (D1) |
| `check_helpfulness` | Is `helpfulness` missing or undefined? (D5) |
| `check_redundant_review_columns` | Do the repeated product columns agree? |
| `explore_highlights` | What would keeping `highlights` cost? (D3) |
| `check_incremental_split` | How much data is on each side of the cutoff? (D8) |
