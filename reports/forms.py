"""Official LSPU forms for Appendix E (LSPU-RDO-SF-017) and Appendix F (SF-16 terminal narrative outline).

Client follow-up 2026-10-02: the export must look like the form whichever file type is picked. So each form is
described once as a list of blocks (header lines, tables, sections, signatures) and render_form() draws the same
blocks as PDF, Word, Excel or CSV. The generic field/value renderers in renderers.py stay for the other reports.

Block kinds:
  {"kind": "header", "lines": [...], "title": str}          university header + form title
  {"kind": "line", "text": str, "italic": bool}             one line of text
  {"kind": "table", "header": [[...], ...], "rows": [[...]], "widths": [...], "spans": [(row, first, last)]}
      spans merge header cells of header row `row` from column `first` to `last`
  {"kind": "heading", "text": str, "level": 1|2}            outline heading (SF-16)
  {"kind": "section", "heading": str, "body": str, "level": 1|2}  heading + text; blank body = space to write in
  {"kind": "signatures", "items": [(label, name, role), ...]}
  {"kind": "footer", "parts": [left, center, right]}
  {"kind": "page_break"}
"""
import csv
import io
import re
from xml.sax.saxutils import escape

from monitoring.models import MidtermReport, TerminalReport
from outputs.serializers import COMPUTED_6P

UNIVERSITY = ["Republic of the Philippines", "Laguna State Polytechnic University", "Province of Laguna"]
HEADER_FILL = "BDD7EE"  # the light blue of the printed SF-017 headers
# 6P wording of the LSPU forms (SF-017/SF-018), not the RMIS labels
FORM_6P_LABELS = {
    "publications": "Publications", "patents": "Patent", "products": "Products",
    "people_services": "People Services", "places_partnerships": "Places/Partnerships",
    "policies": "Policy Recommendations",
}


def _name(user):
    return (user.get_full_name() or user.email) if user else ""


def _pct(value):
    return "" if value is None else f"{value:g}%"


def _objectives(project):
    """Project objectives as a list; manual registration saves them as "1. ...\\n2. ..."."""
    lines = [re.sub(r"^\d+[.)]\s*", "", line).strip() for line in (project.objectives or "").splitlines()]
    return [line for line in lines if line]


def _dean(project):
    endorser = project.endorsers.filter(designation__icontains="dean").first()
    return endorser.name if endorser else ""


# ---- Appendix E: LSPU-RDO-SF-017 Midterm/Terminal Report ----------------------------------------------------------

def sf017_blocks(report):
    project = report.project
    objectives = report.objective_accomplishments or [
        {"objective": text, "q1": None, "q2": None, "q3": None, "q4": None} for text in _objectives(project)
    ]
    outputs = []
    for i, output in enumerate(project.expected_outputs.order_by("id"), start=1):
        related = COMPUTED_6P.get(output.category)
        actual = getattr(project, related).count() if related else output.manual_actual_count
        outputs.append([str(i), FORM_6P_LABELS.get(output.category, output.get_category_display()),
                        output.description, str(output.target_count), f"Actual: {actual}"])
    return [
        {"kind": "header", "lines": UNIVERSITY, "title": "MIDTERM/TERMINAL REPORT (FOR-LSPU-FUNDED PROJECT)"},
        {"kind": "line", "text": f"Project: {project.title} ({project.project_code}) · Project Year {report.project_year}"},
        {
            "kind": "table",
            "header": [["", "SPECIFIC OBJECTIVES", "% Accomplishment", "", "", ""], ["", "", "Q1", "Q2", "Q3", "Q4"]],
            "spans": [(0, 2, 5)],
            "rows": [[str(i), row["objective"], *(_pct(row.get(q)) for q in ("q1", "q2", "q3", "q4"))]
                     for i, row in enumerate(objectives, start=1)],
            "widths": [4, 52, 11, 11, 11, 11],
        },
        {"kind": "line", "text": "*please add additional lines as needed", "italic": True},
        {
            "kind": "table",
            "header": [["", "LSPU 6Ps Matrix", "", "", ""], ["", "Item", "Particulars", "Quantity", "Remarks"]],
            "spans": [(0, 1, 4)],
            "rows": outputs,
            "widths": [4, 22, 46, 14, 14],
        },
        {"kind": "line", "text": "**For Terminal Report, please attach narrative report and financial statement", "italic": True},
        {"kind": "signatures", "items": [
            ("Submitted by:", _name(project.lead), "Project Leader"),
            ("Noted by:", _dean(project), "Dean/Associate Dean"),
        ]},
        {"kind": "footer", "parts": ["LSPU-RDO-SF-017", "Rev. 0", "8 August 2018"]},
    ]


