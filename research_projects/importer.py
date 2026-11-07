"""Excel registration of a project in the LSPU-RDO-SF-018 (Research Proposal Form) layout.

build_template() makes the blank workbook; import_workbook() reads a filled one and saves the project and its
tables through the same serializers the manual endpoints use, so both paths follow the same validation rules.
"""
import datetime
import io
import re
from decimal import Decimal

import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from accounts.models import STAFF_ID_MESSAGE, STAFF_ID_PATTERN, User
from accounts.permissions import LEADER_ROLES
from budget_lib.events import log_registration_lib
from budget_lib.models import LibItem, LineItem, allocation_periods
from budget_lib.serializers import LineItemBudgetSerializer, LineItemSerializer, catalog_item_name, clean_allocations, line_total
from rest_framework.exceptions import ValidationError
from outputs.models import SIX_PS
from outputs.serializers import ExpectedOutputSerializer

from .models import CollegeUnit, CooperatingAgency, FundingType, Program, Project, RdeThrust, ProjectEndorser, ProjectTeamMember
from .serializers import (
    ProjectEndorserSerializer, ProjectSerializer, ProjectTeamMemberSerializer, StudySerializer, TargetBeneficiarySerializer,
    objective_items,
    WorkPlanMilestoneSerializer, co_leader_problem, leader_owns,
)

NEW_OR_CONTINUING = (("new", "New Proposal"), ("continuing", "Continuing"))
WET_OR_DRY = (("wet", "Wet Research"), ("dry", "Dry Research"), ("not_applicable", "Not Applicable"))

# One dropdown since client feedback 2026-10-06; saved to both college and implementing_unit, like manual entry.
COLLEGE_UNIT_LABEL = "College Unit - Implementing Unit"
# System Admin pages that manage each dropdown, named in import errors and template notes
ADMIN_CHOICE_PAGES = {CollegeUnit: "College Units", RdeThrust: "RDE Thrusts", CooperatingAgency: "Cooperating Agencies"}
# Templates downloaded before the merge still have the two old rows; read either as the merged field.
OLD_COLLEGE_UNIT_LABELS = ("Implementing Unit", "College Unit")
# Client 2026-10-29 (Task 4, Q-A): the NTP number is the official code. Older templates have the Project Code row
# instead; it is never copied into the NTP, so such a file needs the NTP row filled.
NTP_LABEL = "NTP (Notice to Proceed No.)"
LEAD_STAFF_ID_LABEL = "Project Leader Staff ID"
LEGACY_PROJECT_CODE_LABEL = "LSPU Faculty Research Number (Project Code)"

# (label in column A, serializer field, kind, choices, note in column C). Order follows the form.
class _FundingTypes:
    """(code, name) pairs read when the template is built or a workbook is imported, so the admin's Funding Types count."""

    def __iter__(self):
        rows = dict(Program.FUNDING_CHOICES)
        rows.update(FundingType.objects.values_list("code", "name"))
        return iter(rows.items())


FUNDING_TYPES = _FundingTypes()

PROJECT_FIELDS = [
    ("Title", "title", "text", None, "Required"),
    (NTP_LABEL, "ntp_number", "text", None, "Required, must be unique; the NTP number is the project's official code"),
    ("Program Code (if under a Program)", "program", "program", None, "Optional; code of an existing RMIS Program"),
    ("Funding Type", "funding_type", "choice", FUNDING_TYPES, "Required"),
    (LEAD_STAFF_ID_LABEL, "lead_staff_id", "staff_id", None,
     "Required; RMIS account with the Project Leader role; format the cell as Text so leading zeros stay"),
    ("Project Leader E-mail Address", "lead", "user", None, "Optional; when given, must be the same account as the Staff ID"),
    ("Project Leader Gender", "lead_gender", "choice", Project.GENDER_CHOICES, "Male or Female"),
    ("Contact No./s.", "contact_number", "text", None, ""),
    ("Start Date", "start_date", "date", None, "Required; date cell or YYYY-MM-DD"),
    ("End Date", "target_end_date", "date", None, "Required; date cell or YYYY-MM-DD"),
    ("Total Project/Study Cost", "total_cost", "decimal", None, "Required; number"),
    # Client 2026-10-29 (Task 11): the campus list of the accounts (User.CAMPUS_CHOICES), the same as Manual Entry
    ("Campus", "campus", "choice", User.CAMPUS_CHOICES, "The Project Leader's campus; blank = the leader's campus"),
    (COLLEGE_UNIT_LABEL, "implementing_unit", "admin_choice", CollegeUnit, "Must match System Admin > College Units"),
    ("Cooperating Agency/ies", "cooperating_agencies", "admin_choices", CooperatingAgency,
     "One or more, separated by semicolons; must match System Admin > Cooperating Agencies"),
    ("Sector", "sectors", "multi", Project.SECTOR_CHOICES, "Required; one or more, comma-separated"),
    ("Sector (if Others)", "sector_other", "text", None, "Required when Sector includes Others"),
    ("New or Continuing", "is_continuing", "choice", NEW_OR_CONTINUING, "Required: New Proposal or Continuing"),
    ("Continuing Year", "continuing_year", "int", None, "2, 3, ... (continuing proposals only)"),
    ("Basic or Applied Research", "research_type", "choice", Project.RESEARCH_TYPE_CHOICES, "Required"),
    ("Wet or Dry Research", "is_dry_research", "choice", WET_OR_DRY, "Required: Wet, Dry or Not Applicable"),
    ("Research Typology", "research_typology", "multi", Project.TYPOLOGY_CHOICES, "Required; one or more, comma-separated"),
    ("Sustainable Development Goals (SDGs)", "sdgs", "sdgs", None, "Required; goal numbers 1-17, comma-separated"),
    ("RDE Thrust", "rde_thrust", "admin_choice", RdeThrust, "Required; must match System Admin > RDE Thrusts"),
    ("RDE Priority Area", "rde_priority", "admin_choice", RdeThrust,
     "Required; a priority area under the RDE Thrust, e.g. 1.3 - Artificial Intelligence and Machine Learning"),
    ("III. Objectives of the Study", "objectives", "text", None, "Required"),
]

# Table sheets: sheet name -> [(column header, serializer field, kind, choices)]
TEAM_ROLES = ProjectTeamMember.ROLE_CHOICES
CATEGORIES = LineItem.CATEGORY_CHOICES + (("mooe", "MOOE"), ("co", "Equipment Outlay"), ("ps", "PS"))
# Legend sheet rows (client 2026-10-23): code shown, meaning as the LIB step labels it. A separate sheet, because any
# filled cell on the Budget Requirements sheet would be read as a budget row.
CATEGORY_LEGEND = (("ps", "PS", "Personal Services"), ("mooe", "MOOE", "Maintenance and Other Operating Expenses"),
                   ("co", "CO", "Equipment Outlay / Capital Outlay"))
# The form's own 6P wording (Section V), accepted alongside the RMIS labels
SIX_P_CHOICES = SIX_PS + (
    ("patents", "Patent"), ("places_partnerships", "Places/Partnerships"), ("policies", "Policy Recommendations"),
)
# Annex A on the Project sheet becomes endorser rows too, so Excel and manual registrations read the same
# (client meeting 2026-10-01, #8). Only the VPRDE maps to a system role.
ANNEX_A_SIGNATORIES = [
    ("endorsed_by_dean", "endorsed_by_dean_on", "Dean/Associate Dean", ""),
    ("noted_by_rds_director", "noted_by_rds_director_on", "RDS Director/Chairperson", ""),
    ("recommended_by_campus_director", "recommended_by_campus_director_on", "Campus Director", ""),
    ("recommended_by_vprde", "recommended_by_vprde_on", "Vice President for Research, Development and Extension", "vprei"),
    ("approved_by_president", "proposal_approved_on", "University President", ""),
]

