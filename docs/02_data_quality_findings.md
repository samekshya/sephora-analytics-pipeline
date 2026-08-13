# 02 — Data Quality Findings

Everything here was measured by `explore.py` against the raw CSVs before any
code was written on top of it. The point of doing it first was to make the
modelling decisions consequences of the data rather than of habit.

---

## 1. Source profile

### `product_info.csv` — 8,494 rows × 27 columns, one row per product

| Check | Result |
|---|---|
| Duplicate `product_id` | **0** |
| `brand_id` → `brand_name` | **strictly 1:1** across 304 brands |
| `price_usd <= 0` | 0 |
| `sale_price_usd > price_usd` | 0 |
| `rating` outside 1–5 | 0 |
| `price_usd` range | $3.00 – $1,900.00 |

**Null counts** (of 8,494): `sale_price_usd` 8,224 · `value_price_usd` 8,043 ·
`child_max_price`/`child_min_price` 5,740 · `highlights` 2,207 · `size` 1,631 ·
`variation_value` 1,598 · `variation_type` 1,444 · `tertiary_category` 990 ·
`ingredients` 945 · `rating`/`reviews` 278 · `secondary_category` 8.

### Five `reviews_*.csv` files — 1,094,411 rows, one row per review

| File | Rows |
|---|---|
| `reviews_0-250.csv` | 602,130 |
| `reviews_250-500.csv` | 206,725 |
| `reviews_500-750.csv` | 116,262 |
| `reviews_750-1250.csv` | 119,317 |
| `reviews_1250-end.csv` | 49,977 |
| **Total** | **1,094,411** |

The files are split **by product range, not by date** — each product's reviews
live entirely in one file. This is what makes the idempotency key work (§4).

**Null counts**: `helpfulness` 561,592 · `review_title` 310,654 · `hair_color`
226,768 · `eye_color` 209,628 · `skin_tone` 170,539 · `is_recommended` 167,988 ·
`skin_type` 111,557 · `review_text` 1,444.

**Rating distribution** — heavily skewed positive, which any "average rating"
visual has to account for:

| Rating | Reviews |
|---|---|
| 5★ | 698,951 |
| 4★ | 199,389 |
| 3★ | 81,816 |
| 2★ | 53,032 |
| 1★ | 61,223 |

**`review_text`**: 350 MB total, 8–6,448 characters, median 263, mean 321. This
volume is why the text stops at the OLTP boundary and the warehouse carries
`review_length` instead (**D6**).

---

## 2. Defects found and fixed

| Issue | Measured | Treatment | Where |
|---|---|---|---|
| Duplicate reviews | **1,040** on (author, product, date) | Removed | `clean.py` |
| `eye_color` casing | Both `'Grey'` and `'gray'` present — 4,859 rows | Collapsed to `'gray'` | `clean.py` |
| `skin_tone` sentinel | `'notSureST'` on 70 rows — a "not sure" placeholder, not a skin tone | Mapped to NULL, then `'Unknown'` | `clean.py` → staging |
| Null reviewer attributes | 111K–227K per attribute | `'Unknown'` at the staging boundary | `20260806120014_load_staging.sql` |
| Redundant review columns | `product_name`, `brand_name`, `price_usd` repeat on every review row and disagree with the catalogue on **0 of 2,351** products | Dropped at the raw→3NF boundary | **D14** |
| Sparse pricing columns | 68–97% null | Dropped at the raw→3NF boundary | **D14** |
| Whitespace | 16,072 product cells, 1,030,753 review cells | Trimmed | `clean.py` |

Once cleaning collapses `'Grey'`→`'gray'` and `'notSureST'`→`'Unknown'`, the
lookup tables settle at **13 skin tones, 4 skin types, 5 eye colors, 7 hair
colors**, and the distinct four-attribute combinations fall from **2,003 in the
raw data to 1,896** — which is the row count of `dim_reviewer_profile`.

Why the null treatment differs by layer: in `3nf.review` a missing answer is
correctly a **NULL foreign key**. In `staging.review` and the warehouse it
becomes the string **`'Unknown'`**, because a junk dimension with NULL members
cannot be joined to or filtered on in a dashboard, and "declined to say" is a
real answer worth showing. Two layers, two correct answers to the same question.

---

## 3. Reviewer attributes belong to the review, not the reviewer

**The most consequential finding in the project.** `skin_tone`, `skin_type`,
`eye_color` and `hair_color` are **not** stable properties of an author:

