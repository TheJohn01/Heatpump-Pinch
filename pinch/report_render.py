"""PDF (ReportLab) and Word (python-docx) files of a TEA report (``pinch.report``).

Both formats share one layout, taken from the reference TEA report the project follows:

* A4, margins 2 cm; Helvetica (PDF) / Arial (Word, metrically identical) 11 pt on 16.5 pt lines,
  justified; headings bold, 15 pt (sections, each on a new page) and 12 pt (subsections);
* title page: the title, the standard and review status in a shaded box, the generation line;
* tables: full text width, rules above and below the header and below the last row (no vertical
  lines), header bold and centred, header repeated on a new page; caption above;
* figures: centred, caption below;
* footer on every page: "<standard statement> | <page number>", 7.5 pt.

The PDF uses the 14 standard fonts, which cover only the Windows-1252 characters; any other
character (Greek letters, arrows, ≤, −) is set in DejaVu Sans, which ships with matplotlib, so
nothing is lost and no font has to be installed. In Word, captions use the "Caption" style and SEQ
fields, so Word can build a list of tables and figures from them.
"""

from __future__ import annotations

import io
from pathlib import Path
from xml.sax.saxutils import escape

from pinch.report import Box, Figure, Heading, Para, Report, Table, runs

PAGE_W_PT, PAGE_H_PT = 595.2756, 841.8898      # A4
MARGIN_PT = 56.69291                          # 2 cm
BODY_PT, LEADING_PT = 11, 16.5
H1_PT, H2_PT, FOOT_PT = 15, 12, 7.5
BOX_FILL, BOX_LINE = "#FFF4D6", "#C99A00"
RULE_PT = 1.5
FIGURE_MAX_H_FRAC = 0.8                        # of the text height, so a caption fits on the same page
#: Characters the standard PDF fonts (WinAnsi) render; everything else goes to DejaVu Sans
_SAFE = set("€°×·±–—‘’“”…éèêëáàâãäçíìîïóòôõöúùûüñºªÉÈÁÀÂÃÇÍÓÔÕÚÜÑ§«»µ")


