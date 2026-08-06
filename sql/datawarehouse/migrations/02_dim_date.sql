-- dim_date: generated calendar, one row per day.
--
-- date_key is an INTEGER in YYYYMMDD form rather than a DATE — the standard
-- Kimball convention (D12). It sorts and joins identically to a date while
-- being compact and unambiguous in the fact table.
--
-- The table is created here but POPULATED by etl/load.py::load_dim_date(),
-- which derives the range from MIN/MAX(submission_date) in the OLTP staging
-- layer with 30 days of padding either side. It cannot be seeded by a static
-- migration because staging lives in a different database (D7), and a
-- hardcoded range would silently go stale the moment newer reviews arrive.
CREATE TABLE IF NOT EXISTS dw.dim_date (
    date_key     INTEGER PRIMARY KEY,          -- YYYYMMDD
    full_date    DATE NOT NULL UNIQUE,
    year         INTEGER NOT NULL,
    quarter      INTEGER NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month        INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    month_name   VARCHAR(10) NOT NULL,
    week         INTEGER NOT NULL,
    day          INTEGER NOT NULL CHECK (day BETWEEN 1 AND 31),
    day_of_week  INTEGER NOT NULL CHECK (day_of_week BETWEEN 1 AND 7),
    day_name     VARCHAR(10) NOT NULL,
    is_weekend   BOOLEAN NOT NULL
);