TABLE_SHEETS = {
    # Client Task 45 (2026-11-06): no Name/Gender columns; both come from the member's RMIS account. Older templates'
    # Name and Gender columns are ignored.
    "Project Team": [
        ("Role", "member_role", "choice", TEAM_ROLES),
        ("RMIS E-mail", "user", "user", None),
        ("Staff ID", "user_staff_id", "staff_id", None),
    ],
    "Study Components": [
        ("Study Title", "title", "text", None),
        ("Study Leader E-mail", "lead", "user", None),
    ],
    "Expected Outputs (6Ps)": [
        ("Item", "category", "choice", SIX_P_CHOICES),
        ("Particulars", "description", "text", None),
        ("Quantity", "target_count", "int", None),
    ],
    "Target Beneficiaries": [
        ("Target Beneficiaries", "group", "text", None),
        ("Description", "description", "text", None),
        ("Total", "total", "int", None),
    ],
    "Budget Requirements": [
        ("Fiscal Year", "fiscal_year", "int", None),
        ("Category", "category", "choice", CATEGORIES),
        ("Particulars", "description", "text", None),
        # Task 14 (2026-10-29): the specific item under the LIB Item, as in Manual Entry and the LIB template
        ("Specification (optional)", "specification", "text", None),
        ("Unit", "unit", "choice", LineItem.UNIT_CHOICES),
        ("Qty", "quantity", "decimal", None),
        ("Unit Cost", "unit_cost", "decimal", None),
        ("Total", "amount", "decimal", None),
        # Client 2026-10-17 (yearly.png): the total split per quarter of each project year; a one-year project
        # fills only Y1 Q1-Q4 (saved as Q1-Q4)
        *[(f"Y{y} Q{q}", f"alloc_Y{y}Q{q}", "decimal", None) for y in (1, 2, 3) for q in (1, 2, 3, 4)],
    ],
    "Work Plan": [
        ("Activity", "title", "text", None),
        ("Start Date", "start_date", "date", None),
        ("End Date", "target_date", "date", None),
    ],
}
# Templates downloaded before 2026-10-23 still say "Target Date"; read it as the End Date.
OLD_TABLE_HEADERS = {"Work Plan": {"target_date": "Target Date"},
                     "Project Team": {"user": "RMIS E-mail (optional)", "user_staff_id": "Staff ID (optional)"}}
# Typed dates besides real date cells: YYYY-MM-DD, MM/DD/YYYY (Excel's Philippine default), "March 1, 2027"
DATE_FORMATS = ("%m/%d/%Y", "%B %d, %Y", "%b %d, %Y")
TABLE_SERIALIZERS = {
    "Project Team": ProjectTeamMemberSerializer,
    "Study Components": StudySerializer,
    "Expected Outputs (6Ps)": ExpectedOutputSerializer,
    "Target Beneficiaries": TargetBeneficiarySerializer,
    "Budget Requirements": LineItemSerializer,
    "Work Plan": WorkPlanMilestoneSerializer,
}


def _norm(value):
    return re.sub(r"\s+", " ", str(value)).strip().rstrip(".").lower()


class CellError(ValueError):
    pass


def _convert(raw, kind, choices):
    """Turn one cell into the value its serializer field expects. Blank cells return None (field left out)."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if kind == "text":
        return str(raw).strip()
    if kind == "date":
        if isinstance(raw, datetime.datetime):
            return raw.date()
        if isinstance(raw, datetime.date):
            return raw
        text = re.sub(r"\s+", " ", str(raw)).strip()
        try:
            return datetime.date.fromisoformat(text)
        except ValueError:
            pass
        for fmt in DATE_FORMATS:
            try:
                return datetime.datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        raise CellError(f"'{raw}' is not a date (use YYYY-MM-DD, MM/DD/YYYY or March 1, 2027).")
    if kind in ("int", "decimal"):
        text = str(raw).replace(",", "").strip()
        try:
            number = Decimal(text)
        except ArithmeticError:
            raise CellError(f"'{raw}' is not a number.")
        if kind == "int":
            if number != number.to_integral_value():
                raise CellError(f"'{raw}' must be a whole number.")
            return int(number)
        return str(number)
    if kind == "user":
        user = User.objects.filter(email__iexact=str(raw).strip()).first()
        if not user:
            raise CellError(f"No RMIS account with e-mail '{raw}'.")
        return user.pk
    if kind == "staff_id":
        # A number cell drops leading zeros; it is read as typed (123456.0 -> "123456"), never padded or guessed.
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and float(raw).is_integer():
            text = str(int(raw))
        else:
            text = str(raw).strip()
        zeros = " If it starts with 0, format the cell as Text." if text[:1] != "0" else ""
        if not re.fullmatch(STAFF_ID_PATTERN, text):
            raise CellError(f"'{raw}': {STAFF_ID_MESSAGE}{zeros}")
        user = User.objects.filter(staff_id=text).first()  # staff_id is unique
        if not user:
            raise CellError(f"No RMIS account with Staff ID '{text}'.{zeros}")
        return user.pk
    if kind == "program":
        program = Program.objects.filter(code__iexact=str(raw).strip()).first()
        if not program:
            raise CellError(f"No RMIS Program with code '{raw}'.")
        return program.pk
    if kind in ("admin_choice", "admin_choices"):
        # Agency names can contain commas (e.g. "LGU of Siniloan, Laguna"), so several are split on ; or new lines
        parts = re.split(r"[;\n]", str(raw)) if kind == "admin_choices" else [str(raw)]
        names = []
        for part in filter(str.strip, parts):
            choice = choices.objects.filter(name__iexact=part.strip()).first()
            if not choice:
                raise CellError(f"'{part.strip()}' is not in System Admin > {ADMIN_CHOICE_PAGES[choices]}.")
            names.append(choice.name)
        return ", ".join(names)
    if kind == "sdgs":
        try:
            return [int(part) for part in re.split(r"[,;]", str(raw)) if part.strip()]
        except ValueError:
            raise CellError(f"'{raw}' must be SDG numbers separated by commas.")
    lookup = {}
    for code, label in choices:
        lookup[_norm(code)] = code
        lookup[_norm(label)] = code
    if kind == "multi":
        parts = [p for p in re.split(r"[,;]", str(raw)) if p.strip()]
        unknown = [p.strip() for p in parts if _norm(p) not in lookup]
        if unknown:
            raise CellError(f"Unknown value(s): {', '.join(unknown)}.")
        return [lookup[_norm(p)] for p in parts]
    if _norm(raw) not in lookup:
        raise CellError(f"Unknown value '{raw}'.")
    return lookup[_norm(raw)]


def _allowed(kind, choices):
    return ", ".join(label for _, label in choices) if choices and kind in ("choice", "multi") else ""


def fill_line_item_amount(data):
    """Section X rows give Qty and Unit Cost, so the amount is Qty x Unit Cost unless given. Older payloads that
    still send QTR1-QTR4 get their total instead."""
    if data.get("amount") in (None, ""):
        if data.get("quantity") not in (None, "") and data.get("unit_cost") not in (None, ""):
            data["amount"] = str(line_total(data["quantity"], data["unit_cost"]))
        else:
            data["amount"] = str(sum(Decimal(str(data.get(f) or 0)) for f in ("q1_amount", "q2_amount", "q3_amount", "q4_amount")))
    return data


def _add_category_legend(wb):
    sheet = wb.create_sheet("Legend")
    sheet.append(["Budget Requirements - Category column"])
    sheet.append(["Category", "Meaning", "Accepted values in the Category column",
                  "Particulars: the active LIB Items of the category (System Admin > LIB Items)"])
    for code, short, meaning in CATEGORY_LEGEND:
        accepted = ", ".join(dict.fromkeys([short, *(label for c, label in CATEGORIES if c == code)]))
        items = "; ".join(LibItem.objects.filter(category=code, is_active=True).order_by("name").values_list("name", flat=True))
        sheet.append([short, meaning, accepted, items])
    sheet.append([])
    sheet.append(["Particulars must match one of the LIB Items of the row's category exactly."])
    sheet["A1"].font = Font(bold=True)
    for column, width in zip("ABCD", (12, 40, 45, 90)):
        sheet.column_dimensions[column].width = width
    for row in sheet.iter_rows(min_row=3, max_row=5):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    # Client 2026-10-29 (Task 11): the RDE Priority Area row must name a priority area of its thrust; read per download
    sheet.append([])
    sheet.append(["RDE Agenda - RDE Thrust and RDE Priority Area rows (System Admin > RDE Thrusts)"])
    sheet.cell(row=sheet.max_row, column=1).font = Font(bold=True)
    sheet.append(["RDE Thrust", "RDE Priority Areas under it (put one in the RDE Priority Area row)"])
    for thrust in RdeThrust.objects.filter(parent=None):
        sheet.append([thrust.name, "; ".join(thrust.priorities.values_list("name", flat=True))])
        for cell in sheet[sheet.max_row]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")


def _add_table_sheet(sheet, name):
    columns = TABLE_SHEETS[name]
    sheet.append([header for header, *_ in columns])
    for i, (header, _, kind, choices) in enumerate(columns):
        sheet.column_dimensions[get_column_letter(i + 1)].width = max(18, len(header) + 4)
        if kind == "staff_id":
            sheet.column_dimensions[get_column_letter(i + 1)].number_format = "@"
        allowed = _allowed(kind, choices)
        if allowed:
            legend = ". See the Legend sheet." if name == "Budget Requirements" and header == "Category" else ""
            sheet.cell(row=1, column=i + 1).comment = Comment(f"Allowed: {allowed}{legend}", "RMIS")


def build_work_plan_template():
    """Client 2026-10-29 (Task 10): only the Work Plan sheet, the same columns as the registration template, for
    Manual Entry's XI. Work Plan import (read_work_plan)."""
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.title = "Work Plan"
    _add_table_sheet(sheet, "Work Plan")
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    # Client Task 29-C: dates typed into Start/End Date show as YYYY-MM-DD and stay date cells (read_work_plan takes both).
    for i, (header, _, kind, _) in enumerate(TABLE_SHEETS["Work Plan"]):
        if kind == "date":
            sheet.column_dimensions[get_column_letter(i + 1)].number_format = "yyyy-mm-dd"
            sheet.cell(row=1, column=i + 1).comment = Comment("Format: YYYY-MM-DD, e.g. 2026-11-02", "RMIS")
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


