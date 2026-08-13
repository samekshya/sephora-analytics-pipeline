# 07 — Dashboard Insights

Every number here was queried from the live warehouse on **2026-08-08** and is
reproducible with `sql/validation/dashboard_checks.sql`. Nothing is estimated.

**Baseline**: 1,093,371 reviews · 503,216 reviewers · 2,351 products reviewed
(of 8,494 in the catalogue) · 304 brands · average rating **4.2990** ·
**83.99%** recommend · 2008-08-28 → 2023-03-21.

---

## Q3 — Does price predict satisfaction? *(the headline finding)*

**No, not linearly. The relationship is an inverted U, and it reverses above $100.**

| Price band | Reviews | Avg rating | Std dev |
|---|---|---|---|
| Under $15 | 113,207 | 4.2383 | 1.2211 |
| $15–30 | 219,693 | 4.2756 | 1.1861 |
| $30–50 | 364,318 | 4.3055 | 1.1498 |
| **$50–100** | 331,249 | **4.3335** ← peak | 1.0996 |
| $100+ | 64,904 | 4.2708 ← falls back | 1.1366 |

Two things worth saying out loud:

**The mean is the weaker half of this finding.** The whole spread is about a
tenth of a star. The **standard deviation** is the sturdier result — but it is
*not* monotonic, and an earlier version of this document said it was. It falls
from 1.2211 to **1.0996 at $50–100** and then widens again to 1.1366 above
$100. Cheap products collect both delighted and furious reviewers; products
around $50–100 mostly meet expectations.

**Both curves turn in the same place, which is the real result.** $50–100 is
simultaneously the best-rated band *and* the most agreed-upon one, and $100+
regresses on both measures at once. That is a stronger claim than "dearer is
better" and it is the one the data actually supports.

**The $100+ reversal is the interesting part.** Satisfaction climbs with price
right up to $100 and then drops back to roughly what a $15 product achieves.
Above $100 expectations appear to outrun what the product can deliver.

> The dashboard's y-axis is **deliberately truncated** here. On a zero-based
> axis these five bars are visually identical and the finding disappears. The
> chart says so on its face.

---

## Q1 — Which brands and categories rate best and worst?

### Brands (minimum 500 reviews — 106 of 304 brands qualify)

| Best | Avg rating | | Worst | Avg rating |
|---|---|---|---|---|
| MARA | 4.8608 | | Topicals | 3.6590 |
| DAMDAM | 4.7394 | | DERMAFLASH | 3.7856 |
| Dr. Lara Devgan | 4.7164 | | Isle of Paradise | 3.8601 |

The minimum-review floor is the single most important control on the page. Set
it to 1 and "best brands" becomes a list of brands with one 5-star review. The
dashboard states how many brands clear the current floor so the sample is
visible rather than implied.

### Categories (secondary level — **D16**)

| Category | Reviews | Avg rating |
|---|---|---|
| Moisturizers | 297,201 | 4.3172 |
| Treatments | 221,871 | 4.3040 |
| Cleansers | 200,477 | **4.3443** ← best |
| Mini Size | 85,433 | 4.2856 |
| Eye Care | 74,966 | 4.1784 |
| Masks | 70,483 | 4.3410 |
| Lip Balms & Treatments | 61,321 | 4.3327 |
| Sunscreen | 41,126 | **4.1665** ← worst |

**Grouped on `secondary_category`, not `primary`.** Every reviewed product in
this dataset is `Skincare` at the primary level — the review scrape covers
skincare only — so a primary-category chart is one bar. `vw_rating_by_skin_type`
filtering to Skincare returns all 1,093,371 rows, which confirms it
independently.

**Sunscreen (4.1665) and Eye Care (4.1784) are the two weak spots**, and they
are weak for opposite reasons worth separating. Sunscreen is the one product
type people buy out of obligation rather than desire — texture and white cast
complaints dominate. Eye Care is the category where the promised effect
(reducing dark circles, fine lines) is hardest to actually observe, so it
disappoints even when the product is fine.

