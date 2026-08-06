"""
Exploration script for the Sephora products and reviews data.
Each function explores one file or answers one specific question about the data.
Run functions individually by commenting/uncommenting calls in main().

Findings from this script are written up in
docs/problem statement and data sources.md and drive the decisions recorded in
docs/09_decision_log.md.
"""

import ast
import glob
import os
from collections import Counter

import pandas as pd

FOLDER = os.path.join('data', 'raw')

# review_text is ~500MB across the five files and is never needed for structural
# profiling — excluded by default so every function below stays memory-bounded.
# explore_review_text() reads that one column on its own.
REVIEW_COLS = [
    'author_id', 'rating', 'is_recommended', 'helpfulness',
    'total_feedback_count', 'total_neg_feedback_count', 'total_pos_feedback_count',
    'submission_time', 'review_title', 'skin_tone', 'eye_color', 'skin_type',
    'hair_color', 'product_id', 'product_name', 'brand_name', 'price_usd',
]

REVIEWER_ATTRS = ['skin_tone', 'skin_type', 'eye_color', 'hair_color']

# Per D8: everything up to this date is the full load, everything from it is the
# incremental batch held back for the watermark demo.
INCREMENTAL_CUTOFF = '2023-01-01'


def review_files():
    """The five review CSVs, in a stable order."""
    return sorted(glob.glob(os.path.join(FOLDER, 'reviews_*.csv')))


def load_products():
    """Load product_info.csv."""
    return pd.read_csv(os.path.join(FOLDER, 'product_info.csv'))


def load_reviews(cols=None):
    """Load and concatenate all five review CSVs.

    The unnamed first column is the CSV row index; it is named source_row_id
    here because it forms half of the fact table's idempotency key (see D13).
    """
    cols = cols or REVIEW_COLS
    frames = []
    for path in review_files():
        df = pd.read_csv(
            path,
            usecols=lambda c: c in cols or c.startswith('Unnamed'),
            dtype={'author_id': str, 'product_id': str},
        )
        df = df.rename(columns={df.columns[0]: 'source_row_id'})
        df['source_file'] = os.path.basename(path)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def parse_highlights(value):
    """highlights is a stringified Python list — return it as a real list."""
    try:
        return ast.literal_eval(value) if isinstance(value, str) else []
    except (ValueError, SyntaxError):
        return []


def row_counts():
    """Print row/column counts for every source file."""
    print('--- row counts ---')
    products = load_products()
    print(f'product_info.csv: {products.shape[0]} rows, {products.shape[1]} columns')
    total = 0
    for path in review_files():
        df = pd.read_csv(path, usecols=['product_id'])
        total += len(df)
        print(f'{os.path.basename(path)}: {len(df)} rows')
    print(f'reviews total: {total} rows')


def explore_products():
    """Columns, nulls, duplicates and category shape of product_info.csv."""
    df = load_products()
    print('--- product_info.csv ---')
    print(df.columns.tolist())
    print(df.head())
    print('Null counts per column:')
    print(df.isna().sum())
    print(f"\nDuplicate product_id: {df['product_id'].duplicated().sum()}")
    print(f"Brands: {df['brand_id'].nunique()} brand_id, {df['brand_name'].nunique()} brand_name")
    print("brand_id -> brand_name is 1:1:",
          df.groupby('brand_id')['brand_name'].nunique().max() == 1)
    print('\n--- primary_category ---')
    print(df['primary_category'].value_counts())
    print(f"\nprice_usd range: {df['price_usd'].min()} to {df['price_usd'].max()}")
    print(f"price_usd <= 0: {(df['price_usd'] <= 0).sum()}")
    print(f"sale_price_usd > price_usd: {(df['sale_price_usd'] > df['price_usd']).sum()}")
    print(f"rating outside 1-5: {((df['rating'] < 1) | (df['rating'] > 5)).sum()}")
    return df


def explore_reviews():
    """Columns, nulls, rating spread and date range across the five review files."""
    df = load_reviews()
    print('--- reviews (all five files) ---')
    print(df.columns.tolist())
    print(df.head())
    print('Null counts per column:')
    print(df.isna().sum())
    print(f"\nDistinct authors: {df['author_id'].nunique()}")
    print(f"Distinct products reviewed: {df['product_id'].nunique()}")

    ts = pd.to_datetime(df['submission_time'], errors='coerce')
    print(f"\nsubmission_time range: {ts.min()} to {ts.max()}")
    print(f'Unparseable dates: {ts.isna().sum()}')
    print('\n--- reviews by year ---')
    print(ts.dt.year.value_counts().sort_index())
    print('\n--- rating distribution ---')
    print(df['rating'].value_counts().sort_index())
    return df