LISTS_SHEET = "Lists"
TABLE_ROWS_WITH_DROPDOWNS = 500  # rows 2-501 of each table sheet get the dropdowns


def _labels(choices):
    return [label for _, label in choices]


def _dropdown_lists():
    """Client Task 45 (2026-11-06): the template's choices, read at every download so System Admin changes count.
    Returns [(Lists header, values, targets)]; a target is ("Project", field) for that row's Value cell or
    (sheet, field) for a table column. No targets = a multi-value field, typed comma-separated and only listed."""
    thrusts = RdeThrust.objects.filter(parent=None)
    return [
        ("Funding Type", [name for _, name in FUNDING_TYPES], [("Project", "funding_type")]),
        ("Gender", _labels(Project.GENDER_CHOICES), [("Project", "lead_gender")]),
        ("Campus", _labels(User.CAMPUS_CHOICES), [("Project", "campus")]),
        ("College Unit", list(CollegeUnit.objects.values_list("name", flat=True)), [("Project", "implementing_unit")]),
        ("New or Continuing", _labels(NEW_OR_CONTINUING), [("Project", "is_continuing")]),
        ("Basic or Applied Research", _labels(Project.RESEARCH_TYPE_CHOICES), [("Project", "research_type")]),
        ("Wet or Dry Research", _labels(WET_OR_DRY), [("Project", "is_dry_research")]),
        ("RDE Thrust", list(thrusts.values_list("name", flat=True)), [("Project", "rde_thrust")]),
        ("RDE Priority Area", list(RdeThrust.objects.filter(parent__in=thrusts).order_by("parent__name", "name")
                                   .values_list("name", flat=True)), [("Project", "rde_priority")]),
        ("Project Team Role", _labels(TEAM_ROLES), [("Project Team", "member_role")]),
        ("6Ps Item", _labels(SIX_PS), [("Expected Outputs (6Ps)", "category")]),
        ("Budget Category", [short for _, short, _ in CATEGORY_LEGEND], [("Budget Requirements", "category")]),
        ("LIB Item (Particulars)", list(LibItem.objects.filter(is_active=True).order_by("category", "name")
                                        .values_list("name", flat=True)), [("Budget Requirements", "description")]),
        ("Unit", _labels(LineItem.UNIT_CHOICES), [("Budget Requirements", "unit")]),
        ("Sector (type, comma-separated)", _labels(Project.SECTOR_CHOICES), []),
        ("Research Typology (type, comma-separated)", _labels(Project.TYPOLOGY_CHOICES), []),
        ("SDGs (type the numbers, comma-separated)", [str(n) for n in range(1, 18)], []),
        ("Cooperating Agency/ies (type, separated by ;)", list(CooperatingAgency.objects.values_list("name", flat=True)), []),
    ]


def _add_dropdowns(wb):
    """A protected Lists sheet (one column per choice list) and list Data Validation on the cells that take one value.
    A dropdown only helps typing: the import still checks every value against the current System Admin data."""
    lists = wb.create_sheet(LISTS_SHEET)
    project_rows = {field: row for row, (_, field, *_rest) in enumerate(PROJECT_FIELDS, start=2)}
    for col, (header, values, targets) in enumerate(_dropdown_lists(), start=1):
        letter = get_column_letter(col)
        lists.cell(row=1, column=col, value=header).font = Font(bold=True)
        lists.column_dimensions[letter].width = max(20, min(60, max((len(v) for v in [header, *values]), default=20) + 2))
        for row, value in enumerate(values, start=2):
            lists.cell(row=row, column=col, value=value)
        if not values or not targets:
            continue
        for sheet_name, field in targets:
            if sheet_name not in wb.sheetnames:  # Step 4's LIB template has only the Budget Requirements sheet
                continue
            sheet = wb[sheet_name]
            validation = DataValidation(type="list", formula1=f"{LISTS_SHEET}!${letter}$2:${letter}${len(values) + 1}",
                                        allow_blank=True, showErrorMessage=True, errorStyle="stop",
                                        errorTitle="Not in the list", error=f"Pick a {header} from the list (Lists sheet).")
            if sheet_name == "Project":
                validation.add(f"B{project_rows[field]}")
            else:
                index = [f for _, f, *_rest in TABLE_SHEETS[sheet_name]].index(field) + 1
                column = get_column_letter(index)
                validation.add(f"{column}2:{column}{TABLE_ROWS_WITH_DROPDOWNS + 1}")
            sheet.add_data_validation(validation)
    lists.freeze_panes = "A2"
    lists.protection.sheet = True  # read-only reference; no password


def build_template():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Project"
    ws.append(["Field", "Value", "Notes / allowed values"])
    for label, field, kind, choices, note in PROJECT_FIELDS:
        allowed = _allowed(kind, choices)
        if kind in ("admin_choice", "admin_choices"):
            rows = choices.objects.all()
            if choices is RdeThrust:  # the thrust row lists the thrusts; the priority-area note names the format only
                rows = rows.filter(parent=None) if field == "rde_thrust" else rows.none()
            allowed = "; ".join(rows.values_list("name", flat=True))
        ws.append([label, None, f"{note}. {allowed}".strip(". ") if allowed else note])
        if kind == "staff_id":
            ws.cell(row=ws.max_row, column=2).number_format = "@"
    ws.column_dimensions["A"].width = 45
    ws.column_dimensions["B"].width = 60
    ws.column_dimensions["C"].width = 70
    for cell in ws["B"]:
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for name in TABLE_SHEETS:
        _add_table_sheet(wb.create_sheet(name), name)
    _add_category_legend(wb)
    _add_dropdowns(wb)
    for sheet in wb.worksheets:
        for cell in sheet[1]:
            cell.font = Font(bold=True)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# Client 2026-10-29 (Tasks 6/8): no longer in the template or required, but a filled row of an older template is still
