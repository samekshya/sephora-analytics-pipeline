# Data directory

The CSVs are **not** in this repository — together they are about 550 MB, well
past what belongs in git. `.gitignore` excludes `data/raw/` and
`data/processed/` entirely. This file explains what to put where.

## 1. Download the source data

**Sephora Products and Skincare Reviews** by Nadyinky, on Kaggle:
<https://www.kaggle.com/datasets/nadyinky/sephora-products-and-skincare-reviews>

## 2. Place the files exactly like this

```
data/
├── README.md                          <- this file (committed)
├── raw/                               <- you create this; gitignored
│   ├── product_info.csv
│   ├── reviews_0-250.csv
│   ├── reviews_250-500.csv
│   ├── reviews_500-750.csv
│   ├── reviews_750-1250.csv
│   └── reviews_1250-end.csv
└── processed/                         <- created by clean.py; gitignored
    ├── products.csv
    └── reviews.csv
```

`clean.py` globs `data/raw/reviews_*.csv`, so the exact filenames don't matter
as long as they start with `reviews_` and `product_info.csv` is named exactly
that.

## 3. Expected contents

Verified against the source files on 2026-08-06, before any cleaning:

| File | Rows | Columns |
|---|---|---|
| `product_info.csv` | 8,494 | 27 |
| 5 × `reviews_*.csv` | 1,094,411 combined | 19 (+ an unnamed index column) |

If your row counts differ, the dataset has been updated since — `ingest.py`
asserts the post-cleaning counts and will refuse to commit a load that
disagrees, so you'll find out immediately rather than halfway through the
warehouse.

## 4. What the pipeline produces

`clean.py` writes `data/processed/`:

| File | Rows | Size | Notes |
|---|---|---|---|
| `products.csv` | 8,494 | 8.1 MB | 0 dropped |
| `reviews.csv` | 1,093,371 | 546.7 MB | 1,040 duplicates removed (D4) |

Nothing downstream reads `data/raw/` again — `ingest.py` `COPY`s only from
`data/processed/` into the `raw` schema of `sephora_oltp`.

## Why the raw CSVs stay out of git

Beyond size: the raw layer's job is traceability *within the database*, where
every source column is preserved and queryable. A second copy in version
control would be a copy nothing reads, and one that has to be kept in sync with
Kaggle by hand.
