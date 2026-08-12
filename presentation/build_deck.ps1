param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "output"),
    [string]$RenderDirectory = (Join-Path (Split-Path $PSScriptRoot -Parent) "tmp\presentation-render")
)

$ErrorActionPreference = "Stop"

function Get-Rgb([int]$Red, [int]$Green, [int]$Blue) {
    return $Red + (256 * $Green) + (65536 * $Blue)
}

$Color = @{
    Background = Get-Rgb 12 16 24
    Panel      = Get-Rgb 27 32 44
    PanelAlt   = Get-Rgb 36 42 57
    White      = Get-Rgb 247 248 250
    Muted      = Get-Rgb 174 184 199
    Coral      = Get-Rgb 255 75 75
    Cyan       = Get-Rgb 95 195 255
    Green      = Get-Rgb 45 194 107
    Yellow     = Get-Rgb 255 209 102
    DarkGreen  = Get-Rgb 18 92 63
}

$ppLayoutBlank = 12
$ppSaveAsOpenXMLPresentation = 24
$ppSaveAsPDF = 32
$msoFalse = 0
$msoTrue = -1
$msoTextOrientationHorizontal = 1
$msoShapeRectangle = 1
$msoShapeRoundedRectangle = 5
$msoShapeChevron = 52
$ppAlignLeft = 1
$ppAlignCenter = 2
$msoAnchorTop = 1
$msoAnchorMiddle = 3

function Add-Text {
    param(
        $Slide,
        [double]$Left,
        [double]$Top,
        [double]$Width,
        [double]$Height,
        [string]$Text,
        [double]$Size = 18,
        [int]$FontColor = $Color.White,
        [bool]$Bold = $false,
        [int]$Alignment = $ppAlignLeft,
        [int]$Vertical = $msoAnchorTop,
        [string]$Font = "Aptos"
    )

    $shape = $Slide.Shapes.AddTextbox(
        $msoTextOrientationHorizontal, $Left, $Top, $Width, $Height)
    $shape.Fill.Visible = $msoFalse
    $shape.Line.Visible = $msoFalse
    $shape.TextFrame.MarginLeft = 0
    $shape.TextFrame.MarginRight = 0
    $shape.TextFrame.MarginTop = 0
    $shape.TextFrame.MarginBottom = 0
    $shape.TextFrame.WordWrap = $msoTrue
    $shape.TextFrame.VerticalAnchor = $Vertical
    $range = $shape.TextFrame.TextRange
    $range.Text = $Text
    $range.Font.Name = $Font
    $range.Font.Size = $Size
    $range.Font.Bold = if ($Bold) { $msoTrue } else { $msoFalse }
    $range.Font.Color.RGB = $FontColor
    $range.ParagraphFormat.Alignment = $Alignment
    return $shape
}

function Add-Box {
    param(
        $Slide,
        [double]$Left,
        [double]$Top,
        [double]$Width,
        [double]$Height,
        [int]$FillColor = $Color.Panel,
        [int]$LineColor = $Color.PanelAlt,
        [double]$Radius = 0
    )

    $shapeType = if ($Radius -gt 0) { $msoShapeRoundedRectangle } else { $msoShapeRectangle }
    $shape = $Slide.Shapes.AddShape($shapeType, $Left, $Top, $Width, $Height)
    $shape.Fill.ForeColor.RGB = $FillColor
    $shape.Line.ForeColor.RGB = $LineColor
    $shape.Line.Weight = 1
    return $shape
}

function Add-LabelBox {
    param(
        $Slide,
        [double]$Left,
        [double]$Top,
        [double]$Width,
        [double]$Height,
        [string]$Title,
        [string]$Detail,
        [int]$Accent = $Color.Coral,
        [int]$FillColor = $Color.Panel
    )

    [void](Add-Box $Slide $Left $Top $Width $Height $FillColor $Color.PanelAlt 8)
    [void](Add-Box $Slide $Left $Top 5 $Height $Accent $Accent 0)
    [void](Add-Text $Slide ($Left + 16) ($Top + 10) ($Width - 26) 23 $Title 13 $Color.White $true)
    [void](Add-Text $Slide ($Left + 16) ($Top + 36) ($Width - 26) ($Height - 44) $Detail 10.5 $Color.Muted $false)
}