# read and saved, so nothing it carries is dropped.
LEGACY_PROJECT_FIELDS = [
    ("Research Priority Area", "research_priority_area", "choice", Project.PRIORITY_AREA_CHOICES, ""),
    ("II. Background of the Study", "background", "text", None, ""),
    ("IV. Project Descriptions/Methodology", "methodology", "text", None, ""),
    ("VI. Socio-Economic Significance", "socio_economic_significance", "text", None, ""),
    ("VIII. Monitoring/Evaluation", "monitoring_evaluation", "text", None, ""),
    ("IX. List of References", "references", "text", None, ""),
    ("Executive Summary", "description", "text", None, ""),
    ("Anticipated Outcomes", "expected_outcomes", "text", None, ""),
    ("Long-term Potential Impacts", "expected_impacts", "text", None, ""),
    # Tasks 13/14 (2026-10-29): Annex A and its dates left the registration; an older file's rows still become endorsers
    ("Date Submitted (Project Leader)", "proposal_submitted_on", "date", None, "Annex A"),
    ("Endorsed By (Dean/Associate Dean)", "endorsed_by_dean", "text", None, "Annex A"),
    ("Date Endorsed by Dean", "endorsed_by_dean_on", "date", None, "Annex A"),
    ("Noted By (RDS Director/Chairperson)", "noted_by_rds_director", "text", None, "Annex A"),
    ("Date Noted by RDS Director", "noted_by_rds_director_on", "date", None, "Annex A"),
    ("Recommending Approval (Campus Director)", "recommended_by_campus_director", "text", None, "Annex A"),
    ("Date Recommended by Campus Director", "recommended_by_campus_director_on", "date", None, "Annex A"),
    ("Recommending Approval (VPRDE)", "recommended_by_vprde", "text", None, "Annex A"),
    ("Date Recommended by VPRDE", "recommended_by_vprde_on", "date", None, "Annex A"),
    ("Approved By (University President)", "approved_by_president", "text", None, "Annex A"),
    ("Date Approved by University President", "proposal_approved_on", "date", None, "Annex A"),
]


def _read_project_sheet(ws, errors):
    by_label = {_norm(label): (field, kind, choices) for label, field, kind, choices, _ in PROJECT_FIELDS + LEGACY_PROJECT_FIELDS}
    for old in OLD_COLLEGE_UNIT_LABELS:
        by_label[_norm(old)] = by_label[_norm(COLLEGE_UNIT_LABEL)]
    by_label[_norm(LEGACY_PROJECT_CODE_LABEL)] = ("legacy_project_code", "text", None)
    data = {}
    legacy_row = None
    for row_number, row in enumerate(ws.iter_rows(min_row=2, max_col=2, values_only=True), start=2):
        if not row or row[0] is None or _norm(row[0]) not in by_label:
            continue
        field, kind, choices = by_label[_norm(row[0])]
        try:
            value = _convert(row[1] if len(row) > 1 else None, kind, choices)
        except CellError as exc:
            errors.append({"sheet": "Project", "row": row_number, "field": row[0], "message": str(exc)})
            continue
        if value is not None:
            data[field] = value
            if field == "legacy_project_code":
                legacy_row = row_number
    legacy = data.pop("legacy_project_code", None)
    if legacy is not None and str(legacy).strip().upper() != str(data.get("ntp_number", "")).strip().upper():
        errors.append({"sheet": "Project", "row": legacy_row, "field": LEGACY_PROJECT_CODE_LABEL, "message": (
            f"The Project Code is no longer used; the NTP number is the project's code. Put the NTP in the "
            f"'{NTP_LABEL}' row (download the new template) and leave this row blank."
        )})
    if "is_continuing" in data:
        data["is_continuing"] = data["is_continuing"] == "continuing"
    if "is_dry_research" in data:
        data["is_dry_research"] = None if data["is_dry_research"] == "not_applicable" else data["is_dry_research"] == "dry"
    if "implementing_unit" in data:
        data["college"] = data["implementing_unit"]
    return data


def _read_table(ws, name, errors):
    """Rows of {field: value} keyed by the sheet's headers; blank rows are skipped. Returns [(row_number, data)]."""
    columns = TABLE_SHEETS[name]
    rows = ws.iter_rows(values_only=True)
    headers = [_norm(h) if h is not None else "" for h in next(rows, [])]
    index = {}
    for header, field, kind, choices in columns:
        old = OLD_TABLE_HEADERS.get(name, {}).get(field)
        for label in (header, old) if old else (header,):
            if _norm(label) in headers:
                index[field] = (headers.index(_norm(label)), header, kind, choices)
                break
    out = []
    for row_number, row in enumerate(rows, start=2):
        if not any(v is not None and str(v).strip() for v in row):
            continue
        data = {}
        for field, (col, header, kind, choices) in index.items():
            try:
                value = _convert(row[col] if col < len(row) else None, kind, choices)
            except CellError as exc:
                errors.append({"sheet": name, "row": row_number, "field": header, "message": str(exc)})
                continue
            if value is not None:
                data[field] = value
        out.append((row_number, data))
    return out


def _check_work_plan(rows, errors):
    """Every activity needs its name and End Date, can't end before it starts, and the same activity with the same
    dates can't be listed twice (client 2026-10-23: the upload must match the template, without silently dropped or
    doubled rows). Also run for Manual Entry's Work Plan import, which saves nothing itself."""
    seen = {}
    for row_number, data in rows:
        if not data.get("title"):
            errors.append({"sheet": "Work Plan", "row": row_number, "field": "Activity", "message": "Activity is required."})
        if "target_date" not in data:
            errors.append({"sheet": "Work Plan", "row": row_number, "field": "End Date", "message": "End Date is required."})
        elif data.get("start_date") and data["start_date"] > data["target_date"]:
            errors.append({"sheet": "Work Plan", "row": row_number, "field": "Start Date",
                           "message": "Start date cannot be after the end date."})
        key = (_norm(data.get("title", "")), data.get("start_date"), data.get("target_date"))
        if key[0] and key in seen:
            errors.append({"sheet": "Work Plan", "row": row_number, "field": "Activity",
                           "message": f"Same activity and dates as row {seen[key]}."})
        seen.setdefault(key, row_number)


def read_work_plan(file_obj):
    """The Work Plan sheet of a workbook (the registration template or any file with that sheet) as rows for Manual
    Entry Step 5 (client 2026-10-23). Returns (rows, errors); nothing is saved."""
    try:
        wb = openpyxl.load_workbook(file_obj, data_only=True)
    except Exception as exc:  # not an xlsx, or corrupted
        return [], [{"sheet": None, "row": None, "field": "file", "message": f"Could not read workbook: {exc}"}]
    if "Work Plan" not in wb.sheetnames:
        return [], [{"sheet": None, "row": None, "field": "file", "message": "Missing the 'Work Plan' sheet; use the RMIS template."}]
    errors = []
    rows = _read_table(wb["Work Plan"], "Work Plan", errors)
    _check_work_plan(rows, errors)
    if errors:
        return [], errors
    return [
        {"title": data["title"], "start_date": str(data.get("start_date") or ""), "target_date": str(data["target_date"])}
        for _, data in rows
    ], []


