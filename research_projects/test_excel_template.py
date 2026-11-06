"""Upload via Excel template (client Task 45-A, 2026-11-06): dropdowns from the current System Admin data on a Lists
sheet, and a Project Team sheet without Name/Gender (they come from the member's RMIS account)."""
import io

import openpyxl
from openpyxl.utils import range_boundaries

from accounts.testing import RMISTestCase
from budget_lib.models import LibItem
from research_projects.models import CollegeUnit, FundingType, Project, RdeThrust
from research_projects.rde_agenda import seed_rde_agenda

from .tests import ExcelImportTests


class TemplateDropdownTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.make_user("system_admin")
        seed_rde_agenda(RdeThrust)

    def template(self):
        response = self.client_for(self.admin).get("/api/projects/import-template/")
        self.assertEqual(response.status_code, 200)
        return openpyxl.load_workbook(io.BytesIO(response.content))

    def dropdown(self, wb, sheet_name, cell):
        """The values a cell's list dropdown offers, read back from the Lists sheet range it points to."""
        sheet = wb[sheet_name]
        for validation in sheet.data_validations.dataValidation:
            if cell in validation.sqref:
                self.assertEqual(validation.type, "list")
                list_sheet, ref = validation.formula1.split("!")
                min_col, min_row, _, max_row = range_boundaries(ref.replace("$", ""))
                return [wb[list_sheet].cell(row=r, column=min_col).value for r in range(min_row, max_row + 1)]
        return None

    def value_cell(self, wb, label):
        return f"B{next(c.row for c in wb['Project']['A'] if c.value == label)}"

    def test_dropdowns_offer_the_current_admin_values(self):
        CollegeUnit.objects.create(code="CCS", title="College of Computer Studies")
        FundingType.objects.create(code="dost", name="DOST Grant")
        LibItem.objects.create(category="mooe", name="Seminar Kits")
        wb = self.template()

        self.assertIn("CCS - College of Computer Studies", self.dropdown(wb, "Project", self.value_cell(wb, "College Unit - Implementing Unit")))
        self.assertIn("DOST Grant", self.dropdown(wb, "Project", self.value_cell(wb, "Funding Type")))
        thrust, area = RdeThrust.objects.get(code="1").name, RdeThrust.objects.get(code="1.3").name
        self.assertIn(thrust, self.dropdown(wb, "Project", self.value_cell(wb, "RDE Thrust")))
        self.assertIn(area, self.dropdown(wb, "Project", self.value_cell(wb, "RDE Priority Area")))
        self.assertEqual(self.dropdown(wb, "Project", self.value_cell(wb, "Project Leader Gender")), ["Male", "Female"])
        self.assertEqual(self.dropdown(wb, "Project Team", "A2"), ["Co-Project Leader", "Team Member"])
        self.assertEqual(self.dropdown(wb, "Budget Requirements", "B501"), ["PS", "MOOE", "CO"])
        self.assertIn("Seminar Kits", self.dropdown(wb, "Budget Requirements", "C2"))

    def test_a_removed_admin_value_leaves_the_next_download(self):
        unit = CollegeUnit.objects.create(code="OLD", title="Old College")
        unit.delete()
        LibItem.objects.create(category="mooe", name="Retired Item", is_active=False)
        wb = self.template()
        self.assertNotIn("OLD - Old College", self.dropdown(wb, "Project", self.value_cell(wb, "College Unit - Implementing Unit")) or [])
        self.assertNotIn("Retired Item", self.dropdown(wb, "Budget Requirements", "C2"))

    def test_multi_value_fields_are_listed_but_typed(self):
        wb = self.template()
        self.assertIsNone(self.dropdown(wb, "Project", self.value_cell(wb, "Sector")))
        self.assertIsNone(self.dropdown(wb, "Project", self.value_cell(wb, "Sustainable Development Goals (SDGs)")))
        headers = [c.value for c in wb["Lists"][1]]
        self.assertIn("SDGs (type the numbers, comma-separated)", headers)
        self.assertIn("Sector (type, comma-separated)", headers)
        self.assertTrue(wb["Lists"].protection.sheet)

    def test_text_and_number_cells_have_no_dropdown(self):
        wb = self.template()
        self.assertIsNone(self.dropdown(wb, "Project", self.value_cell(wb, "Title")))
        self.assertIsNone(self.dropdown(wb, "Project Team", "B2"))  # RMIS E-mail
        self.assertIsNone(self.dropdown(wb, "Budget Requirements", "F2"))  # Qty


class ProjectTeamAccountTests(RMISTestCase):
    """Task 45-A: a Project Team row is an RMIS account; the workbook can't supply someone's name or gender."""

    fill_project = ExcelImportTests.fill_project
    upload = ExcelImportTests.upload

    def setUp(self):
        super().setUp()
        self.admin = self.make_user("system_admin")
        self.leader = self.make_user("project_leader", email="leader@lspu.test")
        CollegeUnit.objects.create(name="CTE")
        seed_rde_agenda(RdeThrust)
        self.workbook = self.template_workbook()

    def template_workbook(self):
        return openpyxl.load_workbook(io.BytesIO(self.client_for(self.admin).get("/api/projects/import-template/").content))

    def test_a_row_without_an_account_is_an_error(self):
        self.fill_project()
        self.workbook["Project Team"].append(["Team Member", None, None])
        self.workbook["Project Team"].append(["Team Member", "nobody@lspu.test", None])

        response = self.upload()

        self.assertEqual(response.status_code, 400)
        errors = [(e["row"], e["field"], e["message"][:30]) for e in response.data["errors"] if e["sheet"] == "Project Team"]
        self.assertEqual(errors, [(3, "RMIS E-mail", "No RMIS account with e-mail 'n"),
                                  (2, "RMIS E-mail", "Give the member's RMIS E-mail ")])
        self.assertFalse(Project.objects.exists())