function Add-Kpi {
    param(
        $Slide,
        [double]$Left,
        [double]$Top,
        [double]$Width,
        [string]$Value,
        [string]$Label,
        [int]$Accent = $Color.Coral
    )

    [void](Add-Box $Slide $Left $Top $Width 78 $Color.Panel $Color.PanelAlt 7)
    [void](Add-Text $Slide ($Left + 12) ($Top + 10) ($Width - 24) 34 $Value 24 $Accent $true $ppAlignCenter $msoAnchorMiddle "Aptos Display")
    [void](Add-Text $Slide ($Left + 8) ($Top + 49) ($Width - 16) 18 $Label 10 $Color.Muted $false $ppAlignCenter)
}

function Add-Arrow {
    param($Slide, [double]$Left, [double]$Top, [double]$Width, [double]$Height)
    $arrow = $Slide.Shapes.AddShape($msoShapeChevron, $Left, $Top, $Width, $Height)
    $arrow.Fill.ForeColor.RGB = $Color.Coral
    $arrow.Line.Visible = $msoFalse
    return $arrow
}

function Add-Relation {
    param($Slide, [double]$X1, [double]$Y1, [double]$X2, [double]$Y2)
    $line = $Slide.Shapes.AddLine($X1, $Y1, $X2, $Y2)
    $line.Line.ForeColor.RGB = $Color.Coral
    $line.Line.Weight = 3
    return $line
}

function Add-PictureContain {
    param(
        $Slide,
        [string]$Path,
        [double]$Left,
        [double]$Top,
        [double]$Width,
        [double]$Height
    )

    Add-Type -AssemblyName System.Drawing
    $image = [System.Drawing.Image]::FromFile($Path)
    try {
        $scale = [Math]::Min($Width / $image.Width, $Height / $image.Height)
        $pictureWidth = $image.Width * $scale
        $pictureHeight = $image.Height * $scale
    }
    finally {
        $image.Dispose()
    }

    [void](Add-Box $Slide $Left $Top $Width $Height $Color.Panel $Color.PanelAlt 6)
    $picture = $Slide.Shapes.AddPicture(
        $Path, $msoFalse, $msoTrue,
        $Left + (($Width - $pictureWidth) / 2),
        $Top + (($Height - $pictureHeight) / 2),
        $pictureWidth, $pictureHeight)
    return $picture
}

function Add-SlideBase {
    param($Presentation, [string]$Title, [string]$Kicker, [int]$Number)

    $slide = $Presentation.Slides.Add($Presentation.Slides.Count + 1, $ppLayoutBlank)
    $slide.FollowMasterBackground = $msoFalse
    $slide.Background.Fill.ForeColor.RGB = $Color.Background
    [void](Add-Text $slide 44 22 860 18 $Kicker.ToUpperInvariant() 9.5 $Color.Coral $true)
    [void](Add-Text $slide 44 46 875 46 $Title 27 $Color.White $true $ppAlignLeft $msoAnchorTop "Aptos Display")
    [void](Add-Box $slide 44 96 72 3 $Color.Coral $Color.Coral 0)
    [void](Add-Text $slide 44 514 600 14 "Sephora Reviews Analytics Pipeline" 8.5 $Color.Muted)
    [void](Add-Text $slide 900 514 20 14 "$Number" 8.5 $Color.Muted $true $ppAlignCenter)
    return $slide
}

function Add-Notes {
    param($Slide, [string]$Notes)
    try {
        $placeholder = $Slide.NotesPage.Shapes.Placeholders.Item(2)
        $placeholder.TextFrame.TextRange.Text = $Notes
    }
    catch {
        Write-Warning "Could not embed notes for slide $($Slide.SlideIndex): $($_.Exception.Message)"
    }
}