# Client Task 50 (2026-11-07): Step 4's LIB template is Upload via Excel's Budget Requirements sheet. LIB_SHEET and
# LIB_COLUMNS are the Task 12 layout (header row with LIB.png's columns, LEGEND rows below), still read so a template
# filled before Task 50 imports.
BUDGET_SHEET = "Budget Requirements"
LIB_SHEET = "LIB"
LIB_COLUMNS = [
    ("Particulars", "category", "choice", CATEGORIES),
    ("Item", "description", "text", None),
    ("Specification (optional)", "specification", "text", None),
    ("Unit", "unit", "choice", LineItem.UNIT_CHOICES),
    ("Qty", "quantity", "decimal", None),
    ("Unit Cost (₱)", "unit_cost", "decimal", None),
    ("Total (₱)", "amount", "decimal", None),
]
LIB_BLANK_ROWS = 30
LIB_LEGEND = "LEGEND"


def lib_periods(start_date, target_end_date):
    """The project's LIB periods from Step 1's dates (YYYY-MM-DD), by allocation_periods. Returns (periods, errors)."""
    dates = {}
    for field, label, value in (("start_date", "Start Date", start_date), ("target_end_date", "Target End Date", target_end_date)):
        try:
            dates[field] = datetime.date.fromisoformat(str(value or "").strip())
        except ValueError:
            return None, [{"sheet": None, "row": None, "field": label,
                           "message": f"Set a valid {label} in Step 1 Project Details first."}]
    periods = allocation_periods(Project(**dates))
    if periods is None:
        return None, [{"sheet": None, "row": None, "field": "Target End Date", "message": "The Target End Date is before the Start Date."}]
    return periods, []


def _period_meaning(period):
    """Y2Q3 -> months 19-21 from the Start Date; Q3 -> months 7-9."""
    year, quarter = (int(period[1:period.index("Q")]), int(period[-1])) if period[0] == "Y" else (1, int(period[1:]))
    first = (year - 1) * 12 + (quarter - 1) * 3 + 1
    return f"Year {year}, Quarter {quarter}: months {first}-{first + 2} counted from the Start Date"


def _period_header(period):
    """'Y2Q3' -> 'Y2 Q3'; a one-year project's 'Q3' -> 'Y1 Q3', the Upload via Excel column that holds it."""
    return f"Y1 {period}" if period[0] == "Q" else period.replace("Q", " Q")


def _period_key(header, one_year):
    """A period column header ('Y2 Q3', 'y2q3') -> 'Y2Q3'; a one-year project's 'Y1 Q3' -> 'Q3', as Upload via Excel
    reads it. None if the header isn't a period."""
    match = re.fullmatch(r"Y(\d+)\s*Q([1-4])", str(header or "").strip(), re.IGNORECASE)
    if not match:
        return None
    return f"Q{match[2]}" if one_year and match[1] == "1" else f"Y{int(match[1])}Q{match[2]}"


def build_lib_template(start_date, target_end_date, periods, items=()):
    """Step 4's LIB workbook: since client Task 50 (2026-11-07) the Budget Requirements sheet of Upload via Excel (same
    columns, Legend sheet and Lists dropdowns), plus Y4+ period columns only for a project longer than three years.
    With `items` (Task 20 LIB download) the first rows hold the LIB as saved, so read_lib reads it back unchanged; the
    template itself has no items."""
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.title = BUDGET_SHEET
    _add_table_sheet(sheet, BUDGET_SHEET)
    years = int(periods[-1][1:periods[-1].index("Q")]) if periods and periods[0][0] == "Y" else 1
    for year in range(4, years + 1):
        for quarter in (1, 2, 3, 4):
            column = sheet.max_column + 1
            sheet.cell(row=1, column=column, value=f"Y{year} Q{quarter}")
            sheet.column_dimensions[get_column_letter(column)].width = 18
    headers = [cell.value for cell in sheet[1]]
    one_year = bool(periods) and periods[0][0] == "Q"
    short = {code: label for code, label, _ in CATEGORY_LEGEND}
    units = dict(LineItem.UNIT_CHOICES)
    for item in items:
        split = {a.get("period"): a.get("amount") for a in item.allocations or []}
        sheet.append([item.fiscal_year, short.get(item.category, item.category), item.description, item.specification,
                      units.get(item.unit, item.unit), _number(item.quantity), _number(item.unit_cost), _number(item.amount)]
                     + [_number(split.get(_period_key(h, one_year))) for h in headers[8:]])
    # shortcut: Total is Excel's own Qty x Unit Cost (column H) on the blank rows; the import recomputes it anyway
    for row in range(sheet.max_row + 1, 2 + max(LIB_BLANK_ROWS, len(items))):
        sheet.cell(row=row, column=8, value=f'=IF(AND(F{row}<>"",G{row}<>""),F{row}*G{row},"")')

    _add_category_legend(wb)
    legend = wb["Legend"]
    legend.append([])
    legend.append([f"Budget periods of this project (Start Date: {start_date}, Target End Date: {target_end_date})"])
    legend.cell(row=legend.max_row, column=1).font = Font(bold=True)
    for period in periods:
        legend.append([_period_header(period), _period_meaning(period)])
    legend.append(["Leave the other Y/Q columns of the Budget Requirements sheet blank; the periods must add up to the Total."])
    _add_dropdowns(wb)
    for worksheet in wb.worksheets:
        for cell in worksheet[1]:
            cell.font = Font(bold=True)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _number(value):
    return None if value in (None, "") else float(value)


def _first_message(exc):
    detail = exc.detail
    while isinstance(detail, (dict, list)):
        detail = next(iter(detail.values())) if isinstance(detail, dict) else detail[0]
    return str(detail)


def _lib_layout(wb, periods):
    """Where read_lib finds things: (sheet name, header row, [(label, field, kind, choices, column)], Total column,
    {column: period, or None for a period outside the project}, errors)."""
    one_year = bool(periods) and periods[0][0] == "Q"
    if BUDGET_SHEET in wb.sheetnames:
        name, columns, header = BUDGET_SHEET, TABLE_SHEETS[BUDGET_SHEET][:8], 1
        sheet = wb[name]
    elif LIB_SHEET in wb.sheetnames:
        name, columns = LIB_SHEET, LIB_COLUMNS
        sheet = wb[name]
        header = next((r for r in range(1, min(sheet.max_row, 30) + 1) if _norm(sheet.cell(row=r, column=1).value or "") == "particulars"), None)
    else:
        return None, None, [], None, {}, [{"sheet": None, "row": None, "field": "file",
                                           "message": f"Missing the '{BUDGET_SHEET}' sheet; use the Download LIB Template file."}]

    def error(field, message):
        return {"sheet": name, "row": header, "field": field, "message": message}

    if header is None:
        return name, None, [], None, {}, [error("Header", "Missing the header row (Particulars, Item, ...); use the Download LIB Template file.")]
    titles = [sheet.cell(row=header, column=c).value for c in range(1, sheet.max_column + 1)]
    errors = [error(label, f"Column {i + 1} must be '{label}'.")
              for i, (label, *_) in enumerate(columns) if _norm(titles[i] if i < len(titles) else "") != _norm(label)]
    fields = [(label, field, kind, choices, i) for i, (label, field, kind, choices) in enumerate(columns) if field != "amount"]
    total = next(i for i, (_, field, *_) in enumerate(columns) if field == "amount")
    if name == LIB_SHEET:
        keys = {c: str(t).replace(" ", "").upper() for c, t in enumerate(titles) if c >= len(columns) and t not in (None, "")}
        unknown = []
    else:
        keys = {c: _period_key(t, one_year) for c, t in enumerate(titles) if c >= len(columns) and t not in (None, "")}
        unknown = [str(titles[c]) for c, key in keys.items() if key is None]
    found = list(keys.values())
    # Task 51: a period without a column is 0.00 on Budget Requirements, as in Upload via Excel; the old LIB sheet stays exact
    missing = [p for p in periods if p not in found] if name == LIB_SHEET else []
    if unknown:
        errors.append(error("Budget periods", f"Column(s) {', '.join(unknown)} are not period columns (Y1 Q1, Y1 Q2, ...)."))
    if missing:
        errors.append(error("Budget periods", f"Missing period column(s) {', '.join(missing)}. "
                                              f"This project's periods are {', '.join(periods)}."))
    if name == LIB_SHEET:
        extra = [p for p in dict.fromkeys(found) if p not in periods]
        if extra:  # the Task 12 template had only the project's own periods
            errors.append(error("Budget periods", f"Period column(s) {', '.join(extra)} are outside this project's Start and End Dates ({', '.join(periods)})."))
    if len([k for k in found if k]) != len({k for k in found if k}):
        errors.append(error("Budget periods", "A period column appears more than once."))
    period_columns = {c: (key if key in periods else None) for c, key in keys.items() if key}
    return name, header, fields, total, period_columns, errors


