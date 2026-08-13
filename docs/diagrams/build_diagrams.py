"""Generate the three project diagrams as standalone SVG files.

    py docs/diagrams/build_diagrams.py

Writes architecture.svg, oltp_er.svg and star_schema.svg beside this script.
They are used by README.md, docs/ and the HTML presentation, so they are
generated rather than hand-drawn: when a measured number in the checkpoint moves,
change it here once and re-run.

Every row count below is from docs/00_project_checkpoint.md section 7. Never put
an estimate in a diagram — a wrong number on a slide is worse than no number.
"""

from pathlib import Path

# --- palette -----------------------------------------------------------------
# Sephora's own identity is black, white and a single hot red. The diagrams stay
# on a light ground so they read on a projector, in a printed handout and on
# GitHub in either theme.
INK = "#17110F"   # near-black body text
MUTED = "#7C6F6A"   # secondary text
RED = "#D6001C"   # Sephora red — accents and primary keys only
RED_SOFT = "#FCEBEE"
LINE = "#E0D5D1"   # box borders and connectors
SOFT = "#FBF7F6"   # panel interior
WHITE = "#FFFFFF"
DARK = "#17110F"   # inverted blocks (fact table, Airflow band)
DARK_2 = "#2A211E"

SANS = "'Segoe UI','Helvetica Neue',Helvetica,Arial,sans-serif"
MONO = "'Cascadia Mono',Consolas,'SF Mono',Menlo,monospace"

# --- geometry ----------------------------------------------------------------
# Type is deliberately large relative to the canvas. These diagrams are shown
# on a projected slide at roughly 70% of their authored width, so a column name
# set at a comfortable 14px here arrives at the audience under 9px. Sizing up
# and carrying fewer rows is what makes them readable; a faithful dump of every
# column is not worth an unreadable slide.
HEADER_H = 52
ROW_H = 30
ROWS_TOP = 14
FOOT_H = 38
PAD_X = 20


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def txt(x, y, s, size=14, fill=INK, anchor="start", weight="400",
        family=SANS, spacing=None, style=None):
    extra = ""
    if spacing:
        extra += f' letter-spacing="{spacing}"'
    if style:
        extra += f' font-style="{style}"'
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
            f'fill="{fill}" text-anchor="{anchor}" font-weight="{weight}"{extra}>'
            f'{esc(s)}</text>')


