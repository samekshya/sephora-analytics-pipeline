# 05 — ETL and Incremental Loading

## The `etl/` package

One module per concern. Airflow tasks map 1:1 onto these functions — there is
no inline SQL or pandas in the DAG file.

| Module | Job | Never does |
|---|---|---|
| `extract.py` | Read `staging` into DataFrames; read warehouse key lookups back | Transform |
| `transform.py` | Resolve natural keys → surrogate keys, derive `price_band` | Write to a database |
| `reconcile.py` | Enforce the row-count identities | Repair anything |
| `quality.py` | **Gate**: raise on bad data | **Fix** bad data |
| `load.py` | `INSERT … ON CONFLICT DO NOTHING` | Decide what to load |
| `staging.py` | Per-run staging tables for the DAG | Anything the local runner needs |

`quality.py` being a gate and not a fixer is deliberate: a check that quietly
repairs what it finds can never fail, so it can never tell you anything.
Cleaning belongs in `clean.py`, where it is logged and counted.

---

## The three load modes

Replaces a two-mode design whose `--full-reload` actually stopped at
2023-01-01. That name claimed something the code did not do — anyone reading it
would reasonably believe the warehouse held everything, when a quarter of a year
was missing by design. **A mode that withholds data must say so in its name**
(**D17**).

| Mode | Selects | Rows | Purpose |
|---|---|---|---|
| `full` | Every review, **no date bound** | 1,093,371 | Build or rebuild the warehouse for real |
| `historical` | `submission_date < 2023-01-01` | 1,043,868 | **Demo baseline** — deliberately holds 2023 back |
| `incremental` | `submission_date > watermark` | 49,503 on first run | Normal operation |

```powershell
py scripts/pipeline.py --mode full
py scripts/pipeline.py --mode historical
py scripts/pipeline.py --mode incremental     # the default
```

In Airflow the same three are a `load_mode` Param rendered as a dropdown.

`extract_reviews_for_mode()` is the single place a mode string becomes a query,
so `pipeline.py` and the DAG cannot drift into disagreeing about what a mode
means.

### Why the demo splits real data

The source is a static export, so there is no genuinely "new" data to arrive.
Rather than generate synthetic rows, the real data is split chronologically at
**2023-01-01** (**D8**), holding back 49,503 real reviews across three months:

```
2023-01   16,904
2023-02   16,734
2023-03   15,865   (to the 21st)
```

Running `historical` then `incremental` demonstrates the watermark advancing
over real data, at meaningful volume.

---

## The watermark

```sql
SELECT COALESCE(MAX(submission_date), DATE '2000-01-01') FROM dw.fact_reviews;
```

Read **from the fact table itself**, not from a separate control table. The
fact table is the thing whose state actually matters, so it cannot disagree with
its own watermark. There is no control row to get out of sync, and no recovery
step after a restore.

Two properties that matter:

**Captured before any write.** In both `pipeline.py` and the DAG the watermark
is read at the start of the fact stage, before a single row is inserted.
Re-reading it later would read a value the same run had already advanced,
causing the run to skip its own rows.

**Strictly greater than, not `>=`.** The watermark is a date the warehouse has
already loaded *in full*. Using `>=` would re-offer every row from that day on
every run — `ON CONFLICT` would absorb them, but the run would report thousands
extracted and zero loaded, forever.

**Empty fact table falls back to 2000-01-01**, comfortably before the earliest
review (2008-08-28), so the first incremental run behaves as a full load without
special-casing.

---

## Idempotency

Every load targets a business key:

| Table | Conflict target |
|---|---|
| `dim_brand` | `(brand_id)` |
| `dim_product` | `(product_id)` |
| `dim_customer` | `(customer_id)` |
| `dim_reviewer_profile` | `(skin_tone, skin_type, eye_color, hair_color)` |
| `dim_date` | `(date_key)` |
| `fact_reviews` | `(source_row_id, product_id)` |

The **constraint** enforces idempotency, so it holds whether or not the caller
remembered. Verified both ways:

| Scenario | Offered | Inserted |
|---|---|---|
| Re-run a completed full load | 1,043,868 | **0** |
| Re-run incremental with a current watermark | 0 extracted | 0 |