def read_lib(file_obj, periods):
    """Step 4's LIB import as Manual Entry LIB rows, checked with the LineItem rules (catalog Item, Qty x Unit Cost, a
    split over exactly the project's periods). Reads the Budget Requirements sheet (client Task 50; a whole Upload via
    Excel workbook works too) or a Task 12 template's LIB sheet. Returns (rows, errors); all-or-nothing, nothing is saved."""
    try:
        wb = openpyxl.load_workbook(file_obj, data_only=True)
    except Exception as exc:  # not an xlsx, or corrupted
        return [], [{"sheet": None, "row": None, "field": "file", "message": f"Could not read workbook: {exc}"}]
    name, header, fields, total, period_columns, errors = _lib_layout(wb, periods)
    if errors:
        return [], errors
    sheet = wb[name]
    labels = {field: label for label, field, *_ in fields}
    total_label = (LIB_COLUMNS if name == LIB_SHEET else TABLE_SHEETS[BUDGET_SHEET])[total][0]

    def error(row, field, message):
        return {"sheet": name, "row": row, "field": field, "message": message}

    rows = []
    for r in range(header + 1, sheet.max_row + 1):
        if _norm(sheet.cell(row=r, column=1).value or "") == _norm(LIB_LEGEND):
            break
        # Total is only Excel's own Qty x Unit Cost; the row is read from the other cells
        cells = [sheet.cell(row=r, column=c).value for c in range(1, sheet.max_column + 1)]
        if all(v is None or (isinstance(v, str) and not v.strip()) for i, v in enumerate(cells) if i != total):
            continue
        data, row_errors = {}, []
        for label, field, kind, choices, i in fields:
            try:
                data[field] = _convert(cells[i], kind, choices)
            except CellError as exc:
                row_errors.append(error(r, label, str(exc)))
        for label, field, *_ in fields:
            if field not in ("specification", "fiscal_year") and data.get(field) is None and not any(e["field"] == label for e in row_errors):
                row_errors.append(error(r, label, f"Enter the {label.replace(' (₱)', '')}."))
        if data.get("specification") and len(data["specification"]) > 300:
            row_errors.append(error(r, labels["specification"], "Keep it to 300 characters."))
        for field in ("quantity", "unit_cost"):
            if data.get(field) is not None and Decimal(data[field]) < 0:
                row_errors.append(error(r, labels[field], "Can't be negative."))
        if not row_errors:
            try:
                data["description"] = catalog_item_name(data["category"], data["description"])
            except ValidationError as exc:
                row_errors.append(error(r, labels["description"], _first_message(exc)))
        if not row_errors:
            amount = line_total(data["quantity"], data["unit_cost"])
            split = []
            for column, period in period_columns.items():
                header_label = sheet.cell(row=header, column=column + 1).value
                try:
                    value = _convert(cells[column] if column < len(cells) else None, "decimal", None)
                except CellError as exc:
                    row_errors.append(error(r, header_label, str(exc)))
                    continue
                if period:
                    split.append({"period": period, "amount": value or "0"})
                elif value and Decimal(value):
                    row_errors.append(error(r, header_label, f"Outside this project's Start and End Dates ({', '.join(periods)}); leave it blank."))
            if amount <= 0:
                row_errors.append(error(r, total_label, "Qty x Unit Cost must be more than 0."))
            if not row_errors:
                try:
                    data["allocations"] = clean_allocations(split, periods, amount)
                except ValidationError as exc:
                    row_errors.append(error(r, "Budget periods", _first_message(exc)))
            data["amount"] = str(amount)
        errors.extend(row_errors)
        if not row_errors:
            rows.append({"specification": "", **{k: v for k, v in data.items() if v is not None}})
    if not rows and not errors:
        errors.append(error(None, "Items", f"The {name} sheet has no items. Fill at least one row."))
    if errors:
        return [], errors
    order = ["category", "description", "specification", "unit", "quantity", "unit_cost", "amount", "allocations", "fiscal_year"]
    return [{k: row[k] for k in order if k in row} for row in rows], []


def _pick_account(data, staff_field, email_field, error):
    """Staff ID first, the e-mail for older templates (client 2026-10-28). Both filled must be the same account.
    Returns the account, or None (none given, or the conflict was reported through error)."""
    by_staff, by_email = data.pop(staff_field, None), data.get(email_field)
    if by_staff and by_email and by_staff != by_email:
        error("The Staff ID and the e-mail belong to two different RMIS accounts.")
        return None
    if by_staff:
        data[email_field] = by_staff
    return User.objects.filter(pk=data[email_field]).first() if data.get(email_field) else None


def _row_reported(errors, sheet, row):
    return any(e["sheet"] == sheet and e["row"] == row for e in errors)


def _fill_from_accounts(project_data, tables, errors):
    """Resolve the Project Leader and Project Team accounts. The leader's blank Gender/Contact No. are filled from the
    profile (filled cells are this project's own values); a team row's name and gender always come from its account.
    Client Task 45 (2026-11-06): the Project Leader's Staff ID and each team row's RMIS E-mail and Staff ID are required,
    and there is at most one Co-Project Leader, a Project Leader or Project Staff account (Carl's Q1, Q2)."""
    if "lead_staff_id" not in project_data and not any(e["sheet"] == "Project" and e["field"] == LEAD_STAFF_ID_LABEL for e in errors):
        errors.append({"sheet": "Project", "row": None, "field": LEAD_STAFF_ID_LABEL,
                       "message": "The Project Leader's Staff ID is required."})
    lead = _pick_account(project_data, "lead_staff_id", "lead", lambda message: errors.append(
        {"sheet": "Project", "row": None, "field": LEAD_STAFF_ID_LABEL, "message": message}))
    if lead:
        if lead.gender:
            project_data.setdefault("lead_gender", lead.gender)
        if lead.mobile_number:
            project_data.setdefault("contact_number", lead.mobile_number)
    co_leaders = 0
    for row_number, data in tables.get("Project Team", []):
        sheet = "Project Team"
        add = lambda field, message, row=row_number: errors.append({"sheet": sheet, "row": row, "field": field, "message": message})
        given = {"RMIS E-mail": "user" in data, "Staff ID": "user_staff_id" in data}
        reported = _row_reported(errors, sheet, row_number)
        member = _pick_account(data, "user_staff_id", "user", lambda message: add("Staff ID", message))
        if member:
            # Client Task 45: never the workbook's own name/gender, only the account's
            data["name"], data["gender"] = member.display_name, member.gender or ""
        if not reported and not _row_reported(errors, sheet, row_number):
            if not any(given.values()):
                add("RMIS E-mail", "Give the member's RMIS E-mail and Staff ID; the name and gender come from the account. "
                                   "Members without an RMIS account are added later in Edit Registration.")
            else:
                for field in [f for f, present in given.items() if not present]:
                    add(field, f"The member's {field} is required too.")
        if data.get("member_role") == "co_leader":
            co_leaders += 1
            problem = "A project has only one Co-Project Leader." if co_leaders > 1 else co_leader_problem(member)
            if problem:
                add("Role", problem)


