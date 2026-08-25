import os
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle,
    PageBreak, ListFlowable, ListItem, Preformatted,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

import content as C

GREEN = colors.HexColor("#2E5D50")
GOLD = colors.HexColor("#C9A227")
CREAM = colors.HexColor("#FAF7F0")
INK = colors.HexColor("#2B2B26")
MUTED = colors.HexColor("#6D6A5E")
ROWALT = colors.HexColor("#F7F5EF")

styles = getSampleStyleSheet()
title_style = ParagraphStyle("TitleBig", parent=styles["Title"], fontSize=30, textColor=colors.white, spaceAfter=6, alignment=TA_LEFT)
subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontSize=13, textColor=CREAM, fontName="Helvetica-Oblique")
h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=20, textColor=GREEN, spaceBefore=0, spaceAfter=12, fontName="Helvetica-Bold")
body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10.8, textColor=INK, leading=15.5, spaceAfter=8)
bullet_style = ParagraphStyle("Bullet", parent=body, leftIndent=14, spaceAfter=7)
caption = ParagraphStyle("Caption", parent=styles["Normal"], fontSize=9, textColor=MUTED, alignment=TA_CENTER, spaceAfter=10, fontName="Helvetica-Oblique")
footer_style = ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8.5, textColor=MUTED)

PAGE_W, PAGE_H = LETTER


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(GREEN)
    canvas.rect(0, PAGE_H - 0.15 * inch, PAGE_W, 0.15 * inch, fill=1, stroke=0)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8.5)
    canvas.drawString(0.75 * inch, 0.45 * inch, "Bellhaven CRM Pipeline")
    canvas.drawRightString(PAGE_W - 0.75 * inch, 0.45 * inch, f"Page {doc.page}")
    canvas.restoreState()


story = []

# ---------------------------------------------------------------------------
# Title page
# ---------------------------------------------------------------------------
def title_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(GREEN)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 34)
    canvas.drawString(0.9 * inch, PAGE_H - 3.1 * inch, C.TITLE)
    canvas.setFillColor(GOLD)
    canvas.rect(0.9 * inch, PAGE_H - 3.35 * inch, 2.2 * inch, 0.045 * inch, fill=1, stroke=0)
    canvas.setFillColor(CREAM)
    canvas.setFont("Helvetica-Oblique", 13)
    text = C.SUBTITLE
    # wrap subtitle manually across ~2 lines
    import textwrap
    for i, line in enumerate(textwrap.wrap(text, 62)):
        canvas.drawString(0.9 * inch, PAGE_H - 3.75 * inch - i * 0.28 * inch, line)
    canvas.setFillColor(GOLD)
    canvas.setFont("Helvetica", 11)
    canvas.drawString(0.9 * inch, 0.9 * inch, "github.com/dparikh066-stack/bellhaven-crm-pipeline")
    canvas.restoreState()


story.append(Spacer(1, 1))  # page 1 is drawn entirely by title_page(); this just occupies it
story.append(PageBreak())   # so real content flows starting on page 2

for sec in C.SECTIONS:
    elements = [Paragraph(sec["title"], h1)]

    table = sec.get("table") or sec.get("big_table")
    diagram = sec.get("diagram")
    is_screenshot = sec.get("screenshot", False)
    code = sec.get("code")
    bullets = sec.get("bullets", [])

    if diagram:
        img_path = os.path.join(C.IMG_ROOT, diagram)
        from PIL import Image as PILImage
        with PILImage.open(img_path) as im:
            iw, ih = im.size
        max_w = 6.9 * inch
        max_h = 5.4 * inch if is_screenshot else 3.6 * inch
        ratio = min(max_w / iw, max_h / ih)
        img = RLImage(img_path, width=iw * ratio, height=ih * ratio)
        elements.append(img)
        elements.append(Spacer(1, 10))

    if code:
        code_style = ParagraphStyle("Code", parent=body, fontName="Courier", fontSize=8.3, leading=10.8,
                                     textColor=colors.HexColor("#D4D4D4"), spaceAfter=0)
        code_pre = Preformatted(code, code_style)
        code_table = Table([[code_pre]], colWidths=[6.9 * inch])
        code_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1E1E1E")),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(code_table)
        elements.append(Spacer(1, 10))

    if bullets:
        items = [ListItem(Paragraph(b, bullet_style), bulletColor=GREEN, value="circle") for b in bullets]
        elements.append(ListFlowable(items, bulletType="bullet", start="circle", leftIndent=16, bulletFontSize=6))

    if table:
        headers = table["headers"]
        rows = table["rows"]
        data = [headers] + rows
        col_widths = ([0.35 * inch, 2.35 * inch, 1.2 * inch, 3.0 * inch] if len(headers) == 4
                       else [1.4 * inch, 2.4 * inch, 3.1 * inch])
        cell_style = ParagraphStyle("Cell", parent=body, fontSize=8.7, leading=11, spaceAfter=0)
        head_style = ParagraphStyle("Head", parent=body, fontSize=9.3, leading=11, textColor=colors.white, fontName="Helvetica-Bold", spaceAfter=0)
        wrapped = [[Paragraph(h, head_style) for h in headers]]
        for row in rows:
            wrapped.append([Paragraph(c, cell_style) for c in row])
        t = Table(wrapped, colWidths=col_widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), GREEN),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E4DFD2")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
        for r in range(1, len(wrapped)):
            if r % 2 == 0:
                style.append(("BACKGROUND", (0, r), (-1, r), ROWALT))
        t.setStyle(TableStyle(style))
        elements.append(t)

    story.append(elements[0])
    story.extend(elements[1:])
    story.append(PageBreak())

# remove trailing page break
if story and isinstance(story[-1], PageBreak):
    story.pop()

doc = SimpleDocTemplate(
    os.path.join(os.path.dirname(__file__), "..", "Bellhaven_CRM_Pipeline.pdf"),
    pagesize=LETTER,
    topMargin=0.85 * inch, bottomMargin=0.75 * inch,
    leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    title="Bellhaven CRM Pipeline",
)

doc.build(story, onFirstPage=title_page, onLaterPages=on_page)
print("Wrote", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Bellhaven_CRM_Pipeline.pdf")))