# ================================================================== PDF
def _fallback_font() -> str:
    """Register DejaVu Sans (and bold) from matplotlib's data folder once; returns the font name."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():
        import matplotlib
        d = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        pdfmetrics.registerFont(TTFont("DejaVuSans", str(d / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(d / "DejaVuSans-Bold.ttf")))
    return "DejaVuSans"


def _rl_text(text: str) -> str:
    """Escape for ReportLab paragraphs; characters outside WinAnsi in DejaVu Sans."""
    out = []
    for ch in text:
        if ord(ch) < 128 or ch in _SAFE:
            out.append(escape(ch))
        elif ch == "̇":                    # combining dot (Q̇): not drawn
            continue
        else:
            out.append(f'<font face="{_fallback_font()}">{escape(ch)}</font>')
    return "".join(out)


def _rl(text: str) -> str:
    tags = {"": ("", ""), "b": ("<b>", "</b>"), "sub": ("<sub>", "</sub>"), "sup": ("<super>", "</super>")}
    return "".join(tags[st][0] + _rl_text(t) + tags[st][1] for t, st in runs(text))


def to_pdf(report: Report) -> bytes:
    """The report as a PDF file (bytes)."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, TableStyle
    from reportlab.platypus import Table as RLTable

    body = ParagraphStyle("body", fontName="Helvetica", fontSize=BODY_PT, leading=LEADING_PT, alignment=TA_JUSTIFY,
                          spaceAfter=12)
    title = ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=H1_PT, leading=22.5,
                           alignment=TA_LEFT, spaceAfter=14)
    h1 = ParagraphStyle("h1", parent=title, leading=18, spaceAfter=14, keepWithNext=1)
    h2 = ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=H2_PT, leading=14.4, spaceBefore=6,
                        spaceAfter=12, alignment=TA_LEFT, keepWithNext=1)
    cap = ParagraphStyle("caption", parent=body, alignment=TA_LEFT, spaceAfter=8)
    cap_above = ParagraphStyle("caption_above", parent=cap, keepWithNext=1)
    cell = ParagraphStyle("cell", parent=body, alignment=TA_LEFT, spaceAfter=0)
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold", alignment=TA_CENTER)
    box = ParagraphStyle("box", parent=body, fontName="Helvetica-Bold", alignment=TA_LEFT, spaceAfter=0)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN_PT, rightMargin=MARGIN_PT, topMargin=MARGIN_PT,
                            bottomMargin=MARGIN_PT, title=report.short_title, author="Heatpump-Pinch",
                            subject=report.title[0], creator="Heatpump-Pinch")
    width = doc.width - 12                      # frame padding 6 pt each side

    def footer(canvas, _doc) -> None:
        from pinch.report import FOOTER
        canvas.saveState()
        canvas.setFont("Helvetica", FOOT_PT)
        canvas.drawString(MARGIN_PT, 34, f"{FOOTER} | {canvas.getPageNumber()}")
        canvas.restoreState()

    story: list = [Paragraph("<br/>".join(_rl(x) for x in report.title), title)]
    for blk, k in report.numbered():
        if isinstance(blk, Heading):
            if blk.level == 1:              # every section on a new page (the title page is page 1)
                story += [PageBreak(), Paragraph(_rl(blk.text), h1)]
            else:
                story.append(Paragraph(_rl(blk.text), h2))
        elif isinstance(blk, Para):
            story.append(Paragraph(_rl(blk.text), body))
        elif isinstance(blk, Box):
            t = RLTable([[Paragraph(_rl(blk.text), box)]], colWidths=[doc.width])
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(BOX_FILL)),
                                   ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(BOX_LINE)),
                                   ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
            story += [t, Spacer(1, 12)]
        elif isinstance(blk, Table):
            story.append(Paragraph(f"<b>Table {k}.</b> " + _rl(blk.caption), cap_above))
            widths = blk.widths or tuple(1 / len(blk.header) for _ in blk.header)
            data = [[Paragraph(_rl(h), head) for h in blk.header]]
            data += [[Paragraph(_rl(c), cell) for c in row] for row in blk.rows]
            t = RLTable(data, colWidths=[w * width for w in widths], repeatRows=1, hAlign="CENTER")
            t.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), RULE_PT, colors.black),
                                   ("LINEBELOW", (0, 0), (-1, 0), RULE_PT, colors.black),
                                   ("LINEBELOW", (0, -1), (-1, -1), RULE_PT, colors.black),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
            story += [t, Spacer(1, 12)]
        elif isinstance(blk, Figure):
            ir = ImageReader(io.BytesIO(blk.png))
            iw, ih = ir.getSize()
            w = blk.width * width
            h = w * ih / iw
            h_max = FIGURE_MAX_H_FRAC * doc.height
            if h > h_max:
                w, h = w * h_max / h, h_max
            img = Image(io.BytesIO(blk.png), width=w, height=h)
            img.hAlign = "CENTER"
            story.append(KeepTogether([img, Spacer(1, 6),
                                       Paragraph(f"<b>Figure {k}.</b> " + _rl(blk.caption), cap)]))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