def _serializer_errors(sheet, row, serializer_errors, labels):
    items = []
    for field, messages in serializer_errors.items():
        messages = messages if isinstance(messages, list) else [messages]
        for message in messages:
            items.append({"sheet": sheet, "row": row, "field": labels.get(field, field), "message": str(message)})
    return items


def import_workbook(file_obj, request):
    """Create one project from a filled template. Returns (project, errors); on any error nothing should be kept,
    so the caller must run this inside transaction.atomic() and roll back when errors is non-empty."""
    try:
        wb = openpyxl.load_workbook(file_obj, data_only=True)
    except Exception as exc:  # not an xlsx, or corrupted
        return None, [{"sheet": None, "row": None, "field": "file", "message": f"Could not read workbook: {exc}"}]
    if "Project" not in wb.sheetnames:
        return None, [{"sheet": None, "row": None, "field": "file", "message": "Missing the 'Project' sheet; use the RMIS template."}]

    errors = []
    context = {"request": request, "defer_scope": True}
    project_data = _read_project_sheet(wb["Project"], errors)
    tables = {name: _read_table(wb[name], name, errors) for name in TABLE_SHEETS if name in wb.sheetnames}
    _check_work_plan(tables.get("Work Plan", []), errors)
    _fill_from_accounts(project_data, tables, errors)
    if errors:
        return None, errors

    serializer = ProjectSerializer(data=project_data, context=context)
    if not serializer.is_valid():
        labels = {field: label for label, field, *_ in PROJECT_FIELDS + LEGACY_PROJECT_FIELDS}
        return None, _serializer_errors("Project", None, serializer.errors, labels)
    project = serializer.save()
    for name_field, date_field, designation, role_code in ANNEX_A_SIGNATORIES:
        name = getattr(project, name_field)
        if name:
            ProjectEndorser.objects.create(
                project=project, name=name, designation=designation, role_code=role_code,
                signed_on=getattr(project, date_field),
            )

    budget = None
    for name, rows in tables.items():
        labels = {field: header for header, field, *_ in TABLE_SHEETS[name]} | {"allocations": "Y1 Q1 - Y3 Q4"}
        one_year = (allocation_periods(project) or ["Q1"])[0] == "Q1"
        for row_number, data in rows:
            data["project"] = project.pk
            if name == "Budget Requirements":
                fill_line_item_amount(data)
                split = [{"period": key[len("alloc_"):], "amount": data.pop(key)} for key in [k for k in data if k.startswith("alloc_")]]
                if one_year:
                    split = [{**a, "period": a["period"][2:]} if a["period"].startswith("Y1Q") else a for a in split]
                if split:
                    data["allocations"] = split
                if budget is None:
                    budget = LineItemBudgetSerializer(data={"project": project.pk}, context=context)
                    budget.is_valid(raise_exception=True)
                    budget = budget.save()
                data["budget"] = budget.pk
            row_serializer = TABLE_SERIALIZERS[name](data=data, context=context)
            if row_serializer.is_valid():
                row_serializer.save()
            else:
                errors.extend(_serializer_errors(name, row_number, row_serializer.errors, labels))
    user = request.user
    if budget is not None and not errors:
        log_registration_lib(user, budget, "Upload via Excel")
    if user.role and user.role.code in LEADER_ROLES and not leader_owns(user, project):
        errors.append({"sheet": "Project", "row": None, "field": "Project Leader E-mail Address", "message": (
            "Leaders can only upload a project they lead, one under a Program they lead (Program Code), "
            "or one with a Study Component they lead."
        )})
    return project, errors


def registration_draft(project, request):
    """The imported project and its tables as the API returns them, for Manual Entry to load and edit before it
    registers (client 2026-10-23). Read before the dry run rolls back; the frontend drops the ids."""
    context = {"request": request}

    def rows(serializer, queryset):
        return serializer(queryset.order_by("id"), many=True, context=context).data

    return {
        "project": ProjectSerializer(project, context=context).data,
        "team": rows(ProjectTeamMemberSerializer, project.team_members),
        "studies": rows(StudySerializer, project.studies),
        "outputs": rows(ExpectedOutputSerializer, project.expected_outputs),
        "beneficiaries": rows(TargetBeneficiarySerializer, project.target_beneficiaries),
        "milestones": rows(WorkPlanMilestoneSerializer, project.milestones),
        "endorsers": rows(ProjectEndorserSerializer, project.endorsers),
        "line_items": rows(LineItemSerializer, LineItem.objects.filter(budget__project=project)),
    }


# Client Task 45 (2026-11-06): Upload via Excel opens the workbook in the Manual Entry wizard as a review before
# anything is registered. Where each sheet's rows go in the wizard's draft.
DRAFT_TABLES = {"Project Team": "team", "Study Components": "studies", "Expected Outputs (6Ps)": "outputs",
                "Target Beneficiaries": "beneficiaries", "Budget Requirements": "line_items", "Work Plan": "milestones"}
# The project fields of the draft and their blank values (the API's own shape, as Manual Entry loads it)
DRAFT_PROJECT_BLANK = {
    "title": "", "funding_type": "", "lead": None, "lead_gender": "", "contact_number": "", "ntp_number": "",
    "ntp_date": None, "toe_signed_date": None, "is_dry_research": None, "start_date": None, "target_end_date": None,
    "rde_thrust": "", "rde_priority": "", "sdgs": [], "sectors": [], "sector_other": "", "is_continuing": False,
    "continuing_year": None, "research_type": "", "research_priority_area": "", "research_typology": [], "campus": "",
    "implementing_unit": "", "college": "", "total_cost": None, "cooperating_agencies": "", "objectives": "",
    "background": "", "methodology": "", "socio_economic_significance": "", "monitoring_evaluation": "", "references": "",
    "description": "", "expected_outcomes": "", "expected_impacts": "", "proposal_submitted_on": None,
    "proposal_reviewed_on": None, "proposal_approved_on": None, "reviewing_body": "",
}


def _check_budget_rows(project_data, rows, errors):
    """The LIB rules a Budget Requirements row would meet on registration, without saving: an active LIB Item of its
    class, and a split over the project's periods that adds up to Qty x Unit Cost. Leaves each row as a draft line item."""
    periods = allocation_periods(Project(start_date=project_data.get("start_date"), target_end_date=project_data.get("target_end_date")))
    one_year = (periods or ["Q1"])[0] == "Q1"
    for row_number, data in rows:
        add = lambda field, exc, row=row_number: errors.append(
            {"sheet": "Budget Requirements", "row": row, "field": field, "message": _first_message(exc)})
        fill_line_item_amount(data)
        split = [{"period": key[len("alloc_"):], "amount": data.pop(key)} for key in [k for k in data if k.startswith("alloc_")]]
        if one_year:
            split = [{**a, "period": a["period"][2:]} if a["period"].startswith("Y1Q") else a for a in split]
        data["allocations"] = split
        if data.get("category") and data.get("description"):
            try:
                data["description"] = catalog_item_name(data["category"], data["description"])
            except ValidationError as exc:
                add("Particulars", exc)
        if split and periods:
            try:
                data["allocations"] = clean_allocations(split, periods, Decimal(data["amount"]))
            except ValidationError as exc:
                add("Y1 Q1 - Y3 Q4", exc)