| Attribute | Authors with >1 distinct value | Max distinct |
|---|---|---|
| `skin_tone` | 12,525 | 4 |
| `skin_type` | 8,387 | 4 |
| `hair_color` | 7,614 | 4 |
| `eye_color` | 827 | 3 |

```
Authors total:                         503,216
Authors whose profile is NOT constant:  22,503  (4.47%)
Reviews written by those authors:      149,788  (13.69%)
Distinct four-attribute combinations:    2,003  of 4,200 possible (1,896 after cleaning)
```

A customer dimension keyed `UNIQUE` on the author and holding these four
attributes would force one profile per person — silently mis-tagging roughly
**one review in seven**, with no constraint violation and nothing downstream to
notice. It would corrupt precisely the business question those attributes exist
to answer (Q4).

Resolved with a **junk dimension**, `dim_reviewer_profile`, joined from the
fact table at the grain the attributes were actually recorded: per review.
`dim_customer` keeps identity only. See **D2**.

---

## 4. Verified relationships

### 4.1 No orphan reviews

```
Product IDs in product_info:      8,494
Distinct product IDs in reviews:  2,351
Orphan review rows:                   0
```

Every review points at a product that exists. Note that only **2,351 of 8,494**
catalogue products have any reviews — the catalogue is far wider than review
coverage, which the dashboard states rather than implies.

### 4.2 `(source_row_id, product_id)` is a valid idempotency key

The CSV row index restarts at 0 in every file, which looks like a collision
risk:

```
reviews_0-250.csv         0 .. 602,129
reviews_250-500.csv       0 .. 206,724
reviews_500-750.csv       0 .. 116,261
reviews_750-1250.csv      0 .. 119,316
reviews_1250-end.csv      0 ..  49,976
```

Tested rather than assumed: **0 duplicate pairs** across all 1,094,411 rows.
Because the files are split by product range, a given product appears in
exactly one file, so the pair cannot collide (**D13**).

### 4.3 The dedup key must include the date

```
Duplicates on (author_id, product_id):                   5,525
Duplicates on (author_id, product_id, submission_time):  1,040
Difference:                                              4,485
```

The 4,485-row difference is the same author reviewing the same product on
**different dates** — legitimate re-reviews. Deduplicating on the pair would
delete real data; the triple is the correct key (**D4**).

### 4.4 `helpfulness` is undefined, not missing

```
Rows with total_feedback_count = 0:  561,592
Rows with helpfulness NULL:          561,592
Rows where the two disagree:               0
Rows where pos + neg != total:             0
```

A perfect correspondence across all 1.09M rows: `helpfulness` is NULL exactly
when nobody voted. It is a value that doesn't exist yet, not one that went
missing, so it is **never imputed** (**D5**). Both invariants are enforced as
`CHECK` constraints rather than merely observed.

### 4.5 The category "hierarchy" is not a hierarchy

One `secondary_category` appears under up to **7 different primaries**
(`Value & Gift Sets` 7, `Mini Size` 5, six others at 2). Modelling it as nested
levels would assert a relationship the data does not have, and any rollup built
on it would produce wrong totals. Keyed on the full (primary, secondary,
tertiary) triple instead — 174 distinct (**D1**).

### 4.6 The date grain is a date

`submission_time` has a non-midnight time component on **0 of 1,094,411 rows**.
A date-grain key and a date-grain watermark lose nothing (**D12**).

---

## 5. `highlights` — evaluated, then descoped

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

Top tags: Vegan (2,623 products) · Cruelty-Free (1,775) · Clean at Sephora
(1,534) · Without Parabens (1,414) · Good for: Dryness (1,221) · Hydrating
(1,170).

A cell holding several values breaks **1NF**, so keeping this column properly
would require a `highlight` table plus a `product_highlight` bridge in the OLTP
layer, and a `dim_highlight` plus a bridge in the warehouse. Storing the raw
comma-list in a single column was never an option — it would make the "3NF"
claim false.

**Decision**: cut at the cleaning step, and drop the sixth business question
with it, to keep scope proportionate to an 8-minute presentation.
`explore.py::explore_highlights()` remains in the script so the decision is
visibly measured rather than accidental (**D3**).

> **This is the project's only genuine many-to-many, and it was descoped
> deliberately.** The absence of bridge tables is a scope decision, not
> evidence that the domain has no many-to-many relationship. Saying otherwise
> would be untrue.

`ingredients` (945 nulls, unbounded free text) is dropped on the same basis
without the same analysis — no business question came close to needing it.

---

## 6. Reproducing these figures

```powershell
py explore.py
```

Each function answers one question and prints its own findings:

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