# ================================================================== Word
def to_docx(report: Report) -> bytes:
    """The report as a Word (.docx) file (bytes)."""
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Cm(2.0)
    sec.footer_distance = Cm(1.0)
    sec.start_type = WD_SECTION.NEW_PAGE
    text_w = sec.page_width - sec.left_margin - sec.right_margin
    font = "Arial"

    def style(name: str, size: float, bold: bool = False, align=None, before: float = 0, after: float = 12,
              keep_next: bool = False, page_break: bool = False):
        st = doc.styles[name]
        st.font.name, st.font.size, st.font.bold = font, Pt(size), bold
        st.font.italic = False
        st.font.color.rgb = RGBColor(0, 0, 0)
        rpr = st.element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rfonts.set(qn(attr), font)
        for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
            rfonts.attrib.pop(qn(attr), None)
        pf = st.paragraph_format
        pf.space_before, pf.space_after = Pt(before), Pt(after)
        pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        pf.line_spacing = Pt(LEADING_PT if size <= BODY_PT else size * 1.2)
        pf.keep_with_next = keep_next
        pf.page_break_before = page_break
        if align is not None:
            pf.alignment = align
        return st

    style("Normal", BODY_PT, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    style("Title", H1_PT, bold=True, align=WD_ALIGN_PARAGRAPH.LEFT, after=14)
    doc.styles["Title"].paragraph_format.line_spacing = Pt(22.5)
    _no_border(doc.styles["Title"], qn, OxmlElement)
    style("Heading 1", H1_PT, bold=True, align=WD_ALIGN_PARAGRAPH.LEFT, after=14, keep_next=True, page_break=True)
    style("Heading 2", H2_PT, bold=True, align=WD_ALIGN_PARAGRAPH.LEFT, before=6, after=12, keep_next=True)
    style("Caption", BODY_PT, align=WD_ALIGN_PARAGRAPH.LEFT, after=8)

    zoom = doc.settings.element.find(qn("w:zoom"))
    if zoom is not None and zoom.get(qn("w:percent")) is None:   # the default template omits a required attribute
        zoom.set(qn("w:percent"), "100")
    core = doc.core_properties
    core.title, core.author, core.subject = report.short_title, "Heatpump-Pinch", report.title[0]

    # footer: statement | page number
    from pinch.report import FOOTER
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _run(fp, f"{FOOTER} | ", size=FOOT_PT, font=font)
    _field(fp, "PAGE", "1", qn, OxmlElement, size=FOOT_PT, font=font)

    def add_runs(par, text: str, size: float | None = None, bold_all: bool = False) -> None:
        for t, st in runs(text):
            r = par.add_run(t)
            r.bold = bold_all or st == "b" or None
            r.font.subscript = st == "sub" or None
            r.font.superscript = st == "sup" or None
            if size:
                r.font.size = Pt(size)

    title = doc.add_paragraph(style="Title")
    for i, line in enumerate(report.title):
        if i:
            title.add_run().add_break(WD_BREAK.LINE)
        add_runs(title, line)
    for blk, k in report.numbered():
        if isinstance(blk, Heading):
            add_runs(doc.add_paragraph(style="Heading 1" if blk.level == 1 else "Heading 2"), blk.text)
        elif isinstance(blk, Para):
            add_runs(doc.add_paragraph(), blk.text)
        elif isinstance(blk, Box):
            t = doc.add_table(rows=1, cols=1)
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            c = t.cell(0, 0)
            c.width = text_w
            _cell_borders(c, {s: (4, BOX_LINE) for s in ("top", "left", "bottom", "right")}, qn, OxmlElement)
            _shade(c, BOX_FILL, qn, OxmlElement)     # tcBorders before shd (schema order)
            p = c.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_after = Pt(0)
            add_runs(p, blk.text, bold_all=True)
            _spacer(doc)
        elif isinstance(blk, Table):
            _caption(doc, "Table", k, blk.caption, add_runs, qn, OxmlElement, keep_next=True)
            widths = blk.widths or tuple(1 / len(blk.header) for _ in blk.header)
            t = doc.add_table(rows=1 + len(blk.rows), cols=len(blk.header))
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            t.autofit = False
            _fixed_layout(t, [int(w * text_w) for w in widths], qn, OxmlElement)
            for j, h in enumerate(blk.header):
                c = t.cell(0, j)
                p = c.paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                add_runs(p, h, bold_all=True)
                _cell_borders(c, {"top": (12, "000000"), "bottom": (12, "000000")}, qn, OxmlElement)
            _repeat_header(t.rows[0], qn, OxmlElement)
            for i, row in enumerate(blk.rows, 1):
                for j, val in enumerate(row):
                    c = t.cell(i, j)
                    p = c.paragraphs[0]
                    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                    add_runs(p, val)
                    if i == len(blk.rows):
                        _cell_borders(c, {"bottom": (12, "000000")}, qn, OxmlElement)
            for row in t.rows:
                for j, c in enumerate(row.cells):
                    c.width = int(widths[j] * text_w)
                    _cell_margins(c, qn, OxmlElement)
                    for p in c.paragraphs:
                        p.paragraph_format.space_after = Pt(0)
            _spacer(doc)
        elif isinstance(blk, Figure):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.keep_with_next = True
            p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            p.paragraph_format.space_after = Pt(6)
            w = blk.width * text_w
            h_max = FIGURE_MAX_H_FRAC * (sec.page_height - sec.top_margin - sec.bottom_margin)
            from PIL import Image as PILImage
            iw, ih = PILImage.open(io.BytesIO(blk.png)).size
            if w * ih / iw > h_max:
                w = h_max * iw / ih
            p.add_run().add_picture(io.BytesIO(blk.png), width=int(w))
            _caption(doc, "Figure", k, blk.caption, add_runs, qn, OxmlElement)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ Word helpers (OOXML details)
def _run(par, text: str, size: float, font: str):
    from docx.shared import Pt
    r = par.add_run(text)
    r.font.size, r.font.name = Pt(size), font
    return r


def _field(par, instr: str, cached: str, qn, OxmlElement, size: float | None = None, font: str | None = None,
           bold: bool = False) -> None:
    """Simple field (PAGE, SEQ ...) with a cached result, so the number shows before Word updates fields."""
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), f" {instr} ")
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    if bold:
        rpr.append(OxmlElement("w:b"))
    if font:
        rf = OxmlElement("w:rFonts")
        for a in ("w:ascii", "w:hAnsi", "w:cs"):
            rf.set(qn(a), font)
        rpr.append(rf)
    if size:
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), str(int(size * 2)))
        rpr.append(sz)
    r.append(rpr)
    t = OxmlElement("w:t")
    t.text = cached
    r.append(t)
    fld.append(r)
    par._p.append(fld)