def appendix_e_form(project_id):
    """One SF-017 per submitted project year, or None when there is no midterm report yet."""
    reports = MidtermReport.objects.filter(project_id=project_id).select_related("project__lead").order_by("project_year")
    blocks = []
    for report in reports:
        if blocks:
            blocks.append({"kind": "page_break"})
        blocks.extend(sf017_blocks(report))
    return {"title": "Appendix E - Midterm Progress Report", "landscape": True, "blocks": blocks} if blocks else None


# ---- Appendix F: SF-16 Terminal Narrative Report -------------------------------------------------------------------

def appendix_f_form(project_id):
    """SF-16 outline. Sections RMIS already holds are filled from the registration (SF-018) and the terminal report;
    the rest are left blank for the leader to write (client follow-up 2026-10-02)."""
    report = TerminalReport.objects.filter(project_id=project_id).select_related("project__lead").first()
    if not report:
        return None
    project = report.project
    team = list(project.team_members.order_by("id"))
    duration = " – ".join(f"{d:%B %Y}" for d in (project.start_date, project.target_end_date) if d)
    objectives = "\n".join(f"{i}. {text}" for i, text in enumerate(_objectives(project), start=1))
    main_text = [
        ("Introduction", "", 1),
        ("Project Rationale", project.background, 1),
        ("Research Framework", "", 1),
        ("Objectives of the Project/Study", objectives, 1),
        ("Conceptual Model", "", 1),
        ("Significance of the Project/Study", project.socio_economic_significance, 1),
        ("Research Methodology", project.methodology, 1),
        ("Research/Experimental Design", "", 2),
        ("Sampling Design (if applicable)", "", 2),
        ("Instruments and Procedures", "", 2),
        ("Data Collection and Analysis", "", 2),
        ("Results and Discussion", "", 1),
        ("Summary of Findings", "", 1),
        ("Conclusion/s", "", 1),
        ("Recommendation/s", "", 1),
        ("Literature Cited", project.references, 1),
    ]
    contents = ["Acknowledgement", "Mentoring Beneficiaries", "Executive Summary"] + [h for h, _, _ in main_text]
    blocks = [
        {"kind": "header", "lines": UNIVERSITY, "title": "TERMINAL REPORT"},
        {"kind": "line", "text": project.title},
        {
            "kind": "table",
            "header": [],
            "rows": [
                ["Project Code", project.project_code],
                ["Project Leader", _name(project.lead)],
                ["Co-Project Leader/s", "; ".join(m.name for m in team if m.member_role == "co_leader")],
                ["Project Team", "; ".join(m.name for m in team if m.member_role != "co_leader")],
                ["Campus", project.campus],
                ["College Unit", project.college],
                ["Implementing Unit", project.implementing_unit],
                ["Duration", duration],
                ["Total Project Cost", f"PhP {project.total_cost:,.2f}" if project.total_cost is not None else ""],
                ["Date Submitted", f"{report.submitted_at:%B %d, %Y}"],
                ["Certified by RDO/RIUH", f"Yes, {_name(report.certified_by)}" if report.is_certified else "Not yet"],
            ],
            "widths": [30, 70],
        },
        {"kind": "page_break"},
        {"kind": "heading", "text": "PRELIMINARY PAGES", "level": 1},
        {"kind": "section", "heading": "Acknowledgement", "body": "", "level": 2},
        {"kind": "section", "heading": "Mentoring Beneficiaries", "body": "", "level": 2},
        {"kind": "section", "heading": "Table of Contents", "body": "\n".join(contents), "level": 2},
        {"kind": "section", "heading": "Executive Summary", "body": report.narrative, "level": 2},
        {"kind": "heading", "text": "MAIN TEXT", "level": 1},
        *({"kind": "section", "heading": h, "body": body or "", "level": level + 1} for h, body, level in main_text),
    ]
    return {"title": "Appendix F - Terminal Report", "landscape": False, "blocks": blocks}


