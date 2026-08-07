<#
.SYNOPSIS
    One-sequence setup for the Sephora reviews warehouse, on Windows.

.DESCRIPTION
    Runs the whole path from an empty machine to a validated warehouse:

        1.  check prerequisites (docker, python, .env, the raw CSVs)
        2.  start Postgres and wait for it to be healthy
        3.  create schemas and apply the raw DDL
        4.  clean the CSVs            (skipped if data/processed/ is current)
        5.  ingest into raw           (COPY)
        6.  apply the 3NF + staging migrations
        7.  apply the warehouse migrations and the analytics views
        8.  run pytest
        9.  start Airflow
       10.  (you trigger the DAG from the UI)
       11.  validate totals

    Every step is idempotent: migrations use IF NOT EXISTS, loads use
    ON CONFLICT DO NOTHING, and ingest truncates before COPY. Re-running the
    script is safe, and is the intended way to resume after a failure.

.PARAMETER Step
    Run a single step by number, e.g. -Step 8. Default runs 1-9 in order.

.PARAMETER SkipTests
    Skip pytest. Not recommended - it is the only thing that proves the load
    worked rather than merely finished.

.PARAMETER FromScratch
    Destroy the database volume first. Deletes both databases. Prompts.

.EXAMPLE
    .\setup.ps1
    .\setup.ps1 -Step 8
    .\setup.ps1 -FromScratch
#>