function Add-MiniBar {
    param($Slide, [double]$Left, [double]$Top, [double]$Width, [string]$Label, [double]$Value, [double]$Minimum, [double]$Maximum, [int]$Accent)
    [void](Add-Text $Slide $Left $Top 92 18 $Label 10 $Color.Muted $false)
    [void](Add-Box $Slide ($Left + 92) ($Top + 3) $Width 11 $Color.PanelAlt $Color.PanelAlt 5)
    $filled = [Math]::Max(3, (($Value - $Minimum) / ($Maximum - $Minimum)) * $Width)
    [void](Add-Box $Slide ($Left + 92) ($Top + 3) $filled 11 $Accent $Accent 5)
    [void](Add-Text $Slide ($Left + 98 + $Width) ($Top - 1) 48 18 $Value.ToString("0.000") 10 $Color.White $true)
}

$RepoRoot = Split-Path $PSScriptRoot -Parent
$HistoricalShot = Join-Path $RepoRoot "docs\screenshots\airflow_historical_run.png"
$IncrementalShot = Join-Path $RepoRoot "docs\screenshots\airflow_incremental_run.png"
$OverviewShot = Join-Path $RepoRoot "docs\screenshots\streamlit_overview.png"
$AnalysisShot = Join-Path $RepoRoot "docs\screenshots\streamlit_analysis.png"

