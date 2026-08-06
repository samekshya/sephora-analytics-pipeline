-- Runs once, on first boot of an empty data volume, via
-- /docker-entrypoint-initdb.d. The postgres image creates POSTGRES_DB
-- (sephora_oltp) itself; the warehouse database has to be created here.
--
-- CREATE DATABASE cannot run inside a transaction block, which is why this is
-- its own file rather than part of the numbered migrations.

CREATE DATABASE sephora_dw;

COMMENT ON DATABASE sephora_dw IS
    'Star schema warehouse — dimensions, fact_reviews. Loaded from sephora_oltp by the etl package.';