def rect(x, y, w, h, fill=WHITE, stroke=LINE, r=14, sw=1.5, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" ry="{r}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')


def top_rounded(x, y, w, h, r, fill):
    """A rectangle with only its top two corners rounded — used for headers."""
    return (f'<path d="M{x},{y + h} L{x},{y + r} Q{x},{y} {x + r},{y} '
            f'L{x + w - r},{y} Q{x + w},{y} {x + w},{y + r} L{x + w},{y + h} Z" '
            f'fill="{fill}"/>')


def entity_height(fields):
    return HEADER_H + ROWS_TOP + ROW_H * len(fields) + FOOT_H


def entity(x, y, w, title, fields, footer, dark=False, note=None):
    """One table box: dark or light header, monospace field rows, a count footer.

    fields is a list of (column_name, badge) pairs; badge is '', 'PK', 'FK' or
    'UQ'. PK badges are red, everything else is muted — so the key structure is
    readable from the back of a room without reading a single column name.
    """
    h = entity_height(fields)
    head_fill = RED if dark else DARK
    body_fill = DARK_2 if dark else WHITE
    body_text = "#F5EFED" if dark else INK
    body_muted = "#B9A9A4" if dark else MUTED
    border = DARK_2 if dark else LINE

    out = [rect(x, y, w, h, fill=body_fill, stroke=border, r=14,
                sw=2 if dark else 1.5)]
    out.append(top_rounded(x, y, w, HEADER_H, 14, head_fill))
    out.append(txt(x + PAD_X, y + 34, title, size=19.5, fill=WHITE,
                   weight="600", family=MONO))

    ty = y + HEADER_H + ROWS_TOP + 19
    for name, badge in fields:
        out.append(txt(x + PAD_X, ty, name, size=16.5, family=MONO,
                       fill=body_text if badge == "PK" else body_muted,
                       weight="600" if badge == "PK" else "400"))
        if badge:
            colour = RED if badge == "PK" else body_muted
            out.append(txt(x + w - PAD_X, ty, badge, size=12.5, family=SANS,
                           fill=colour, anchor="end", weight="700",
                           spacing="0.6"))
        ty += ROW_H

    fy = y + h - 13
    out.append(f'<line x1="{x + PAD_X}" y1="{y + h - FOOT_H + 2}" '
               f'x2="{x + w - PAD_X}" y2="{y + h - FOOT_H + 2}" '
               f'stroke="{border}" stroke-width="1"/>')
    out.append(txt(x + PAD_X, fy, footer, size=14.5, fill=RED if not dark else "#FF6B7F",
                   weight="600"))
    if note:
        out.append(txt(x + w - PAD_X, fy, note, size=13, fill=body_muted,
                       anchor="end", style="italic"))
    return "\n".join(out), h


def defs():
    return f'''<defs>
  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
          markerHeight="7" orient="auto-start-reverse">
    <path d="M0,1 L9,5 L0,9 z" fill="{RED}"/>
  </marker>
  <marker id="arrow-light" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
          markerHeight="7" orient="auto-start-reverse">
    <path d="M0,1 L9,5 L0,9 z" fill="#F5EFED"/>
  </marker>
  <marker id="dot" viewBox="0 0 8 8" refX="4" refY="4" markerWidth="5"
          markerHeight="5">
    <circle cx="4" cy="4" r="3.4" fill="{RED}"/>
  </marker>
</defs>'''


def svg(width, height, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}" '
            f'font-family="{SANS}">\n'
            f'<rect width="{width}" height="{height}" fill="{WHITE}"/>\n'
            f'{defs()}\n{body}\n</svg>\n')


def link(x1, y1, x2, y2, one_at="start", n_at="end", light=False):
    """A relationship line carrying 1 / N cardinality labels at its two ends.

    Both labels are placed in the gap BETWEEN the two boxes, on the side the
    line actually travels — otherwise a right-to-left relationship drops its
    labels inside a box and lands them on top of an FK badge.
    """
    marker = "arrow-light" if light else "arrow"
    colour = "#8C7D78" if not light else "#6B5B56"
    out = [f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{colour}" '
           f'stroke-width="2" marker-end="url(#{marker})" marker-start="url(#dot)"/>']
    if abs(y2 - y1) < abs(x2 - x1):
        d = 1 if x2 > x1 else -1
        out.append(txt(x1 + 24 * d, y1 - 12, one_at, size=15, fill=RED,
                       weight="700", anchor="middle"))
        out.append(txt(x2 - 26 * d, y2 - 12, n_at, size=15, fill=RED,
                       weight="700", anchor="middle"))
    else:
        d = 1 if y2 > y1 else -1
        out.append(txt(x1 + 16, y1 + 24 * d, one_at, size=15, fill=RED,
                       weight="700", anchor="middle"))
        out.append(txt(x2 + 16, y2 - 16 * d, n_at, size=15, fill=RED,
                       weight="700", anchor="middle"))
    return "\n".join(out)


