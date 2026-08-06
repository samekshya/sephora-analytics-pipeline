"""
ingest.py
---------
Loads data/processed/*.csv into the raw schema of sephora_oltp using COPY.

Script-based rather than a manual client import, so ingestion is repeatable
and auditable: the same command produces the same result, and the row counts
are logged rather than eyeballed.

COPY rather than INSERT because the review file is 1.09M rows / 547 MB —
row-by-row inserts would take orders of magnitude longer for no benefit.

Idempotent by truncate-and-reload inside a single transaction. The raw layer
is a landing zone for a full source export, not an incremental target, so
"load it again" should mean "make it match the file", not "append a second
copy". Incremental behaviour lives further downstream, in the warehouse load.
"""

import argparse
import logging
import os
from datetime import datetime

import psycopg2
from dotenv import load_dotenv

PROCESSED_DIR = os.path.join('data', 'processed')
LOG_DIR = 'logs'

# (table, csv file, expected row count after cleaning). The expected counts come
# from clean.py's own output and are asserted after load, so a partial COPY
# fails loudly instead of quietly under-loading.
TABLES = [
    ('raw.product_info', 'products.csv', 8494),
    ('raw.reviews', 'reviews.csv', 1093371),
]

os.makedirs(LOG_DIR, exist_ok=True)

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
log_filename = os.path.join(LOG_DIR, f'ingest_{timestamp}.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)s [%(filename)s:%(lineno)d] %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

load_dotenv()

OLTP_DB_CONFIG = dict(
    host=os.getenv('OLTP_DB_HOST'),
    port=os.getenv('OLTP_DB_PORT'),
    dbname=os.getenv('OLTP_DB_NAME'),
    user=os.getenv('OLTP_DB_USER'),
    password=os.getenv('OLTP_DB_PASSWORD'),
)


def parse_args():
    parser = argparse.ArgumentParser(description='Load processed CSVs into raw schema')
    parser.add_argument(
        '--skip-truncate',
        action='store_true',
        help='Append instead of truncating first (only useful for debugging a partial load)',
    )
    return parser.parse_args()


def copy_table(conn, table, filename, truncate=True):
    """COPY one CSV into one raw table. Returns the loaded row count."""
    path = os.path.join(PROCESSED_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f'{path} not found — run clean.py first')

    size_mb = os.path.getsize(path) / 1_000_000
    logger.info(f'{table}: loading {filename} ({size_mb:.1f} MB)')

    with conn.cursor() as cur:
        if truncate:
            cur.execute(f'TRUNCATE {table} CASCADE')
            logger.info(f'{table}: truncated')

        # HEADER tells COPY to skip the header row; the CSV column order matches
        # the table definition, so no column list is needed.
        with open(path, 'r', encoding='utf-8', newline='') as f:
            cur.copy_expert(
                f"COPY {table} FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')",
                f,
            )
        cur.execute(f'SELECT count(*) FROM {table}')
        count = cur.fetchone()[0]

    logger.info(f'{table}: {count} rows loaded')
    return count


def main():
    args = parse_args()
    conn = psycopg2.connect(**OLTP_DB_CONFIG)
    try:
        loaded = {}
        for table, filename, expected in TABLES:
            count = copy_table(conn, table, filename, truncate=not args.skip_truncate)
            loaded[table] = count
            if count != expected:
                raise ValueError(
                    f'{table}: loaded {count} rows, expected {expected} — '
                    f'refusing to commit a partial load'
                )
            logger.info(f'{table}: row count matches expected ({expected})')

        conn.commit()
        logger.info('Committed')

        for table, count in loaded.items():
            logger.info(f'  {table}: {count} rows')
        logger.info(f'Done. Log written to {log_filename}')
    except Exception:
        conn.rollback()
        logger.exception('Ingest failed — rolled back, raw schema unchanged')
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