def _caption(doc, label: str, number: int, text: str, add_runs, qn, OxmlElement, keep_next: bool = False) -> None:
    p = doc.add_paragraph(style="Caption")
    p.paragraph_format.keep_with_next = keep_next
    r = p.add_run(f"{label} ")
    r.bold = True
    _field(p, f"SEQ {label} \\* ARABIC", str(number), qn, OxmlElement, bold=True)
    r = p.add_run(". ")
    r.bold = True
    add_runs(p, text)


def _spacer(doc) -> None:
    from docx.shared import Pt
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = Pt(6)


def _shade(cell, fill: str, qn, OxmlElement) -> None:
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill.lstrip("#"))
    cell._tc.get_or_add_tcPr().append(shd)


def _cell_borders(cell, sides: dict, qn, OxmlElement) -> None:
    """sides: {"top": (size in eighths of a point, hex colour), ...}; other sides stay without a line."""
    tcpr = cell._tc.get_or_add_tcPr()
    borders = tcpr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tcpr.append(borders)
    for side, (sz, colour) in sides.items():
        el = borders.find(qn(f"w:{side}"))
        if el is None:
            el = OxmlElement(f"w:{side}")
            borders.append(el)
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(sz))
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), colour.lstrip("#"))


def _cell_margins(cell, qn, OxmlElement, top_dxa: int = 140, side_dxa: int = 80) -> None:
    tcpr = cell._tc.get_or_add_tcPr()
    mar = OxmlElement("w:tcMar")
    for side, v in (("top", top_dxa), ("left", side_dxa), ("bottom", top_dxa), ("right", side_dxa)):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:w"), str(v))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tcpr.append(mar)


def _fixed_layout(table, widths_emu: list[int], qn, OxmlElement) -> None:
    """Fixed column widths in twips (dxa) on the grid and the table, no table-level borders."""
    tblpr = table._tbl.tblPr
    for old in tblpr.findall(qn("w:tblW")) + tblpr.findall(qn("w:tblLayout")):
        tblpr.remove(old)
    tw = OxmlElement("w:tblW")                 # schema order: tblStyle, ..., tblW, jc, ..., tblLayout, tblCellMar, tblLook
    tw.set(qn("w:w"), str(sum(int(w / 635) for w in widths_emu)))
    tw.set(qn("w:type"), "dxa")
    style = tblpr.find(qn("w:tblStyle"))
    tblpr.insert(0 if style is None else list(tblpr).index(style) + 1, tw)
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    after = [el for el in tblpr if el.tag in (qn("w:tblCellMar"), qn("w:tblLook"), qn("w:tblCaption"),
                                                qn("w:tblDescription"))]
    if after:
        after[0].addprevious(layout)
    else:
        tblpr.append(layout)
    grid = table._tbl.tblGrid
    for col, w in zip(grid.findall(qn("w:gridCol")), widths_emu):
        col.set(qn("w:w"), str(int(w / 635)))    # 635 EMU per twip


def _repeat_header(row, qn, OxmlElement) -> None:
    trpr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trpr.append(el)


def _no_border(st, qn, OxmlElement) -> None:
    """The default 'Title' style has a bottom border and theme colour; the reference title has neither."""
    ppr = st.element.get_or_add_pPr()
    for b in ppr.findall(qn("w:pBdr")):
        ppr.remove(b)
