# Sephora Reviews Analytics Pipeline — 8-minute speaking guide

The deck is built by `build_deck.ps1`. The timestamps below total **8:00** and
match the notes embedded in the PowerPoint file.

## Slide 1 — What was built (0:40)

This project turns the Sephora product catalogue and more than one million
skincare reviews into a reproducible analytics warehouse. The important point
is the complete chain: cleaning, a normalized OLTP model, dimensional ETL,
Airflow orchestration, quality controls, and a live Streamlit dashboard.

## Slide 2 — Source data and cleaning (0:50)

The catalogue and reviews arrive at different grains. I profiled them before
choosing rules: 1,094,411 raw reviews, 8,494 products, 304 brands, and 503,216
authors. Cleaning removes 1,040 duplicates on author, product, and date while
preserving legitimate re-reviews. It also standardizes Grey/gray and removes
the notSureST sentinel without dropping source columns.

## Slide 3 — End-to-end architecture (1:05)

The OLTP database has three deliberate layers. Raw is a traceable source
mirror; 3NF enforces relationships and removes redundancy; staging flattens the
validated entities for predictable ETL reads. Python then extracts, transforms,
reconciles, quality-checks, and loads a separate star-schema database. Ten SQL
views are the only dashboard read surface.

## Slide 4 — The modelling decision worth defending (1:10)

Reviewer attributes cannot safely live on a one-row-per-author dimension.
22,503 authors changed at least one profile attribute, affecting 149,788
reviews. A conventional customer dimension would silently attach the wrong
profile to about one review in seven. The solution is an identity-only customer
dimension plus a 1,896-row junk dimension at review grain.

## Slide 5 — ETL reliability and incremental loading (1:05)

The modules follow the course reference structure, with two stricter controls.
First, every transformed row is reconciled as loaded or dropped for a named
reason; unexplained loss stops the run. Second, the quality layer is a gate,
not a fixer. Full, historical, and watermark-driven incremental modes share
the same implementation, and every load is idempotent through database keys
and ON CONFLICT DO NOTHING.

## Slide 6 — Airflow proof, not just a diagram (1:10)

The DAG has 16 tasks. Dimensions run in parallel; product waits for brand; the
fact path is staged into extract, transform, quality, and load. The controlled
verification re-offered the historical population successfully in 164 seconds,
then removed only the 2023 fact slice. Incremental restored all 49,503 rows in
27 seconds. In both runs 15 tasks succeeded and the one_failed watcher was
correctly skipped.

## Slide 7 — What the dashboard actually tells us (1:25)

The strongest result is that price and satisfaction form an inverted U, not a
straight line. Ratings rise from 4.238 under $15 to 4.334 at $50–100, then fall
to 4.271 above $100. The better signal is consistency: rating variation narrows
as price rises. The hype view separates wishlist intention from satisfaction,
and the time series flags March 2023 as partial so it is not read as a demand
collapse. Skin-profile differences are small and labelled as weak signals.

## Slide 8 — Close and live-demo path (0:35)

The final state is 1,093,371 fact rows, zero orphan keys, zero duplicate fact
keys, 51 passing host tests, and 11 passing in-container DAG assertions. For a
live demo: show the successful incremental run, open the Streamlit overview,
move one SQL-backed control on Deep dive, and finish with the validation query
that reconciles every full-population view to the fact table.