def _issue_keys(errors, tables):
    """Each issue also names its draft field (Project sheet) or table and row index, so the wizard can show it."""
    labels = {_norm(label): field for label, field, *_ in PROJECT_FIELDS + LEGACY_PROJECT_FIELDS}
    labels[_norm(LEAD_STAFF_ID_LABEL)] = "lead"
    labels[_norm("Project Leader E-mail Address")] = "lead"
    positions = {name: {row: i for i, (row, _) in enumerate(rows)} for name, rows in tables.items()}
    for error in errors:
        if error["sheet"] == "Project":
            error["key"] = labels.get(_norm(error["field"] or ""), "project")
        elif error["sheet"] in DRAFT_TABLES:
            error["key"] = DRAFT_TABLES[error["sheet"]]
            error["index"] = positions.get(error["sheet"], {}).get(error["row"])
    return errors


def review_workbook(file_obj):
    """Upload via Excel review (client Task 45): every value the workbook holds, read with the import's rules but
    saved nowhere, as Manual Entry's draft, plus the issues found. A cell that fails (e.g. a College Unit the System
    Admin removed) is left blank in the draft and listed, never replaced by another value. Registering then goes
    through Manual Entry's own POST projects/, which checks everything again. Returns (draft, issues); draft is None
    when the file can't be read."""
    try:
        wb = openpyxl.load_workbook(file_obj, data_only=True)
    except Exception as exc:  # not an xlsx, or corrupted
        return None, [{"sheet": None, "row": None, "field": "file", "message": f"Could not read workbook: {exc}"}]
    if "Project" not in wb.sheetnames:
        return None, [{"sheet": None, "row": None, "field": "file", "message": "Missing the 'Project' sheet; use the RMIS template."}]
    errors = []
    project_data = _read_project_sheet(wb["Project"], errors)
    tables = {name: _read_table(wb[name], name, errors) for name in TABLE_SHEETS if name in wb.sheetnames}
    _check_work_plan(tables.get("Work Plan", []), errors)
    _fill_from_accounts(project_data, tables, errors)
    _check_budget_rows(project_data, tables.get("Budget Requirements", []), errors)

    project = {**DRAFT_PROJECT_BLANK, **{k: v for k, v in project_data.items() if k in DRAFT_PROJECT_BLANK}}
    lead = User.objects.filter(pk=project["lead"]).first() if project["lead"] else None
    if lead and not project["campus"]:
        project["campus"] = lead.campus  # a blank Campus is the leader's, as on registration
    rows = lambda name: [data for _, data in tables.get(name, [])]
    draft = {
        "project": project,
        "team": [{"id": i, "member_role": d.get("member_role", "member"), "name": d.get("name", ""), "gender": d.get("gender", ""),
                  "user": d.get("user")} for i, d in enumerate(rows("Project Team"), start=1)],
        "studies": [{"id": i, "title": d.get("title", ""), "lead": d.get("lead")} for i, d in enumerate(rows("Study Components"), start=1)],
        "outputs": [{"id": i, "category": d.get("category", ""), "description": d.get("description", ""),
                     "target_count": d.get("target_count", "")} for i, d in enumerate(rows("Expected Outputs (6Ps)"), start=1)],
        "beneficiaries": [{"id": i, "group": d.get("group", ""), "description": d.get("description", ""), "total": d.get("total", "")}
                          for i, d in enumerate(rows("Target Beneficiaries"), start=1)],
        "milestones": [{"id": i, "title": d.get("title", ""), "start_date": d.get("start_date"), "target_date": d.get("target_date", ""),
                        "tasks_total": 0} for i, d in enumerate(rows("Work Plan"), start=1)],
        "line_items": [{"id": i, "category": d.get("category", ""), "description": d.get("description", ""),
                        "specification": d.get("specification", ""), "unit": d.get("unit", ""), "quantity": d.get("quantity"),
                        "unit_cost": d.get("unit_cost"), "amount": d.get("amount"), "allocations": d.get("allocations", []),
                        "fiscal_year": d.get("fiscal_year")} for i, d in enumerate(rows("Budget Requirements"), start=1)],
        "endorsers": [{"id": i, "role_code": role_code, "user": None, "name": project_data[name_field], "designation": designation,
                       "signed_on": project_data.get(date_field)}
                      for i, (name_field, date_field, designation, role_code) in enumerate(
                          [a for a in ANNEX_A_SIGNATORIES if project_data.get(a[0])], start=1)],
    }
    return draft, _issue_keys(errors, tables)


def proposal_preview(project):
    """The saved project in the shape of the frontend's SF-018 ProposalPreview, for ?dry_run=1 (client meeting
    2026-10-01, #9). Read before the dry run rolls back, so it shows exactly what an upload would register."""
    def person(member):
        return {"name": member.name, "gender": member.gender}

    team = list(project.team_members.order_by("id"))
    line_items = LineItem.objects.filter(budget__project=project).order_by("id")
    lib = project.budgets.filter(is_current=True).select_related("endorsed_by", "certified_by").first()
    return {
        "title": project.title,
        "lead_name": project.lead.get_full_name() or project.lead.email,
        "lead_email": project.lead.email,
        "lead_gender": project.lead_gender,
        "co_leaders": [person(m) for m in team if m.member_role == "co_leader"],
        "team": [person(m) for m in team if m.member_role != "co_leader"],
        "start_date": str(project.start_date or ""),
        "target_end_date": str(project.target_end_date or ""),
        "total_cost": str(project.total_cost or ""),
        "implementing_unit": project.implementing_unit,
        "campus": project.campus,
        "college": project.college,
        "contact_number": project.contact_number,
        "cooperating_agencies": project.cooperating_agencies,
        "sectors": project.sectors,
        "sector_other": project.sector_other,
        "is_continuing": project.is_continuing,
        "continuing_year": str(project.continuing_year or ""),
        "research_type": project.research_type,
        "is_dry_research": project.is_dry_research,
        "study_titles": [s.title for s in project.studies.order_by("id")],
        "rde_thrust": project.rde_thrust,
        "rde_priority": project.rde_priority,
        "research_priority_area": project.research_priority_area,
        "research_typology": project.research_typology,
        "sdgs": project.sdgs,
        "background": project.background,
        # Manual entry saves "1. ...\n2. ..."; the preview numbers them itself
        "objectives": objective_items(project.objectives),
        "methodology": project.methodology,
        "outputs": [
            {"category": o.category, "description": o.description, "target_count": o.target_count}
            for o in project.expected_outputs.order_by("id")
        ],
        "socio_economic_significance": project.socio_economic_significance,
        "beneficiaries": [
            {"group": b.group, "description": b.description, "total": b.total}
            for b in project.target_beneficiaries.order_by("id")
        ],
        "monitoring_evaluation": project.monitoring_evaluation,
        "references": project.references,
        "budget": [
            {"category": i.category, "description": i.description, "specification": i.specification,
             "unit": i.get_unit_display() if i.unit else "",
             "quantity": float(i.quantity) if i.quantity is not None else None,
             "unit_cost": float(i.unit_cost) if i.unit_cost is not None else None, "total": float(i.amount),
             "allocations": [{"period": a["period"], "amount": float(a["amount"])} for a in i.allocations]}
            for i in line_items
        ],
        "allocation_periods": allocation_periods(project) or [],
        # Client 2026-10-18: SF-018 shows who endorsed (CRC Chair) and certified (Budget Officer) the LIB, names only
        "lib_endorsed_by": lib.endorsed_by.display_name if lib and lib.endorsed_by else "",
        "lib_certified_by": lib.certified_by.display_name if lib and lib.certified_by else "",
        "work_plan": [
            {"title": m.title, "start_date": str(m.start_date or "") or None, "target_date": str(m.target_date or "") or None}
            for m in project.milestones.order_by("id")
        ],
        "endorsers": [
            {"name": e.name, "designation": e.designation, "signed_on": str(e.signed_on) if e.signed_on else None}
            for e in project.endorsers.order_by("id")
        ],
        "proposal_submitted_on": str(project.proposal_submitted_on or ""),
    }