# =============================================================================
# 1. Architecture — raw CSV to OLTP to warehouse to dashboard
# =============================================================================
def architecture():
    W, H = 1840, 748
    panel_w, gap = 300, 170
    xs = [60]
    for _ in range(3):
        xs.append(xs[-1] + panel_w + gap)

    p_top, p_bot = 30, 476
    body = []

    panels = [
        ("SOURCE FILES", "#17110F", [
            ("product_info.csv", "8,494 rows × 27 columns", "one row per catalogue product"),
            ("reviews_*.csv  (5 files)", "1,094,411 rows", "one row per written review"),
            ("Kaggle, public dataset", "Sephora catalogue and", "skincare reviews, 2008–2023"),
        ], None, None),
        ("OLTP  ·  sephora_oltp", "#17110F", [
            ("raw", "1:1 mirror of the CSVs", "loaded by COPY, nothing dropped"),
            ("3nf", "9 tables, FKs enforced", "redundancy removed"),
            ("staging", "flattened, no review text", "the ETL's only read surface"),
        ], None, None),
        ("WAREHOUSE  ·  sephora_dw", "#17110F", [
            ("5 dimensions", "product · brand · customer", "reviewer profile · date"),
            ("fact_reviews", "1,093,371 rows", "grain: one row per review"),
            ("11 analytics views", "the dashboard's only", "read surface"),
        ], None, None),
        ("DASHBOARD  ·  Streamlit", "#17110F", [
            ("One page, live connection", "queries Postgres on every", "filter change"),
            ("5 business questions", "Q1-Q5, each backed", "by a named view"),
            ("4 query-bound controls", "filters are SQL parameters,", "not dataframe filters"),
        ], None, None),
    ]

    for i, (title, head, boxes, note1, note2) in enumerate(panels):
        x = xs[i]
        body.append(rect(x, p_top, panel_w, p_bot - p_top, fill=SOFT, stroke=LINE, r=16))
        body.append(top_rounded(x, p_top, panel_w, 46, 16, head))
        body.append(txt(x + panel_w / 2, p_top + 29, title, size=13.5, fill=WHITE,
                        anchor="middle", weight="700", spacing="1.1"))

        by = p_top + 68
        for name, l1, l2 in boxes:
            bh = 104 if len(boxes) == 2 else 108
            body.append(rect(x + 16, by, panel_w - 32, bh, fill=WHITE, stroke=LINE, r=10, sw=1.2))
            body.append(txt(x + 32, by + 32, name, size=14.5, family=MONO,
                            fill=INK, weight="600"))
            body.append(txt(x + 32, by + 58, l1, size=12.5, fill=MUTED))
            body.append(txt(x + 32, by + 79, l2, size=12.5, fill=MUTED))
            by += bh + 14
        if note1:
            body.append(txt(x + 32, by + 26, note1, size=12.5, fill=RED, weight="600"))
            body.append(txt(x + 32, by + 46, note2, size=12.5, fill=RED, weight="600"))

    # arrows between the four stages
    arrow_y = 268
    steps = [("clean.py  ·  ingest.py", "dedupe, normalise, COPY"),
             ("etl/ package", "extract → transform → load"),
             ("analytics views", "11 read-only SQL views")]
    for i, (top, sub) in enumerate(steps):
        x1 = xs[i] + panel_w + 14
        x2 = xs[i + 1] - 14
        cx = (x1 + x2) / 2
        body.append(f'<line x1="{x1}" y1="{arrow_y}" x2="{x2}" y2="{arrow_y}" '
                    f'stroke="{RED}" stroke-width="2.5" marker-end="url(#arrow)"/>')
        body.append(txt(cx, arrow_y - 20, top, size=14, fill=INK, anchor="middle",
                        weight="700"))
        body.append(txt(cx, arrow_y + 34, sub, size=12, fill=MUTED, anchor="middle"))

    # Airflow orchestration band
    band_y, band_h = 536, 168
    bx, bw = 60, W - 120
    body.append(rect(bx, band_y, bw, band_h, fill=DARK, stroke=DARK, r=16, sw=2))
    body.append(txt(bx + 26, band_y + 40, "APACHE AIRFLOW", size=14, fill=RED,
                    weight="700", spacing="1.6"))
    body.append(txt(bx + 200, band_y + 40,
                    "dags/sephora_dw_pipeline_staged.py  —  15 tasks, 21 edges  ·  "
                    "modes: full · historical · incremental (watermark)",
                    size=14, fill="#CBBCB7"))

    chips = ["create_staging", "extract dims", "load dims", "extract fact",
             "transform", "quality gate", "load fact", "cleanup (teardown)"]
    inner = bw - 52
    chip_gap = 26
    chip_w = (inner - chip_gap * (len(chips) - 1)) / len(chips)
    cy = band_y + 78
    for i, label in enumerate(chips):
        cx = bx + 26 + i * (chip_w + chip_gap)
        last = i == len(chips) - 1
        body.append(rect(cx, cy, chip_w, 52, fill="#221A17",
                         stroke=RED if last else "#453733", r=10, sw=1.5,
                         dash="5 4" if last else None))
        body.append(txt(cx + chip_w / 2, cy + 32, label, size=12.5,
                        fill="#F2E9E6" if not last else RED, anchor="middle",
                        weight="600", family=MONO))
        if not last:
            ax = cx + chip_w + 5
            body.append(f'<line x1="{ax}" y1="{cy + 26}" x2="{ax + chip_gap - 10}" '
                        f'y2="{cy + 26}" stroke="#6B5B56" stroke-width="2" '
                        f'marker-end="url(#arrow-light)"/>')

    body.append(txt(bx + 26, band_y + band_h - 16,
                    "cleanup is a teardown: it runs after failures so staging is never "
                    "stranded, and is excluded from run state so a failed run stays red (D24)",
                    size=12.5, fill="#9C8B85", style="italic"))

    return W, H, "\n".join(body)