foreach ($required in @($HistoricalShot, $IncrementalShot, $OverviewShot, $AnalysisShot)) {
    if (-not (Test-Path $required)) {
        throw "Missing presentation asset: $required"
    }
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $RenderDirectory | Out-Null

$PowerPoint = New-Object -ComObject PowerPoint.Application
$PowerPoint.Visible = $msoTrue
$Presentation = $PowerPoint.Presentations.Add()
$Presentation.PageSetup.SlideWidth = 960
$Presentation.PageSetup.SlideHeight = 540

try {
    # Slide 1 - title
    $slide = $Presentation.Slides.Add(1, $ppLayoutBlank)
    $slide.FollowMasterBackground = $msoFalse
    $slide.Background.Fill.ForeColor.RGB = $Color.Background
    [void](Add-Box $slide 0 0 12 540 $Color.Coral $Color.Coral 0)
    [void](Add-Text $slide 62 55 820 22 "DATA ENGINEERING CAPSTONE | 2026" 11 $Color.Coral $true)
    [void](Add-Text $slide 62 100 760 100 "Sephora Reviews`nAnalytics Pipeline" 39 $Color.White $true $ppAlignLeft $msoAnchorTop "Aptos Display")
    [void](Add-Text $slide 62 216 760 58 "Raw CSVs -> clean data -> 3NF OLTP -> star schema -> Airflow -> live Streamlit" 17 $Color.Muted $false)
    Add-Kpi $slide 62 340 155 "1.09M" "warehouse facts" $Color.Coral
    Add-Kpi $slide 230 340 155 "15" "Airflow tasks" $Color.Cyan
    Add-Kpi $slide 398 340 155 "10" "analytics views" $Color.Yellow
    Add-Kpi $slide 566 340 155 "51" "passing tests" $Color.Green
    [void](Add-Text $slide 62 469 620 22 "Samekshya Baniya | PostgreSQL | Python | Airflow | Streamlit" 11 $Color.Muted)
    [void](Add-Text $slide 885 508 30 14 "1" 8.5 $Color.Muted $true $ppAlignCenter)
    Add-Notes $slide "0:40 - Introduce the complete pipeline and emphasize that every number in the deck is measured from live runs."

    # Slide 2 - source and cleaning
    $slide = Add-SlideBase $Presentation "Source data first; rules second" "01 | Explore and clean" 2
    [void](Add-Text $slide 44 112 872 36 "The catalogue and review stream arrive at different grains, so profiling drives the cleaning contract." 13 $Color.Muted)
    Add-Kpi $slide 44 164 164 "1,094,411" "raw reviews" $Color.Coral
    Add-Kpi $slide 220 164 164 "8,494" "catalogue products" $Color.Cyan
    Add-Kpi $slide 396 164 164 "503,216" "review authors" $Color.Yellow
    Add-Kpi $slide 572 164 164 "304" "brands" $Color.Green
    Add-Kpi $slide 748 164 168 "14" "profiling checks" $Color.Coral
    Add-LabelBox $slide 44 270 278 164 "Deduplicate at the right grain" "Remove 1,040 rows on (author, product, date). Keep 4,485 legitimate re-reviews that a coarser key would destroy." $Color.Coral
    Add-LabelBox $slide 341 270 278 164 "Standardize, do not invent" "Grey -> gray. notSureST -> Unknown at the staging boundary. Helpfulness nulls stay undefined when nobody voted." $Color.Cyan
    Add-LabelBox $slide 638 270 278 164 "Keep traceability" "Cleaning drops rows, never columns. Every source column reaches raw; scope trims happen explicitly at raw -> 3NF." $Color.Green
    [void](Add-Text $slide 44 456 872 30 "Result: 1,093,371 clean reviews - exactly the population reconciled through 3NF, staging, and the warehouse." 13 $Color.White $true $ppAlignCenter)
    Add-Notes $slide "0:50 - Explain the measured dedup key, two standardizations, and why cleaning does not drop columns."

    # Slide 3 - architecture
    $slide = Add-SlideBase $Presentation "A traceable path from files to decisions" "02 | End-to-end architecture" 3
    [void](Add-Text $slide 44 110 872 30 "Each layer has one job; the same Python package runs locally or under Airflow." 13 $Color.Muted)

    $flowTop = 176
    $boxWidth = 118
    $gap = 15
    $labels = @(
        @{ Title = "6 CSV files"; Detail = "raw source"; Accent = $Color.Coral },
        @{ Title = "clean.py"; Detail = "standardize + dedup"; Accent = $Color.Coral },
        @{ Title = "raw"; Detail = "1:1 mirror"; Accent = $Color.Cyan },
        @{ Title = "3NF"; Detail = "9 related tables"; Accent = $Color.Cyan },
        @{ Title = "staging"; Detail = "analytics-ready"; Accent = $Color.Cyan },
        @{ Title = "etl/"; Detail = "E | T | R | Q | L"; Accent = $Color.Yellow },
        @{ Title = "star schema"; Detail = "5 dims + fact"; Accent = $Color.Green }
    )
    for ($index = 0; $index -lt $labels.Count; $index++) {
        $left = 38 + ($index * ($boxWidth + $gap))
        Add-LabelBox $slide $left $flowTop $boxWidth 94 $labels[$index].Title $labels[$index].Detail $labels[$index].Accent
        if ($index -lt ($labels.Count - 1)) {
            [void](Add-Arrow $slide ($left + $boxWidth + 3) ($flowTop + 33) 22 27)
        }
    }

    Add-LabelBox $slide 92 326 222 116 "sephora_oltp" "PostgreSQL database`nraw -> 3NF -> staging`n0 row gap" $Color.Cyan
    Add-LabelBox $slide 369 326 222 116 "Two orchestrators" "pipeline.py for local runs`n16-task Airflow DAG`nfull | historical | incremental" $Color.Yellow
    Add-LabelBox $slide 646 326 222 116 "sephora_dw" "Star schema + 10 views`nStreamlit reads views only`nvalidation shares definitions" $Color.Green
    [void](Add-Text $slide 44 470 872 23 "Grain of fact_reviews: one row per review. PostgreSQL generates every surrogate key." 12.5 $Color.White $true $ppAlignCenter)
    Add-Notes $slide "1:05 - Walk left to right. Stress raw traceability, 3NF correctness, staging convenience, and the separate warehouse."

    # Slide 4 - model decision
    $slide = Add-SlideBase $Presentation "The profile belongs to the review" "03 | Dimensional modelling" 4
    [void](Add-Text $slide 44 110 872 34 "A one-row-per-author customer dimension would silently assign the wrong skin profile to roughly one review in seven." 13 $Color.Muted)

    Add-LabelBox $slide 369 213 224 112 "fact_reviews" "1,093,371 rows`none review per row`n4 foreign keys" $Color.Coral $Color.PanelAlt
    Add-LabelBox $slide 62 171 208 92 "dim_product" "8,494 products`nbrand + categories + price" $Color.Cyan
    Add-LabelBox $slide 62 315 208 92 "dim_date" "5,379 dates`nYYYYMMDD integer key" $Color.Cyan
    Add-LabelBox $slide 690 171 208 92 "dim_customer" "503,216 authors`nidentity only" $Color.Cyan
    Add-LabelBox $slide 690 315 208 92 "dim_reviewer_profile" "1,896 combinations`nskin | eye | hair" $Color.Yellow

    [void](Add-Relation $slide 270 217 369 269)
    [void](Add-Relation $slide 270 361 369 269)
    [void](Add-Relation $slide 593 269 690 217)
    [void](Add-Relation $slide 593 269 690 361)

    [void](Add-Text $slide 301 160 358 28 "D2 - measured before modelling" 12 $Color.Coral $true $ppAlignCenter)
    [void](Add-Text $slide 297 448 366 44 "22,503 authors changed profile attributes`n149,788 reviews affected | 13.69% of the dataset" 13 $Color.White $true $ppAlignCenter)
    Add-Notes $slide "1:10 - Defend the junk dimension with measured author variability. Explain that plausible-looking wrong joins are more dangerous than visible failures."

    # Slide 5 - ETL reliability
    $slide = Add-SlideBase $Presentation "Make silent data loss impossible" "04 | ETL, quality and incrementals" 5
    [void](Add-Text $slide 44 110 872 34 "The course reference structure is preserved, with reconciliation and severity-aware gates added where this dataset needs them." 13 $Color.Muted)

    $stageNames = @(
        @{ Name = "Extract"; Detail = "named SQL reads"; Color = $Color.Cyan },
        @{ Name = "Transform"; Detail = "resolve keys"; Color = $Color.Cyan },
        @{ Name = "Reconcile"; Detail = "count every drop"; Color = $Color.Yellow },
        @{ Name = "Quality"; Detail = "gate, not fixer"; Color = $Color.Coral },
        @{ Name = "Load"; Detail = "idempotent inserts"; Color = $Color.Green }
    )
    for ($index = 0; $index -lt $stageNames.Count; $index++) {
        $left = 54 + ($index * 179)
        Add-LabelBox $slide $left 176 145 92 $stageNames[$index].Name $stageNames[$index].Detail $stageNames[$index].Color
        if ($index -lt ($stageNames.Count - 1)) {
            [void](Add-Arrow $slide ($left + 149) 207 27 27)
        }
    }

    Add-LabelBox $slide 44 314 270 122 "full" "Every staged review`nNo date bound`nSafe re-run: conflicts insert 0" $Color.Cyan
    Add-LabelBox $slide 345 314 270 122 "historical" "Before 2023-01-01`n1,043,868-row demo baseline`n49,503 held back, not lost" $Color.Yellow
    Add-LabelBox $slide 646 314 270 122 "incremental" "Strictly after watermark`n2022-12-31 -> 2023-03-21`nEmpty batch is a clean no-op" $Color.Green
    [void](Add-Text $slide 44 460 872 30 "Hard failures stop before writes | warnings remain visible | ON CONFLICT DO NOTHING enforces idempotency" 12.5 $Color.White $true $ppAlignCenter)
    Add-Notes $slide "1:05 - Explain the five module boundaries, row accounting identity, quality severities, and the three honest mode names."

    # Slide 6 - Airflow evidence
    $slide = Add-SlideBase $Presentation "The DAG ran both paths successfully" "05 | Airflow orchestration" 6
    [void](Add-Text $slide 44 109 872 26 "Controlled verification on 12 Aug 2026 | 15 tasks | cleanup is a teardown, so a failed run cannot report success" 12.5 $Color.Muted)
    [void](Add-PictureContain $slide $HistoricalShot 44 151 419 284)
    [void](Add-PictureContain $slide $IncrementalShot 497 151 419 284)
    [void](Add-Text $slide 44 442 419 22 "Historical re-offer | SUCCESS | 134 seconds" 12 $Color.Yellow $true $ppAlignCenter)
    [void](Add-Text $slide 497 442 419 22 "Incremental restore | SUCCESS | 22 seconds" 12 $Color.Green $true $ppAlignCenter)
    [void](Add-Text $slide 44 476 872 24 "Deleted only the verified 2023 fact slice -> restored all 49,503 rows -> watermark returned to 2023-03-21." 11.5 $Color.White $true $ppAlignCenter)
    Add-Notes $slide "1:10 - Point to task states and durations. Historical was idempotent; incremental restored the controlled 2023 slice; all staging tables ended empty."

    # Slide 7 - dashboard insights
    $slide = Add-SlideBase $Presentation "The dashboard leads with decisions, not decoration" "06 | Analytics and Streamlit" 7
    [void](Add-Text $slide 44 109 872 26 "Live connection to sephora_dw - every figure re-queried on render, every control a SQL parameter" 12.5 $Color.Muted)
    [void](Add-PictureContain $slide $OverviewShot 44 151 419 284)
    [void](Add-PictureContain $slide $AnalysisShot 497 151 419 284)
    [void](Add-Text $slide 44 442 419 22 "Overview | KPIs and fifteen-year trend" 12 $Color.Cyan $true $ppAlignCenter)
    [void](Add-Text $slide 497 442 419 22 "Deep dive | hype, price and skin profile" 12 $Color.Coral $true $ppAlignCenter)
    [void](Add-Text $slide 44 470 872 30 "Price vs satisfaction is an inverted U: 4.238 under `$15 -> 4.334 at `$50-100 -> 4.271 above `$100, and rating spread narrows as price rises." 11.5 $Color.White $true $ppAlignCenter)
    Add-Notes $slide "1:25 - Present the price curve as the headline. Then explain hype, partial-month labelling, weak skin signals, and SQL-backed controls."

    # Slide 8 - conclusion
    $slide = Add-SlideBase $Presentation "A complete, reproducible capstone" "07 | Close and live demo" 8
    [void](Add-Text $slide 44 112 872 32 "The final state is measured, source-backed, and runnable from an empty Docker environment." 13 $Color.Muted)

    Add-Kpi $slide 44 166 196 "1,093,371" "facts = staging rows" $Color.Coral
    Add-Kpi $slide 254 166 196 "0" "orphan fact keys" $Color.Green
    Add-Kpi $slide 464 166 196 "0" "duplicate fact keys" $Color.Green
    Add-Kpi $slide 674 166 196 "51 + 11" "host tests + DAG asserts" $Color.Cyan

    Add-LabelBox $slide 44 287 410 154 "Live demo in four moves" "1. Show the successful incremental run`n2. Open the live Overview KPIs`n3. Move one Deep dive SQL control`n4. Reconcile views to fact_reviews" $Color.Coral
    Add-LabelBox $slide 506 287 410 154 "Where to verify it" "README.md - setup + diagrams`ndocs/ - decisions + evidence`ndashboard/ - app + metric model`nsql/validation/ - source-of-truth checks" $Color.Cyan
    [void](Add-Text $slide 44 466 872 29 "Questions?" 22 $Color.White $true $ppAlignCenter $msoAnchorMiddle "Aptos Display")
    Add-Notes $slide "0:35 - Close with the exact verified totals and give the four-step live demo route."

    $PptxPath = Join-Path $OutputDirectory "Sephora_Analytics_Pipeline.pptx"
    $PdfPath = Join-Path $OutputDirectory "Sephora_Analytics_Pipeline.pdf"
    $Presentation.SaveAs($PptxPath, $ppSaveAsOpenXMLPresentation)
    $Presentation.SaveAs($PdfPath, $ppSaveAsPDF)
    $Presentation.Export($RenderDirectory, "PNG", 1600, 900)

    Write-Output "Created: $PptxPath"
    Write-Output "Created: $PdfPath"
    Write-Output "Rendered slides: $RenderDirectory"
}
finally {
    $Presentation.Close()
    $PowerPoint.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($Presentation)
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($PowerPoint)
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
