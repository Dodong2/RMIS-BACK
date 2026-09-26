import datetime
import io

import openpyxl

from accounts.testing import RMISTestCase
from budget_lib.models import LineItem
from research_projects.models import Program, Project


def project_payload(lead, **overrides):
    data = {
        "title": "Bridging Academia and Communities", "project_code": "LSPU-1", "funding_type": "core_funded",
        "lead": lead.id, "sdgs": [4, 17], "sectors": ["education"],
    }
    data.update(overrides)
    return data


class ManualRegistrationTests(RMISTestCase):
    def test_registrar_can_register_a_project_with_several_sectors(self):
        admin, leader = self.make_user("system_admin"), self.make_user("project_leader")

        response = self.client_for(admin).post(
            "/api/projects/", project_payload(leader, sectors=["education", "community_development"]), format="json"
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["sectors"], ["community_development", "education"])

    def test_others_sector_needs_a_description(self):
        admin, leader = self.make_user("system_admin"), self.make_user("project_leader")

        response = self.client_for(admin).post("/api/projects/", project_payload(leader, sectors=["others"]), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("sector_other", response.data)

    def test_continuing_proposal_needs_its_year(self):
        admin, leader = self.make_user("system_admin"), self.make_user("project_leader")

        response = self.client_for(admin).post("/api/projects/", project_payload(leader, is_continuing=True), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("continuing_year", response.data)

    def test_roles_outside_module_2_cannot_register(self):
        leader = self.make_user("project_leader")

        response = self.client_for(self.make_user("finance_budget")).post("/api/projects/", project_payload(leader), format="json")

        self.assertEqual(response.status_code, 403)

    def test_project_leader_cannot_register_a_project_for_someone_else(self):
        leader, other = self.make_user("project_leader"), self.make_user("project_leader")

        response = self.client_for(leader).post("/api/projects/", project_payload(other), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Project.objects.exists())

    def test_project_leader_cannot_edit_another_leaders_project(self):
        leader, other = self.make_user("project_leader"), self.make_user("project_leader")
        project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=other)

        response = self.client_for(leader).patch(f"/api/projects/{project.id}/", {"title": "Hijacked"}, format="json")

        self.assertEqual(response.status_code, 400)
        project.refresh_from_db()
        self.assertEqual(project.title, "P")

    def test_line_item_quarters_must_add_up_to_the_amount(self):
        admin, leader = self.make_user("system_admin"), self.make_user("project_leader")
        project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=leader)
        budget = self.client_for(admin).post("/api/budget/budgets/", {"project": project.id}, format="json").data

        response = self.client_for(admin).post("/api/budget/line-items/", {
            "budget": budget["id"], "category": "mooe", "description": "Travel", "amount": "100",
            "q1_amount": "30", "q2_amount": "30",
        }, format="json")

        self.assertEqual(response.status_code, 400)


class ExcelImportTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.make_user("system_admin")
        self.leader = self.make_user("project_leader", email="leader@lspu.test")
        template = self.client_for(self.admin).get("/api/projects/import-template/")
        self.assertEqual(template.status_code, 200)
        self.workbook = openpyxl.load_workbook(io.BytesIO(template.content))

    def fill_project(self, **values):
        defaults = {
            "Title": "Bridging Academia and Communities",
            "LSPU Faculty Research Number (Project Code)": "LSPU-X1",
            "Project Leader E-mail Address": "Leader@LSPU.test",
            "Project Leader Gender": "Female",
            "Start Date": datetime.datetime(2026, 1, 1),
            "Sector": "Education, Community Development",
            "Sustainable Development Goals (SDGs)": "4, 11, 17",
            "College Unit": "CTE",
        }
        defaults.update(values)
        for row in self.workbook["Project"].iter_rows(min_row=2):
            if row[0].value in defaults:
                row[1].value = defaults[row[0].value]

    def upload(self, user=None):
        buffer = io.BytesIO()
        self.workbook.save(buffer)
        buffer.seek(0)
        buffer.name = "registration.xlsx"
        return self.client_for(user or self.admin).post("/api/projects/import/", {"file": buffer}, format="multipart")

    def test_filled_template_registers_the_project_and_its_tables(self):
        self.fill_project()
        self.workbook["Project Team"].append(["Co-Project Leader", "Archieval M. Jain", "Male", None])
        self.workbook["Project Team"].append(["Team Member", "EIU Coordinators", None, None])
        self.workbook["Expected Outputs (6Ps)"].append(["Patent", "Novel technology", 1])
        self.workbook["Target Beneficiaries"].append(["Community beneficiaries", "Farmers", 2000])
        self.workbook["Budget Requirements"].append([2026, "MOOE", "Travel Expenses", 5000, 2500, 2500, None, None, "LSPU"])
        self.workbook["Work Plan"].append(["Logistic preparations", datetime.datetime(2026, 1, 1), datetime.datetime(2026, 3, 31)])

        response = self.upload()

        self.assertEqual(response.status_code, 201, response.data)
        project = Project.objects.get(project_code="LSPU-X1")
        self.assertEqual(project.lead, self.leader)
        self.assertEqual(project.sectors, ["community_development", "education"])
        self.assertEqual(project.team_members.count(), 2)
        self.assertEqual(project.expected_outputs.get().category, "patents")
        self.assertEqual(project.target_beneficiaries.get().total, 2000)
        self.assertEqual(LineItem.objects.get(budget__project=project).amount, 10000)
        self.assertEqual(project.milestones.count(), 1)

    def test_any_bad_row_rolls_back_the_whole_import_and_lists_the_error(self):
        self.fill_project()
        self.workbook["Expected Outputs (6Ps)"].append(["Not a 6P", "x", 1])

        response = self.upload()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["errors"][0]["sheet"], "Expected Outputs (6Ps)")
        self.assertFalse(Project.objects.exists())

    def test_a_non_workbook_file_is_rejected_cleanly(self):
        buffer = io.BytesIO(b"not an excel file")
        buffer.name = "notes.xlsx"

        response = self.client_for(self.admin).post("/api/projects/import/", {"file": buffer}, format="multipart")

        self.assertEqual(response.status_code, 400)

    def test_leader_can_upload_their_own_project(self):
        self.fill_project()

        response = self.upload(self.leader)

        self.assertEqual(response.status_code, 201, response.data)

    def test_leader_cannot_upload_a_project_led_by_someone_else(self):
        self.make_user("project_leader", email="other@lspu.test")
        self.fill_project(**{"Project Leader E-mail Address": "other@lspu.test"})

        response = self.upload(self.leader)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Project.objects.exists())

    def test_program_leader_can_upload_under_their_own_program(self):
        program_leader = self.make_user("program_leader")
        Program.objects.create(code="PROG-1", title="Program", funding_type="core_funded", lead=program_leader)
        self.make_user("project_leader", email="other@lspu.test")
        self.fill_project(**{"Project Leader E-mail Address": "other@lspu.test", "Program Code (if under a Program)": "prog-1"})

        response = self.upload(program_leader)

        self.assertEqual(response.status_code, 201, response.data)