# ---- Renderers -----------------------------------------------------------------------------------------------------

def _table_width(block):
    return len(block["rows"][0]) if block["rows"] else len(block["header"][-1]) if block["header"] else 2


def _flat_rows(form):
    """The form as plain rows, top to bottom; CSV and Excel both write these."""
    out = []
    for block in form["blocks"]:
        kind = block["kind"]
        if kind == "header":
            out += [[line] for line in block["lines"]] + [[], [block["title"]], []]
        elif kind == "line":
            out.append([block["text"]])
        elif kind == "table":
            out += [list(r) for r in block["header"]] + [list(r) for r in block["rows"]] + [[]]
        elif kind == "heading":
            out += [[], [block["text"]]]
        elif kind == "section":
            out.append([("    " if block["level"] > 2 else "") + block["heading"], block["body"]])
        elif kind == "signatures":
            out += [[]] + [[label, name, role] for label, name, role in block["items"]]
        elif kind == "footer":
            out += [[], block["parts"]]
        elif kind == "page_break":
            out += [[], []]
    return out


def render_form_csv(form):
    buf = io.StringIO()
    csv.writer(buf).writerows(_flat_rows(form))
    return buf.getvalue().encode("utf-8")


def render_form_xlsx(form):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r"[\[\]:*?/\\]", "-", form["title"])[:31]
    thin = Side(style="thin", color="000000")
    grid = Border(left=thin, right=thin, top=thin, bottom=thin)
    fill = PatternFill("solid", fgColor=HEADER_FILL)
    wrap = Alignment(wrap_text=True, vertical="top")
    widths = {}
    row = 1
    span = max([_table_width(b) for b in form["blocks"] if b["kind"] == "table"] or [2])
    if form["landscape"]:
        ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0  # as many pages as needed, only the width is fitted
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    def full(r, value, center=False, **style):
        """A line across the whole form width (header, title, notes)."""
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=span)
        return put(r, 1, value, alignment=Alignment(horizontal="center" if center else "left", wrap_text=True), **style)

    def put(r, c, value, **style):
        cell = ws.cell(row=r, column=c, value=value)
        cell.alignment = style.pop("alignment", wrap)
        for k, v in style.items():
            setattr(cell, k, v)
        return cell

    for block in form["blocks"]:
        kind = block["kind"]
        if kind == "header":
            for line in block["lines"]:
                full(row, line, center=True, font=Font(bold=line == UNIVERSITY[1]))
                row += 1
            full(row + 1, block["title"], center=True, font=Font(bold=True, size=12))
            row += 3
        elif kind == "line":
            italic = block.get("italic", False)
            full(row, block["text"], font=Font(italic=italic, bold=not italic))
            ws.row_dimensions[row].height = 15 * (1 + len(block["text"]) // 90)
            row += 1
        elif kind == "table":
            for i, w in enumerate(block.get("widths", [])):
                widths[i + 1] = max(widths.get(i + 1, 0), w)
            width = _table_width(block)
            for h, header in enumerate(block["header"]):
                for c in range(width):
                    put(row, c + 1, header[c] or None, font=Font(bold=True), fill=fill, border=grid,
                        alignment=Alignment(horizontal="center", vertical="center", wrap_text=True))
                for span_row, first, last in block.get("spans", []):
                    if span_row == h:
                        ws.merge_cells(start_row=row, start_column=first + 1, end_row=row, end_column=last + 1)
                row += 1
            for values in block["rows"]:
                for c, value in enumerate(values):
                    put(row, c + 1, value, border=grid, font=Font(bold=not block["header"] and c == 0))
                row += 1
            row += 1
        elif kind == "heading":
            row += 1
            full(row, block["text"], font=Font(bold=True, size=12))
            row += 1
        elif kind == "section":
            put(row, 1, ("    " if block["level"] > 2 else "") + block["heading"], font=Font(bold=True))
            put(row, 2, block["body"] or None)
            row += 1
        elif kind == "signatures":
            row += 1
            half = max(span // 2, 1)
            for c, (label, name, role) in enumerate(block["items"]):
                first = 1 + c * half
                last = span if c == len(block["items"]) - 1 else first + half - 1
                for r, value, font in ((row, label, Font()), (row + 2, name or "________________________", Font(bold=True)),
                                       (row + 3, role, Font())):
                    ws.merge_cells(start_row=r, start_column=first, end_row=r, end_column=last)
                    put(r, first, value, font=font)
            row += 5
        elif kind == "footer":
            full(row, "        ".join(block["parts"]), font=Font(size=8))
            row += 1
        elif kind == "page_break":
            row += 2
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _shade(cell):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:fill"), HEADER_FILL)
    cell._tc.get_or_add_tcPr().append(shading)


def render_form_docx(form):
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.shared import Pt, RGBColor

    doc = Document()
    doc.styles["Normal"].font.name = "Times New Roman"
    doc.styles["Normal"].font.size = Pt(11)
    section = doc.sections[0]
    if form["landscape"]:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width

    def para(text="", bold=False, italic=False, size=None, center=False):
        p = doc.add_paragraph()
        run = p.add_run(text)
        run.bold, run.italic = bold, italic
        if size:
            run.font.size = Pt(size)
        if center:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        return p

    for block in form["blocks"]:
        kind = block["kind"]
        if kind == "header":
            for line in block["lines"]:
                para(line, bold=line == UNIVERSITY[1], center=True)
            para(block["title"], bold=True, size=13, center=True)
        elif kind == "line":
            para(block["text"], italic=block.get("italic", False), bold=not block.get("italic", False))
        elif kind == "table":
            width = _table_width(block)
            table = doc.add_table(rows=0, cols=width)
            table.style = "Table Grid"
            table.autofit = False
            usable = section.page_width - section.left_margin - section.right_margin
            weights = block.get("widths") or [1] * width
            col_widths = [int(usable * w / sum(weights)) for w in weights]
            for h, header in enumerate(block["header"]):
                cells = table.add_row().cells
                for c in range(width):
                    cells[c].text = header[c]
                    _shade(cells[c])
                    for run in cells[c].paragraphs[0].runs:
                        run.bold = True
                    cells[c].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
                for span_row, first, last in block.get("spans", []):
                    if span_row == h:
                        merged = cells[first].merge(cells[last])
                        merged.text = header[first]
                        for run in merged.paragraphs[0].runs:
                            run.bold = True
                        merged.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            for values in block["rows"]:
                cells = table.add_row().cells
                for c, value in enumerate(values):
                    cells[c].text = value
                    if not block["header"] and c == 0 and value:
                        cells[c].paragraphs[0].runs[0].bold = True
            for c, column in enumerate(table.columns):  # LibreOffice reads the grid, Word reads each cell
                column.width = col_widths[c]
            for r in table.rows:
                for c, cell in enumerate(r.cells):
                    cell.width = col_widths[c]
            para()
        elif kind == "heading":
            para(block["text"], bold=True, size=13)
        elif kind == "section":
            heading = doc.add_heading(block["heading"], level=block["level"])
            for run in heading.runs:  # the form's headings are black, not Word's default blue
                run.font.color.rgb = RGBColor(0, 0, 0)
            if block["body"]:
                for chunk in block["body"].split("\n"):
                    para(chunk)
            else:
                para("\n\n")  # space to write in
        elif kind == "signatures":
            table = doc.add_table(rows=4, cols=len(block["items"]))
            for c, (label, name, role) in enumerate(block["items"]):
                table.cell(0, c).text = label
                table.cell(2, c).text = name or "________________________"
                if table.cell(2, c).paragraphs[0].runs:
                    table.cell(2, c).paragraphs[0].runs[0].bold = True
                table.cell(3, c).text = role
        elif kind == "footer":
            footer = section.footer.paragraphs[0]
            footer.text = "\t".join(block["parts"])
        elif kind == "page_break":
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def render_form_pdf(form):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    pagesize = landscape(A4) if form["landscape"] else A4
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=pagesize, leftMargin=40, rightMargin=40, topMargin=36, bottomMargin=40)
    base = getSampleStyleSheet()["Normal"]
    normal = ParagraphStyle("form", parent=base, fontName="Times-Roman", fontSize=10, leading=13)
    small = ParagraphStyle("cell", parent=normal, fontSize=9, leading=11)
    center = ParagraphStyle("center", parent=normal, alignment=TA_CENTER)
    h1 = ParagraphStyle("h1", parent=normal, fontName="Times-Bold", fontSize=12, spaceBefore=10, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=normal, fontName="Times-Bold", fontSize=11, spaceBefore=8, spaceAfter=3)
    h3 = ParagraphStyle("h3", parent=h2, fontName="Times-BoldItalic", leftIndent=18)
    footer_parts = []

    def p(text, style=normal):
        return Paragraph(escape(text or "").replace("\n", "<br/>"), style)

    elements = []
    for block in form["blocks"]:
        kind = block["kind"]
        if kind == "header":
            for line in block["lines"]:
                elements.append(Paragraph(f"<b>{escape(line)}</b>" if line == UNIVERSITY[1] else escape(line), center))
            elements += [Spacer(1, 10), Paragraph(f"<b>{escape(block['title'])}</b>", center), Spacer(1, 8)]
        elif kind == "line":
            text = escape(block["text"])
            elements.append(Paragraph(f"<i>{text}</i>" if block.get("italic") else f"<b>{text}</b>", normal))
            elements.append(Spacer(1, 4))
        elif kind == "table":
            width = _table_width(block)
            header = [[Paragraph(f"<b>{escape(v)}</b>", ParagraphStyle("th", parent=small, alignment=TA_CENTER))
                       for v in row] for row in block["header"]]
            body = [[p(v, small) for v in row] for row in block["rows"]]
            if not block["header"]:  # label/value table: bold labels
                body = [[Paragraph(f"<b>{escape(r[0])}</b>", small), *[p(v, small) for v in r[1:]]] for r in block["rows"]]
            widths = block.get("widths") or [100 / width] * width
            usable = pagesize[0] - 80
            table = Table(header + body or [[""] * width], colWidths=[usable * w / sum(widths) for w in widths],
                          repeatRows=len(header))
            style = [("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP")]
            if header:
                style.append(("BACKGROUND", (0, 0), (-1, len(header) - 1), colors.HexColor(f"#{HEADER_FILL}")))
            for span_row, first, last in block.get("spans", []):
                style.append(("SPAN", (first, span_row), (last, span_row)))
            table.setStyle(TableStyle(style))
            elements += [table, Spacer(1, 6)]
        elif kind == "heading":
            elements.append(Paragraph(escape(block["text"]), h1))
        elif kind == "section":
            elements.append(Paragraph(escape(block["heading"]), h3 if block["level"] > 2 else h2))
            elements.append(p(block["body"]) if block["body"] else Spacer(1, 48))
        elif kind == "signatures":
            items = block["items"]
            rows = [[label for label, _, _ in items], ["" for _ in items],
                    [name or "________________________" for _, name, _ in items], [role for _, _, role in items]]
            table = Table([[p(v) for v in row] for row in rows], colWidths=[(pagesize[0] - 80) / len(items)] * len(items))
            table.setStyle(TableStyle([("TOPPADDING", (0, 1), (-1, 1), 18)]))
            elements += [Spacer(1, 16), table]
        elif kind == "footer":
            footer_parts = block["parts"]
        elif kind == "page_break":
            elements.append(PageBreak())

    def draw_footer(canvas, _doc):
        if not footer_parts:
            return
        canvas.setFont("Helvetica", 8)
        left, middle, right = footer_parts
        canvas.drawString(40, 22, left)
        canvas.drawCentredString(pagesize[0] / 2, 22, middle)
        canvas.drawRightString(pagesize[0] - 40, 22, right)

    doc.build(elements, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buf.getvalue()


FORM_RENDERERS = {"csv": render_form_csv, "xlsx": render_form_xlsx, "pdf": render_form_pdf, "docx": render_form_docx}