Dimensions load in **full every run**; only the fact is incremental (**D10**).
A review arriving in an incremental batch for a newly-catalogued product must
find its product key already present, or the row gets dropped.

---

## Row reconciliation

Two identities, enforced rather than hoped for (**D19**):

```
rows_extracted == rows_transformed + sum(rows_dropped_by_reason)
rows_offered   == rows_inserted    + rows_already_present
```

Before this existed, `transform.py` dropped unresolved rows with a log warning
and nothing else — a silent data-loss channel with a paper trail nobody reads.
If 1,000 reviews pointed at a missing product, the run stayed green, the fact
table was quietly 1,000 rows short, and the only evidence was a `WARNING` among
thousands of log lines.

Now every `build_*` function returns `(DataFrame, drops)` where `drops` maps a
**named reason** to a count:

```python
{'unresolved_product': 12, 'unresolved_customer': 0,
 'unresolved_reviewer_profile': 0, 'out_of_range_date': 0}
```

Every reason is present **including the zeros**, so "nothing was dropped for
this reason" is distinguishable from "this reason was never checked". If the
identity fails to balance, `ReconciliationError` halts the run:

```
fact_reviews: row counts do not balance. extracted=100, transformed=90,
dropped=5 (accounted=95), UNEXPLAINED=5. Every dropped row must be counted
against a named reason.
```

Dropping rows is allowed. Dropping them without saying how many and why is not.

Counts come from `COUNT(*)` before and after, **not** `cursor.rowcount` —
`execute_values` sends one statement per page, so `rowcount` reports only the
last page. On the first 1.09M-row load with `PAGE_SIZE = 5000` it reported
3,868 instead of 1,043,868: the data was right, the number was nonsense, which
is worse than no number in a reconciliation.

---

## The quality gate

Runs on the **transformed** frame, before load. Two severities (**D21**):

| Severity | Behaviour | Checks |
|---|---|---|
| `hard_failure` | **Halts before any write** | null surrogate key, rating outside 1–5, negative counts, duplicate business key, referential integrity, row count below minimum |
| `warning` | Logs, run continues | null rate above an expected threshold |

The split is real rather than decorative. `is_recommended` is unanswered on
~15% of reviews and `helpfulness` is undefined wherever nobody voted — both are
legitimately null in bulk. Failing a run over that would be wrong; saying
nothing would be worse. So it warns, and a *shift* (say, 90% null) becomes
visible without stopping anything.

Warnings are logged **before** the hard-failure raise, so a run that dies still
leaves its warnings behind.

In Airflow a hard failure is re-raised as `AirflowFailException`, so the task
fails immediately instead of burning its 2-retry budget on something that will
never pass on retry.

**An empty frame skips the gate rather than failing it** — an incremental run
with nothing new is a valid outcome, not a fault. Without this, every quiet
Tuesday would page somebody.

---

## Stage order

Forced by foreign keys, not preference:

```
1.  dim_brand                                    (dim_product references it)
2.  dim_product, dim_customer, dim_reviewer_profile, dim_date   (parallel)
3.  fact_reviews                                 (references all four)
```

`extract_lookup_dim()` reads the surrogate keys back out of the warehouse after
the dimensions are loaded — keys come from Postgres `SERIAL`, never from pandas
(**D9**). Generating them client-side would mean two writers deciding the same
key space, which works right up until it doesn't.

---

## Memory: why the fact load is chunked

The first full-reload DAG run was **SIGKILLed**. `read_staged_rows` materialises
the whole result, and `_execute` then builds a list of tuples on top of it — at
1,043,868 rows that is two full copies resident at once. The local runner
survived it; the containerised worker did not.

`iter_staged_rows` uses a **named (server-side) cursor** so Postgres streams the
result, yielding DataFrames of at most `CHUNK_SIZE = 100,000` rows. Peak memory
is now capped regardless of batch size (**D15**).

The read side holds its cursor open for the whole iteration, so the write side
commits on a **separate connection** — committing on the same one would
invalidate the cursor mid-loop.

---

## Verification

```powershell
py -m pytest -q                                    # 51 passed
py -m pytest tests/unit -q                         # no database needed
docker exec -i leapfrog_sephora_postgres psql -U postgres -d sephora_dw -q -f - < sql/validation/dashboard_checks.sql
```

See [08 — Testing evidence](08_testing_evidence.md).
