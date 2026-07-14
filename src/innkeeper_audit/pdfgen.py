"""Render the OTA partner statement as a REAL PDF (reportlab), with the three
real-world hazards from SEED_DATA.md planted deterministically:

  H1  8-pt table text (the whole table renders at 8 pt);
  H2  a footnote asterisk that changes a total (promo co-funding -$12.00,
      applied to one line AND to the statement's Total Payout row);
  H3  one page-broken row (gross/commission at the bottom of one page, the
      payout cell carried to the top of the next page).

The renderer also emits a *sidecar* JSON with the true value and the exact
bounding box (PDF points, y-up) of every rendered line. The sidecar is the
FakeQwen extraction fixture (keyed to the PDF by sha256) and doubles as the
layout ground truth for bbox tests. Canvas(invariant=1) makes the PDF bytes
byte-identical across --regen runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as rl_canvas

PAGE_W, PAGE_H = letter  # 612 x 792 pt
MARGIN_L, MARGIN_R = 40, 572
ROW_H = 11
FONT, FONT_SIZE = "Helvetica", 8  # hazard H1: 8-pt table text
ROWS_PER_PAGE = 44

# column x positions: (label, x, right_align)
COLS = [
    ("#", 40, False),
    ("NIGHT", 62, False),
    ("FOLIO", 112, False),
    ("GUEST", 210, False),
    ("ROOM", 330, False),
    ("GROSS", 420, True),
    ("COMM 3%", 486, True),
    ("PAYOUT", 566, True),
]

FOOTNOTE_TEXT = "* less promotional co-funding $12.00 (July Getaway campaign)"


def _header(c: rl_canvas.Canvas, month: str, page: int) -> float:
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN_L, 752, "SUNWAY TRAVEL — PARTNER SETTLEMENT STATEMENT")
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN_L, 740, f"Property 88231 · The Larkspur Inn · Period {month} · Page {page}")
    c.setFont("Helvetica-Bold", FONT_SIZE)
    y = 718.0
    for label, x, right in COLS:
        if right:
            c.drawRightString(x, y, label)
        else:
            c.drawString(x, y, label)
    c.line(MARGIN_L, y - 3, MARGIN_R, y - 3)
    c.setFont(FONT, FONT_SIZE)
    return y - ROW_H - 2


def _row_cells(line: dict[str, Any]) -> list[str]:
    return [
        str(line["line_no"]),
        line["night"][5:],  # MM-DD
        line["folio"],
        str(line["guest"])[:20],
        str(line["room"]),
        f"{line['gross']:.2f}",
        f"{line['commission']:.2f}",
        f"{line['payout']:.2f}" + ("*" if line.get("footnote_adjustment") else ""),
    ]


def _draw_cells(c: rl_canvas.Canvas, y: float, cells: list[str], skip: set[int] = frozenset()) -> None:
    for i, ((_, x, right), text) in enumerate(zip(COLS, cells)):
        if i in skip:
            continue
        if right:
            c.drawRightString(x, y, text)
        else:
            c.drawString(x, y, text)


def render_statement(
    month: str,
    lines: list[dict[str, Any]],
    totals: dict[str, float],
    out_pdf: Path,
) -> dict[str, Any]:
    """Render lines (dicts with line_no/night/folio/guest/room/gross/commission/
    payout/footnote_adjustment/hazard) to out_pdf. Returns the sidecar dict
    (pdf_sha256 left empty; caller fills it after hashing the file).
    """
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    # invariant=1 (constructor) fixes the CreationDate + document ID at doc init
    # => byte-identical PDF across --regen. Setting it post-construction is too
    # late: the random document ID is already seeded.
    c = rl_canvas.Canvas(str(out_pdf), pagesize=letter, pageCompression=0, invariant=1)
    c.setProducer("innkeeper-audit seed generator")
    c.setTitle(f"Sunway Travel partner statement {month}")
    c._doc.invariant = 1

    sidecar_lines: list[dict[str, Any]] = []
    page = 1
    y = _header(c, month, page)
    rows_on_page = 0
    footnote_pages: set[int] = set()

    def new_page() -> tuple[float, int]:
        nonlocal page, rows_on_page
        if page in footnote_pages:
            c.setFont(FONT, FONT_SIZE - 1)
            c.drawString(MARGIN_L, 48, FOOTNOTE_TEXT)
            c.setFont(FONT, FONT_SIZE)
        c.showPage()
        page += 1
        rows_on_page = 0
        return _header(c, month, page), page

    i = 0
    while i < len(lines):
        line = lines[i]
        cells = _row_cells(line)
        page_broken = line.get("hazard") == "page_broken"
        if rows_on_page >= ROWS_PER_PAGE:
            y, _ = new_page()

        if page_broken:
            # hazard H3: draw everything except PAYOUT, then carry the payout
            # cell to the top of the next page.
            _draw_cells(c, y, cells, skip={7})
            c.drawRightString(COLS[7][1], y, "→")
            bbox_head = [MARGIN_L, round(y - 2, 2), MARGIN_R, round(y + 8, 2)]
            head_page = page
            y, _ = new_page()
            c.drawString(COLS[2][1], y, f"(cont'd) {line['folio']}")
            c.drawRightString(COLS[7][1], y, cells[7])
            bbox_cont = [MARGIN_L, round(y - 2, 2), MARGIN_R, round(y + 8, 2)]
            sidecar_lines.append(
                {
                    **_sidecar_entry(line, head_page, bbox_head),
                    "cont_page": page,
                    "cont_bbox": bbox_cont,
                }
            )
        else:
            _draw_cells(c, y, cells)
            if line.get("footnote_adjustment"):
                footnote_pages.add(page)  # hazard H2 footnote on this page
            sidecar_lines.append(
                _sidecar_entry(line, page, [MARGIN_L, round(y - 2, 2), MARGIN_R, round(y + 8, 2)])
            )
        y -= ROW_H
        rows_on_page += 1
        i += 1

    # totals block (hazard H2: the printed total includes the * adjustment,
    # so a naive sum of gross x 0.97 over-counts by $12.00)
    if rows_on_page > ROWS_PER_PAGE - 6:
        y, _ = new_page()
    y -= ROW_H
    c.line(MARGIN_L, y + 8, MARGIN_R, y + 8)
    c.setFont("Helvetica-Bold", FONT_SIZE)
    for label, value in [
        ("TOTAL GROSS", totals["gross"]),
        ("TOTAL COMMISSION (3%)", totals["commission"]),
        ("ADJUSTMENTS *", -totals["adjustments"]),
        ("TOTAL PAYOUT", totals["payout"]),
    ]:
        c.drawString(COLS[3][1], y, label)
        c.drawRightString(COLS[7][1], y, f"{value:.2f}")
        y -= ROW_H
    if page in footnote_pages or totals["adjustments"]:
        c.setFont(FONT, FONT_SIZE - 1)
        c.drawString(MARGIN_L, 48, FOOTNOTE_TEXT)
    c.showPage()
    c.save()

    return {
        "month": month,
        "pdf_sha256": "",
        "generator": "innkeeper-audit/pdfgen invariant=1",
        "pages": page,
        "font_pt": FONT_SIZE,
        "totals": totals,
        "lines": sidecar_lines,
    }


def _sidecar_entry(line: dict[str, Any], page: int, bbox: list[float]) -> dict[str, Any]:
    return {
        "line_no": line["line_no"],
        "night": line["night"],
        "folio": line["folio"],
        "guest": line["guest"],
        "room": line["room"],
        "gross": line["gross"],
        "commission": line["commission"],
        "payout": line["payout"],
        "footnote_adjustment": line.get("footnote_adjustment", 0.0),
        "footnote_text": FOOTNOTE_TEXT if line.get("footnote_adjustment") else None,
        "hazard": line.get("hazard"),
        # FakeQwen pass-B value: differs only on the planted page-broken row,
        # which is exactly the two-pass disagreement that must escalate (I5).
        "pass_b_payout": line.get("pass_b_payout", line["payout"]),
        "page": page,
        "bbox": bbox,
    }