def explore_review_text():
    """Length profile of review_text — the column excluded from REVIEW_COLS.

    Per D6 the text stays in the OLTP layer only; the warehouse stores
    review_length instead. This confirms the size that decision is based on.
    """
    print('--- review_text ---')
    lengths = []
    missing = 0
    for path in review_files():
        col = pd.read_csv(path, usecols=['review_text'])['review_text']
        missing += int(col.isna().sum())
        lengths.append(col.dropna().str.len())
    lengths = pd.concat(lengths, ignore_index=True)
    total_mb = lengths.sum() / 1_000_000
    print(f'Reviews with no text: {missing}')
    print(f'Length — min {lengths.min()}, median {int(lengths.median())}, '
          f'mean {lengths.mean():.0f}, max {lengths.max()}')
    print(f'Total text volume: {total_mb:.0f} MB')


def check_duplicates():
    """Duplicate reviews — and why the dedup key must include the date (D4)."""
    df = load_reviews(cols=['author_id', 'product_id', 'submission_time'])
    print('--- duplicate reviews ---')
    pair = df.duplicated(subset=['author_id', 'product_id']).sum()
    triple = df.duplicated(subset=['author_id', 'product_id', 'submission_time']).sum()
    print(f'Duplicates on (author_id, product_id):                   {pair}')
    print(f'Duplicates on (author_id, product_id, submission_time):  {triple}')
    print(f'Difference (same author + product, different dates):     {pair - triple}')
    print('-> dedup on the triple; the difference is legitimate re-reviews,')
    print('   so deduplicating on the pair would delete real data.')


def check_referential_integrity():
    """Confirm every review points at a product that exists (no orphans)."""
    products = set(load_products()['product_id'])
    reviews = load_reviews(cols=['product_id'])
    orphan = ~reviews['product_id'].isin(products)
    print('--- reviews -> products referential integrity ---')
    print(f'Product IDs in product_info: {len(products)}')
    print(f'Distinct product IDs in reviews: {reviews["product_id"].nunique()}')
    print(f'Orphan review rows: {orphan.sum()}')


def check_idempotency_key():
    """Is UNIQUE(source_row_id, product_id) actually unique across all 5 files? (D13)

    The CSV row index restarts at 0 in every file, which looks like a collision
    risk — worth testing rather than assuming.
    """
    df = load_reviews(cols=['product_id'])
    print('--- idempotency key check ---')
    print('source_row_id range per file:')
    for name, group in df.groupby('source_file'):
        print(f'  {name:24s} {group["source_row_id"].min()} .. {group["source_row_id"].max()}')
    dup = df.duplicated(subset=['source_row_id', 'product_id']).sum()
    print(f'\nDuplicate (source_row_id, product_id) pairs: {dup}')
    print('-> each product appears in exactly one file (the files are split by')
    print('   product range), so the pair cannot collide.')


def check_reviewer_profile_consistency():
    """Do reviewer attributes belong to the author or to the review? (D2)

    This is the check that rules out holding skin_tone/skin_type/eye_color/
    hair_color as attributes of a customer dimension.
    """
    df = load_reviews(cols=['author_id'] + REVIEWER_ATTRS)
    print('--- reviewer attribute consistency per author ---')
    inconsistent = pd.Series(False, index=df['author_id'].unique())
    for col in REVIEWER_ATTRS:
        per_author = df.groupby('author_id')[col].nunique()
        bad = per_author[per_author > 1]
        print(f'  {col:11s}: {len(bad):>6} authors with >1 distinct value '
              f'(max {per_author.max()})')
        inconsistent |= per_author.reindex(inconsistent.index).fillna(0).gt(1)

    n_bad = int(inconsistent.sum())
    n_authors = df['author_id'].nunique()
    affected = int(df['author_id'].isin(inconsistent[inconsistent].index).sum())
    print(f'\nAuthors total: {n_authors}')
    print(f'Authors whose profile is NOT constant: {n_bad} ({n_bad / n_authors:.2%})')
    print(f'Reviews written by those authors: {affected} ({affected / len(df):.2%})')

    combos = df[REVIEWER_ATTRS].fillna('Unknown').drop_duplicates()
    possible = 1
    for col in REVIEWER_ATTRS:
        possible *= df[col].fillna('Unknown').nunique()
    print(f'\nDistinct four-attribute combinations present: {len(combos)} of {possible} possible')
    print('-> attributes belong to the review, not the author. Held in a junk')
    print('   dimension (dim_reviewer_profile); dim_customer keeps identity only.')


def check_attribute_values():
    """List the actual values of each reviewer attribute — casing/sentinel defects."""
    df = load_reviews(cols=REVIEWER_ATTRS)
    print('--- reviewer attribute values ---')
    for col in REVIEWER_ATTRS:
        values = sorted(df[col].dropna().unique())
        print(f'  {col:11s} ({len(values)}): {values}')
    print("\n-> eye_color holds both 'Grey' and 'gray' — same colour, two values.")
    print("-> skin_tone holds 'notSureST', a placeholder rather than a skin tone.")
    print('   Both are normalised in clean.py.')