Cleansers rate best (4.3443) and are cheap to make — the categories where
expectations are simplest to meet are the ones that satisfy.

---

## Q2 — Hype vs reality

`loves_count` is a wishlist add, recorded **before** purchase. Rating is
recorded **after**. The gap between the two, as percentile ranks, is `hype_gap`.

### Most overhyped — loved far more than the ratings justify

| Product | Brand | Loves | Reviews | Rating | Gap |
|---|---|---|---|---|---|
| Vitamin C Suspension 23% + HA Spheres 2% | The Ordinary | 132,601 | 1,113 | **3.4456** | +0.93 |
| Oat Cleansing Balm | The INKEY List | 127,819 | 2,998 | 3.6044 | +0.91 |
| Caffeine 5% + EGCG Depuffing Eye Serum | The Ordinary | 281,928 | 2,123 | 3.7715 | +0.91 |
| Faded Serum for Dark Spots | Topicals | 139,007 | 918 | 3.6590 | +0.90 |
| The Kissu Lip Mask | Tatcha | 202,204 | 1,232 | 3.7662 | +0.90 |

The Ordinary appears twice in the top five. Its position is coherent: very
cheap, very heavily marketed, very widely wishlisted — and then rated around
3.5. This is the clearest demonstration in the dataset that **intention and
satisfaction are different signals**, and that a "most loved" ranking is not a
quality ranking.

### Sleeper hits — better than their love count suggests

| Product | Brand | Loves | Reviews | Rating | Gap |
|---|---|---|---|---|---|
| High Performance Face Cleanser with Niacinamide | MACRENE actives | 204 | 55 | **4.9273** | −0.99 |
| High Performance Face Serum with Vitamin C | MACRENE actives | 254 | 96 | 4.9271 | −0.99 |
| Aquarius BHA + Blue Tansy Clarity Cleanser | Herbivore | 518 | 55 | 4.9273 | −0.99 |
| Honey Infused Lip Oil | Gisou | 547 | 81 | 4.9012 | −0.98 |
| Pore Perfecting Liquid Exfoliator | alpyn beauty | 654 | 100 | 4.9300 | −0.98 |

Near-perfect ratings on a few hundred wishlist adds. Minimum 50 reviews applies
— without it this list would be products with three reviews.

---

## Q4 — Do skin type and tone change ratings?

### Skin type

| Skin type | Reviews | Avg rating |
|---|---|---|
| *Unknown* | 111,342 | *4.3121* |
| Combination | 544,041 | 4.3092 |
| Dry | 185,760 | 4.2911 |
| Normal | 131,818 | 4.2822 |
| Oily | 120,410 | 4.2708 |

Combination is by far the largest group (544,041 reviews — half the dataset),
which is itself worth noting: it is the default self-description, and the
answer people pick when unsure.

### Skin tone (minimum 1,000 reviews)

| Skin tone | Reviews | Avg rating |
|---|---|---|
| medium | 70,408 | 4.3311 |
| Unknown | 170,361 | 4.3204 |
| lightMedium | 196,412 | 4.3189 |
| light | 266,165 | 4.3012 |
| fair | 207,871 | 4.2734 |
| deep | 20,583 | 4.2560 |
| fairLight | 56,194 | 4.2547 |
| porcelain | 1,598 | 4.2247 |

**Present this as a weak signal, not a headline.** The skin-type spread is
0.038 and the skin-tone spread about 0.11 — real, consistent, and small. Saying
"oily-skinned reviewers are harder to please" overstates a 0.04 difference on a
five-point scale.

What matters more is that **this is the question the junk dimension exists
for**. Held on `dim_customer`, these four attributes would have been forced to
one value per author, mis-tagging 13.69% of reviews. These two tables are the
exact output that would have been quietly wrong — plausible-looking, and
untrue (**D2**).

`Unknown` is kept rather than filtered — 111,342 reviews on skin type and
170,361 on skin tone. It means the reviewer declined to answer, which is a real
answer, and hiding it would overstate how much is actually known.