[CmdletBinding()]
param(
    [int]$Step = 0,
    [switch]$SkipTests,
    [switch]$FromScratch
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$PG        = "leapfrog_sephora_postgres"
$OLTP      = "sephora_oltp"
$DW        = "sephora_dw"
$PYTHON    = "py"          # the launcher; `python` is not on PATH on this box

function Write-Step($n, $text) {
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor Cyan
    Write-Host "  STEP $n : $text" -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor Cyan
}

function Write-Ok($text)   { Write-Host "  [OK]   $text" -ForegroundColor Green }
function Write-Info($text) { Write-Host "  [..]   $text" -ForegroundColor Gray }
function Write-Warn($text) { Write-Host "  [WARN] $text" -ForegroundColor Yellow }

function Should-Run($n) { return ($Step -eq 0) -or ($Step -eq $n) }

# Runs an external program and judges it by its EXIT CODE.
#
# Necessary because of a Windows PowerShell 5.1 behaviour: with
# $ErrorActionPreference = 'Stop', ANY output a native command writes to stderr
# is promoted to a terminating error - even when the command succeeded. pip
# printing "WARNING: scripts are installed in ... which is not on PATH" was
# enough to abort the whole script on a successful install.
#
# Exit code is the only thing that actually says whether a program worked, so
# that is what this checks. stderr is still shown; it just no longer kills the
# run on its own.
function Invoke-Native {
    param(
        [Parameter(Mandatory)][scriptblock]$Command,
        [Parameter(Mandatory)][string]$What
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Command 2>&1 | ForEach-Object { Write-Host "         $_" -ForegroundColor DarkGray }
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

# Runs a .sql file inside the postgres container. -v ON_ERROR_STOP=1 matters:
# without it psql reports success after a failed statement, and a migration
# that half-applied would look identical to one that worked.
function Invoke-Sql($database, $file) {
    Write-Info "applying $(Split-Path $file -Leaf) -> $database"
    $sql = Get-Content $file -Raw
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        # client-min-messages=warning suppresses the "relation already exists,
        # skipping" NOTICE that every IF NOT EXISTS emits on a re-run. Those
        # are the migrations behaving correctly, but psql writes them to
        # stderr, where PowerShell renders them in red as though something
        # broke. Real errors still stop the run via ON_ERROR_STOP.
        $sql | docker exec -i -e PGOPTIONS='--client-min-messages=warning' $PG `
            psql -U postgres -d $database -v ON_ERROR_STOP=1 -q
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($LASTEXITCODE -ne 0) { throw "psql failed applying $file" }
}

function Invoke-SqlQuery($database, $sql) {
    # SQL goes in on STDIN, not as a -c argument. The 3NF schema has to be
    # written "3nf" (it starts with a digit, so it must be quoted), and passing
    # that through PowerShell's argument parser into docker exec strips the
    # quotes - psql then sees an unquoted 3nf and rejects it. stdin sidesteps
    # argument parsing completely.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $result = $sql | docker exec -i $PG psql -U postgres -d $database -t -A
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($LASTEXITCODE -ne 0) { throw "psql query failed: $sql" }
    return ($result | Select-Object -First 1)
}


# ---------------------------------------------------------------------------
if (Should-Run 1) {
    Write-Step 1 "Prerequisites"

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "docker not found. Install Docker Desktop and start it."
    }
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker is installed but not running. Start Docker Desktop." }
    Write-Ok "docker is running"

    if (-not (Get-Command $PYTHON -ErrorAction SilentlyContinue)) {
        throw "'$PYTHON' not found. Install Python 3.13+."
    }
    Write-Ok "python: $(& $PYTHON --version)"

    if (-not (Test-Path ".env")) {
        Write-Warn ".env missing - copying .env.example (working local defaults)"
        Copy-Item ".env.example" ".env"
    }
    Write-Ok ".env present"

    $missing = @("product_info.csv") | Where-Object { -not (Test-Path "data/raw/$_") }
    $reviewFiles = @(Get-ChildItem "data/raw/reviews_*.csv" -ErrorAction SilentlyContinue)
    if ($missing -or $reviewFiles.Count -eq 0) {
        throw "Raw CSVs missing from data/raw/. See data/README.md for the Kaggle link and expected filenames."
    }
    Write-Ok "raw CSVs present ($($reviewFiles.Count) review files + product_info.csv)"

    Write-Info "installing python dependencies"
    Invoke-Native { & $PYTHON -m pip install -q -r requirements.txt -r requirements-dev.txt } "pip install"
    Write-Ok "dependencies installed"
}

# ---------------------------------------------------------------------------
if (Should-Run 2) {
    Write-Step 2 "Start Postgres"

    if ($FromScratch) {
        Write-Warn "-FromScratch will DELETE both databases ($OLTP and $DW)."
        $answer = Read-Host "  Type 'yes' to confirm"
        if ($answer -ne "yes") { throw "Aborted by user." }
        Invoke-Native { docker compose down -v } "docker compose down -v"
        Write-Ok "volume destroyed"
    }

    Invoke-Native { docker compose up -d } "docker compose up"

    Write-Info "waiting for postgres to report healthy"
    $deadline = (Get-Date).AddMinutes(2)
    do {
        Start-Sleep -Seconds 3
        $health = docker inspect $PG --format '{{.State.Health.Status}}' 2>$null
        if ((Get-Date) -gt $deadline) { throw "Postgres did not become healthy within 2 minutes." }
    } while ($health -ne "healthy")

    Write-Ok "postgres healthy on localhost:5434"
    Write-Ok "databases: $(Invoke-SqlQuery 'postgres' ""SELECT string_agg(datname, ', ') FROM pg_database WHERE datname LIKE 'sephora%'"")"
}

# ---------------------------------------------------------------------------
if (Should-Run 3) {
    Write-Step 3 "Create schemas and raw tables"

    # sql/init/ runs automatically on the container's FIRST boot only (it is
    # mounted at /docker-entrypoint-initdb.d), which is what creates
    # sephora_dw. The raw DDL is applied here because it must be re-appliable.
    Invoke-Sql $OLTP "sql/oltp/01_raw_schema.sql"

    $rawTables = Invoke-SqlQuery $OLTP "SELECT count(*) FROM information_schema.tables WHERE table_schema='raw'"
    Write-Ok "raw schema has $rawTables table(s)"
}

# ---------------------------------------------------------------------------
if (Should-Run 4) {
    Write-Step 4 "Clean the CSVs"

    # Skipped when the processed files are newer than the raw ones - cleaning
    # 1.09M rows takes ~25s and rerunning it unchanged proves nothing.
    $rawNewest = (Get-ChildItem "data/raw/*.csv" | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
    $processed = Get-ChildItem "data/processed/reviews.csv" -ErrorAction SilentlyContinue

    if ($processed -and $processed.LastWriteTime -gt $rawNewest) {
        Write-Ok "data/processed/ is newer than data/raw/ - skipping (delete data/processed/ to force)"
    } else {
        Invoke-Native { & $PYTHON clean.py } "clean.py"
        Write-Ok "cleaned -> data/processed/"
    }
}

# ---------------------------------------------------------------------------
if (Should-Run 5) {
    Write-Step 5 "Ingest into the raw schema"

    Invoke-Native { & $PYTHON ingest.py } "ingest.py"

    Write-Ok "raw.product_info: $(Invoke-SqlQuery $OLTP 'SELECT count(*) FROM raw.product_info') rows"
    Write-Ok "raw.reviews:      $(Invoke-SqlQuery $OLTP 'SELECT count(*) FROM raw.reviews') rows"
}

# ---------------------------------------------------------------------------
if (Should-Run 6) {
    Write-Step 6 "Apply 3NF and staging migrations"

    # Numbered and append-only, so name order IS apply order.
    Get-ChildItem "sql/oltp/migrations/*.sql" | Sort-Object Name |
        ForEach-Object { Invoke-Sql $OLTP $_.FullName }

    Write-Ok "3nf.review:      $(Invoke-SqlQuery $OLTP 'SELECT count(*) FROM ""3nf"".review') rows"
    Write-Ok "staging.review:  $(Invoke-SqlQuery $OLTP 'SELECT count(*) FROM staging.review') rows"
    Write-Ok "staging.product: $(Invoke-SqlQuery $OLTP 'SELECT count(*) FROM staging.product') rows"
}

# ---------------------------------------------------------------------------
if (Should-Run 7) {
    Write-Step 7 "Apply warehouse migrations and analytics views"

    Get-ChildItem "sql/datawarehouse/migrations/*.sql" | Sort-Object Name |
        ForEach-Object { Invoke-Sql $DW $_.FullName }

    Get-ChildItem "sql/analytics/views/*.sql" | Sort-Object Name |
        ForEach-Object { Invoke-Sql $DW $_.FullName }

    $views = Invoke-SqlQuery $DW "SELECT count(*) FROM information_schema.views WHERE table_schema='dw'"
    Write-Ok "dw schema ready, $views view(s) created"
    Write-Warn "Dimensions and facts are NOT loaded yet - that is the DAG's job (step 10)."
    Write-Info "To load without Airflow: $PYTHON pipeline.py --mode historical"
}

# ---------------------------------------------------------------------------
if ((Should-Run 8) -and -not $SkipTests) {
    Write-Step 8 "Run the test suite"

    # Integration tests skip themselves if the warehouse is empty, so this is
    # meaningful before the DAG has run and more meaningful after.
    Invoke-Native { & $PYTHON -m pytest -q } "pytest"
    Write-Ok "tests passed"
}

# ---------------------------------------------------------------------------
if (Should-Run 9) {
    Write-Step 9 "Start Airflow"

    Invoke-Native { docker compose -f docker-compose-airflow.yml up -d } "airflow compose up"

    Write-Info "waiting for the API server"
    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 5
        try {
            $r = Invoke-WebRequest "http://localhost:8081/api/v2/monitor/health" -TimeoutSec 5 -UseBasicParsing
            $up = ($r.StatusCode -eq 200)
        } catch { $up = $false }
        if ((Get-Date) -gt $deadline) { throw "Airflow did not come up within 3 minutes. Check: docker compose -f docker-compose-airflow.yml logs" }
    } while (-not $up)

    Write-Ok "Airflow is up at http://localhost:8081"
}

# ---------------------------------------------------------------------------
if (Should-Run 10) {
    Write-Step 10 "Trigger the DAG (manual)"
    Write-Host @"
  Open http://localhost:8081 and trigger 'sephora_dw_pipeline_staged' twice:

    1. Trigger with load_mode = historical
       -> loads reviews before 2023-01-01 (the demo baseline)

    2. Trigger with load_mode = incremental
       -> picks up the held-back 2023 rows using the watermark

  Watching those two runs in order is the point of the demo: the second one
  proves the watermark works on real data rather than on a story.

  Then run:  .\setup.ps1 -Step 11
"@ -ForegroundColor White
}

# ---------------------------------------------------------------------------
if (Should-Run 11) {
    Write-Step 11 "Validate totals"

    Get-Content "sql/validation/dashboard_checks.sql" -Raw |
        docker exec -i $PG psql -U postgres -d $DW -q

    Write-Host ""
    Write-Ok "Every view above must show diff_from_fact = 0."
    Write-Info "Launch the dashboard: $PYTHON -m streamlit run dashboard/app.py"
}

# ---------------------------------------------------------------------------
if ($Step -eq 0) {
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor Green
    Write-Host "  Setup complete through step 9." -ForegroundColor Green
    Write-Host ("=" * 72) -ForegroundColor Green
    Write-Host @"

  Next:
    1. Trigger the DAG twice (historical, then incremental) at
       http://localhost:8081          -  see .\setup.ps1 -Step 10
    2. Validate:    .\setup.ps1 -Step 11
    3. Dashboard:   $PYTHON -m streamlit run dashboard/app.py

"@ -ForegroundColor White
}