def check_category_hierarchy():
    """Is primary -> secondary -> tertiary a real hierarchy? (D1)"""
    df = load_products()
    print('--- category hierarchy ---')
    print(f"primary:   {df['primary_category'].nunique()}")
    print(f"secondary: {df['secondary_category'].nunique()}")
    print(f"tertiary:  {df['tertiary_category'].nunique()}")
    triples = df[['primary_category', 'secondary_category', 'tertiary_category']].drop_duplicates()
    print(f'Distinct (primary, secondary, tertiary) triples: {len(triples)}')

    per_secondary = df.groupby('secondary_category')['primary_category'].nunique()
    print(f'\nMax distinct primaries for one secondary_category: {per_secondary.max()}')
    print('Secondary categories appearing under more than one primary:')
    print(per_secondary[per_secondary > 1].sort_values(ascending=False).head(10))
    print('\n-> not a clean hierarchy, so category is keyed on the full triple')
    print('   rather than modelled as nested levels.')


def check_helpfulness():
    """Is helpfulness missing, or undefined? (D5)"""
    df = load_reviews(cols=['helpfulness', 'total_feedback_count',
                            'total_pos_feedback_count', 'total_neg_feedback_count'])
    print('--- helpfulness ---')
    no_feedback = df['total_feedback_count'] == 0
    print(f'Rows with total_feedback_count = 0: {no_feedback.sum()}')
    print(f'Rows with helpfulness NULL:         {df["helpfulness"].isna().sum()}')
    print(f'Rows where the two disagree:        {(no_feedback != df["helpfulness"].isna()).sum()}')
    mismatch = (df['total_pos_feedback_count'] + df['total_neg_feedback_count']
                != df['total_feedback_count']).sum()
    print(f'Rows where pos + neg != total:      {mismatch}')
    print('\n-> helpfulness is NULL exactly when nobody voted. It is undefined,')
    print('   not missing, so it is never imputed.')


def check_redundant_review_columns():
    """product_name / brand_name / price_usd are repeated on every review row."""
    products = load_products()[['product_id', 'product_name', 'brand_name', 'price_usd']]
    reviews = load_reviews(cols=['product_id', 'product_name', 'brand_name', 'price_usd'])
    merged = reviews.drop_duplicates('product_id').merge(
        products, on='product_id', how='left', suffixes=('_review', '_product'))
    print('--- redundant columns on the review rows ---')
    print(f'Products compared: {len(merged)}')
    for col in ['product_name', 'brand_name', 'price_usd']:
        diff = (merged[f'{col}_review'] != merged[f'{col}_product']).sum()
        print(f'  {col:13s} disagreements: {diff}')
    print('\n-> they agree completely with product_info.csv, so they are dropped')
    print('   at the staging boundary rather than stored twice.')


def explore_highlights():
    """Profile the highlights column before descoping it (D3).

    The column is a genuine many-to-many and would need its own table plus a
    bridge. It is cut for scope — this function is what makes that a measured
    decision rather than an oversight, so it stays in the script.
    """
    df = load_products()
    df['highlight_list'] = df['highlights'].map(parse_highlights)
    df['highlight_count'] = df['highlight_list'].map(len)

    counts = Counter(tag for tags in df['highlight_list'] for tag in tags)
    print('--- highlights ---')
    print(f'Products with no highlights: {(df["highlight_count"] == 0).sum()}')
    print(f'Distinct highlights: {len(counts)}')
    print(f'Mean per product (of those with any): '
          f'{df.loc[df["highlight_count"] > 0, "highlight_count"].mean():.1f}')
    print(f'Max per product: {df["highlight_count"].max()}')
    print(f'Total product-highlight pairs (bridge size if kept): {df["highlight_count"].sum()}')
    print('\nTop 15 highlights:')
    for tag, n in counts.most_common(15):
        print(f'  {n:5d}  {tag}')
    print('\n-> a cell holding several values breaks 1NF, so storing this would')
    print('   require a highlight table plus a product_highlight bridge.')
    print('   Evaluated and descoped for scope — see decision D3.')


def check_incremental_split():
    """Volume on each side of the full/incremental cutoff (D8)."""
    df = load_reviews(cols=['submission_time'])
    ts = pd.to_datetime(df['submission_time'], errors='coerce')
    cutoff = pd.Timestamp(INCREMENTAL_CUTOFF)
    print('--- full / incremental split ---')
    print(f'Cutoff: {INCREMENTAL_CUTOFF}')
    print(f'Full load (before cutoff):   {(ts < cutoff).sum()}')
    print(f'Incremental (from cutoff):   {(ts >= cutoff).sum()}')
    print('\nIncremental batch by month:')
    print(ts[ts >= cutoff].dt.to_period('M').value_counts().sort_index())
    print(f'\nRows with a non-midnight time component: '
          f'{(ts.dt.time != pd.Timestamp("00:00:00").time()).sum()}')
    print('-> no time component anywhere, so a date-grain key loses nothing.')


def main():
    # Uncomment the exploration(s) you want to run:

    row_counts()
    # explore_products()
    # explore_reviews()
    # explore_review_text()
    # check_duplicates()
    # check_referential_integrity()
    # check_idempotency_key()
    # check_reviewer_profile_consistency()
    # check_attribute_values()
    # check_category_hierarchy()
    # check_helpfulness()
    # check_redundant_review_columns()
    # explore_highlights()
    # check_incremental_split()


if __name__ == '__main__':
    main()