# =============================================================================
# 2. OLTP entity relationship diagram (simplified for presentation + README)
# =============================================================================
def oltp_er():
    W, H = 1500, 900
    body = []

    # Simplified for presentation and README: the four reviewer-attribute
    # foreign keys collapse to one row, and the free-text columns to another.
    # The full column list is in sql/oltp/migrations/ — a slide needs the shape
    # of the model, not every field.
    brand_f = [("brand_id", "PK"), ("brand_name", "UQ")]
    cat_f = [("category_id", "PK"), ("primary_category", ""),
             ("secondary_category", ""), ("tertiary_category", "")]
    prod_f = [("product_id", "PK"), ("brand_id", "FK"), ("category_id", "FK"),
              ("product_name", ""), ("price_usd", ""), ("loves_count", ""),
              ("rating, size, flags", "")]
    rev_f = [("review_id", "PK"), ("source_row_id + product_id", "UQ"),
             ("author_id", "FK"), ("product_id", "FK"), ("submission_date", ""),
             ("rating, is_recommended", ""), ("helpfulness, feedback", ""),
             ("review_text, review_length", ""),
             ("4 reviewer attribute ids", "FK")]
    auth_f = [("author_id", "PK")]

    rev_h = entity_height(rev_f)
    rev_x, rev_y, rev_w = 790, 60, 330

    prod_h = entity_height(prod_f)
    prod_x, prod_y, prod_w = 420, 150, 290

    brand_h = entity_height(brand_f)
    brand_x, brand_y, brand_w = 60, 100, 270

    cat_h = entity_height(cat_f)
    cat_x, cat_y = 60, 330

    auth_h = entity_height(auth_f)
    auth_x, auth_y, auth_w = 1190, 150, 250

    s, _ = entity(brand_x, brand_y, brand_w, '3nf.brand', brand_f, "304 rows")
    body.append(s)
    s, _ = entity(cat_x, cat_y, brand_w, '3nf.category', cat_f, "174 rows",
                  note="UNIQUE on the triple (D1)")
    body.append(s)
    s, _ = entity(prod_x, prod_y, prod_w, '3nf.product', prod_f, "8,494 rows")
    body.append(s)
    s, _ = entity(rev_x, rev_y, rev_w, '3nf.review', rev_f, "1,093,371 rows")
    body.append(s)
    s, _ = entity(auth_x, auth_y, auth_w, '3nf.author', auth_f, "503,216 rows")
    body.append(s)
    body.append(txt(auth_x + PAD_X, auth_y + auth_h + 34,
                    "Identity only — no skin tone,", size=14.5, fill=MUTED))
    body.append(txt(auth_x + PAD_X, auth_y + auth_h + 57,
                    "type, eye or hair colour here.", size=14.5, fill=MUTED))
    body.append(txt(auth_x + PAD_X, auth_y + auth_h + 86,
                    "4.47% of authors changed at", size=14.5, fill=RED, weight="600"))
    body.append(txt(auth_x + PAD_X, auth_y + auth_h + 109,
                    "least one of them (D2).", size=14.5, fill=RED, weight="600"))

    # lookup group beneath review
    grp_w, grp_h = 460, 250
    grp_x = rev_x + rev_w / 2 - grp_w / 2
    grp_y = rev_y + rev_h + 108
    H = int(grp_y + grp_h + 60)
    body.append(rect(grp_x, grp_y, grp_w, grp_h, fill=SOFT, stroke=LINE, r=16,
                     sw=1.5, dash="7 6"))
    body.append(txt(grp_x + grp_w / 2, grp_y + 34, "REVIEWER ATTRIBUTE LOOKUPS",
                    size=13.5, fill=MUTED, anchor="middle", weight="700", spacing="1.2"))
    lookups = [("skin_tone", "13 values"), ("skin_type", "4 values"),
               ("eye_color", "5 values"), ("hair_color", "7 values")]
    lw, lh = 196, 78
    for i, (name, count) in enumerate(lookups):
        lx = grp_x + 22 + (i % 2) * (lw + 24)
        ly = grp_y + 54 + (i // 2) * (lh + 18)
        body.append(rect(lx, ly, lw, lh, fill=WHITE, stroke=LINE, r=10, sw=1.2))
        body.append(txt(lx + 16, ly + 33, name, size=16.5, family=MONO,
                        fill=INK, weight="600"))
        body.append(txt(lx + 16, ly + 58, count, size=13.5, fill=RED, weight="600"))

    # relationships
    body.append(link(brand_x + brand_w, brand_y + brand_h / 2,
                     prod_x, brand_y + brand_h / 2, "1", "N"))
    body.append(link(cat_x + brand_w, cat_y + cat_h / 2,
                     prod_x, cat_y + cat_h / 2, "1", "N"))
    body.append(link(prod_x + prod_w, prod_y + prod_h / 2,
                     rev_x, prod_y + prod_h / 2, "1", "N"))
    body.append(link(auth_x, auth_y + 40, rev_x + rev_w, auth_y + 40, "1", "N"))
    body.append(link(rev_x + rev_w / 2, rev_y + rev_h,
                     grp_x + grp_w / 2, grp_y, "N", "1"))
    body.append(txt(rev_x + rev_w / 2 + 38, (rev_y + rev_h + grp_y) / 2 + 5,
                    "4 nullable FKs — recorded per review, not per author",
                    size=14.5, fill=MUTED, anchor="start"))

    return W, H, "\n".join(body)


# =============================================================================
# 3. Warehouse star schema
# =============================================================================
def star_schema():
    W, H = 1440, 1167          # H is recomputed below once the stack is laid out
    body = []

    # Keys are listed individually because the join paths are the point of the
    # diagram; the measures are grouped, because their names are not.
    fact_f = [("review_key", "PK"), ("source_row_id + product_id", "UQ"),
              ("product_key", "FK"), ("customer_key", "FK"),
              ("reviewer_profile_key", "FK"), ("date_key", "FK"),
              ("rating, is_recommended", ""), ("helpfulness, feedback", ""),
              ("review_length, submission_date", "")]
    prod_f = [("product_key", "PK"), ("product_id", "UQ"), ("brand_key", "FK"),
              ("product_name", ""), ("primary_category", ""),
              ("secondary_category", ""), ("tertiary_category", ""),
              ("price_usd, price_band", ""), ("loves_count, flags", "")]
    brand_f = [("brand_key", "PK"), ("brand_id", "UQ"), ("brand_name", "")]
    cust_f = [("customer_key", "PK"), ("customer_id", "UQ")]
    prof_f = [("reviewer_profile_key", "PK"), ("skin_tone", ""), ("skin_type", ""),
              ("eye_color", ""), ("hair_color", "")]
    date_f = [("date_key", "PK"), ("full_date", "UQ"), ("year, quarter, month", ""),
              ("week, day_name, is_weekend", "")]

    # The vertical stack is laid out top-down with a fixed 120px gap between
    # boxes, so the 1/N labels on the customer and date links always have clear
    # air. Deriving the fact's y from the canvas height instead left the date
    # link 16px long, with the two labels sitting on top of each other.
    V_GAP = 100

    fact_w, fact_x = 380, 590
    fact_h = entity_height(fact_f)

    cust_w = 300
    cust_h = entity_height(cust_f)
    cust_x = fact_x + (fact_w - cust_w) / 2
    cust_y = 60

    fact_y = cust_y + cust_h + V_GAP

    date_w = 320
    date_h = entity_height(date_f)
    date_x = fact_x + (fact_w - date_w) / 2
    date_y = fact_y + fact_h + V_GAP

    H = date_y + date_h + 60

    # left arm: dim_brand -> dim_product -> fact
    prod_h = entity_height(prod_f)
    prod_w, prod_x = 300, 210
    prod_y = fact_y + (fact_h - prod_h) / 2
    brand_h = entity_height(brand_f)
    brand_w, brand_x = 240, 60
    brand_y = prod_y + prod_h + 74

    # right arm
    prof_w, prof_x = 300, 1080
    prof_h = entity_height(prof_f)
    prof_y = fact_y + (fact_h - prof_h) / 2

    s, _ = entity(fact_x, fact_y, fact_w, 'dw.fact_reviews', fact_f,
                  "1,093,371 rows", dark=True, note="one row per review")
    body.append(s)
    s, _ = entity(prod_x, prod_y, prod_w, 'dw.dim_product', prod_f, "8,494 rows")
    body.append(s)
    s, _ = entity(brand_x, brand_y, brand_w, 'dw.dim_brand', brand_f, "304 rows")
    body.append(s)
    s, _ = entity(cust_x, cust_y, cust_w, 'dw.dim_customer', cust_f, "503,216 rows",
                  note="identity only (D2)")
    body.append(s)
    s, _ = entity(prof_x, prof_y, prof_w, 'dw.dim_reviewer_profile', prof_f,
                  "1,896 rows", note="junk dimension")
    body.append(s)
    s, _ = entity(date_x, date_y, date_w, 'dw.dim_date', date_f, "5,379 rows",
                  note="date_key = YYYYMMDD (D12)")
    body.append(s)

    body.append(link(prod_x + prod_w, fact_y + fact_h / 2, fact_x,
                     fact_y + fact_h / 2, "1", "N"))
    body.append(link(prof_x, fact_y + fact_h / 2, fact_x + fact_w,
                     fact_y + fact_h / 2, "1", "N"))
    body.append(link(cust_x + cust_w / 2, cust_y + cust_h, fact_x + fact_w / 2,
                     fact_y, "1", "N"))
    body.append(link(date_x + date_w / 2, date_y, fact_x + fact_w / 2,
                     fact_y + fact_h, "1", "N"))
    body.append(link(brand_x + brand_w, brand_y + brand_h / 2,
                     prod_x + prod_w / 2, prod_y + prod_h, "1", "N"))

    # The D11 note lives in the empty top-left corner. Anchoring it to the
    # bottom of the canvas put it straight through dim_brand. It is set large
    # enough to survive being scaled down onto a slide — at the old 13px it was
    # legible in the PNG and illegible everywhere the diagram is actually shown.
    body.append(txt(60, 104, "No brand_key on the fact table",
                    size=20, fill=RED, weight="700"))
    for i, line in enumerate([
            "Brand is functionally determined by product,",
            "so it lives on dim_product only. A copy on",
            "fact_reviews would add no information and",
            "create a way for the two to disagree (D11)."]):
        body.append(txt(60, 142 + i * 27, line, size=17, fill=MUTED))

    return W, H, "\n".join(body)


def main():
    here = Path(__file__).resolve().parent
    for name, builder in (("architecture", architecture),
                          ("oltp_er", oltp_er),
                          ("star_schema", star_schema)):
        w, h, body = builder()
        path = here / f"{name}.svg"
        path.write_text(svg(w, h, body), encoding="utf-8")
        print(f"wrote {path.name}  ({w} x {h})")


if __name__ == "__main__":
    main()