It also happens to rate **highest on both axes** (4.3121 / 4.3204). That is not
a finding about skin, it is a finding about behaviour: people who skip the
profile questions are, on average, slightly happier reviewers. Worth stating
precisely because it is the kind of artifact that looks like a result if you
filter `Unknown` out without saying so.

---

## Q5 — Volume and rating over time

| Year | Reviews | Avg rating | | Year | Reviews | Avg rating |
|---|---|---|---|---|---|---|
| 2008 | 2,760 | 4.4533 | | 2016 | 33,136 | 4.3037 |
| 2009 | 9,702 | 4.4584 | | 2017 | 54,561 | 4.3538 |
| 2010 | 13,460 | 4.4569 | | 2018 | 97,976 | 4.3444 |
| 2011 | 12,402 | 4.4497 | | 2019 | 143,750 | 4.2409 |
| 2012 | 11,778 | 4.4453 | | **2020** | **215,278** ← peak | **4.2075** ← trough |
| 2013 | 15,505 | 4.3953 | | 2021 | 201,686 | 4.3210 |
| 2014 | 18,146 | 4.3176 | | 2022 | 192,141 | 4.3384 |
| 2015 | 21,587 | 4.2689 | | 2023 | 49,503 | 4.2899 (to 21 Mar) |

**Volume peaked in 2020 at 215,278 — and that same year had the lowest average
rating in the dataset, 4.2075.** The two move together: the years with the most
reviews are the years with the harshest ones. The most likely reading is
composition, not product quality — a rush of new, less-committed reviewers
during the 2020 lockdown skincare boom rates more critically than the small,
enthusiastic early cohort did (2008–2012 all sit above 4.44 on a few thousand
reviews a year).

Ratings recovered to 4.3384 by 2022.

**2023 is partial** — data ends 21 March. The dashboard annotates the final
month `partial month` so the drop is not misread as collapsing demand.

---

## Review length — longer reviews are more moderate, not more negative

The common assumption that unhappy customers write longer reviews is not
supported here. Average rating is nearly flat across the five populated
length buckets: **4.2784 to 4.3342**, a spread of only 0.056 stars.

| Length bucket | Reviews | Avg rating | Rating std dev | 1-star | 5-star |
|---|---:|---:|---:|---:|---:|
| Very short (<100) | 100,133 | 4.2784 | 1.2555 | 8.15% | 67.35% |
| Short (100–249) | 408,384 | 4.2979 | 1.1750 | 6.13% | 65.06% |
| Medium (250–499) | 413,790 | 4.3069 | 1.1156 | 4.87% | 62.87% |
| Long (500–999) | 148,816 | 4.2885 | 1.1074 | 4.65% | 61.07% |
| Very long (1,000+) | 20,804 | 4.3342 | 1.0589 | 3.73% | 62.52% |

The useful signal is **polarisation**. As length rises, the 1-star share and
the 5-star share both fall, while rating variation declines monotonically.
Long reviews are more moderate and internally consistent; the two shrinking
tails largely cancel in the mean. The 1,444 rows with unknown review length
remain in the reconciliation view but are labelled separately in the app.

---

## What the dashboard deliberately does *not* claim

- **No causation.** Price *correlates* with consistency; nothing here shows
  price *causes* satisfaction.
- **Coverage is stated, not hidden.** 2,351 of 8,494 catalogue products have
  any reviews. The KPI row shows both numbers so "8,494 products" cannot be
  read as review coverage.
- **Helpfulness is averaged only over reviews that received a vote**
  (532,310 of 1,093,371). Imputing zero for the rest would halve it and mean
  nothing (**D5**).
- **Skewed ratings.** 64% of all reviews are 5★. An average of 4.30 is a
  *low* score in this distribution, not a high one.

---

## Reproducing every figure

```powershell
docker exec -i leapfrog_sephora_postgres psql -U postgres -d sephora_dw -q -f - < sql/validation/dashboard_checks.sql
py -m streamlit run dashboard/app.py
```

If the dashboard and that script ever disagree, **the dashboard is wrong** —
the views and the fact table are the authority. See
[`dashboard/README.md`](../dashboard/README.md) for what each visual shows.
