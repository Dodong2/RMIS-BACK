import datetime
import io

import openpyxl

from accounts.testing import RMISTestCase
from budget_lib.models import LineItem
from research_projects.models import Project, ProjectEndorser


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

    def test_crc_chair_can_register_a_project(self):
        leader = self.make_user("project_leader")

        response = self.client_for(self.make_user("crc_chair")).post("/api/projects/", project_payload(leader), format="json")

        self.assertEqual(response.status_code, 201, response.data)

    def test_project_leader_can_register_a_project_they_lead(self):
        """Client meeting 2026-10-01: the Project Leader registers their own approved project."""
        leader = self.make_user("project_leader")

        response = self.client_for(leader).post("/api/projects/", project_payload(leader), format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Project.objects.get().lead, leader)

    def test_project_leader_cannot_register_a_project_for_another_leader(self):
        leader, other = self.make_user("project_leader"), self.make_user("project_leader")

        response = self.client_for(leader).post("/api/projects/", project_payload(other), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("lead", response.data)
        self.assertFalse(Project.objects.exists())

    def test_program_and_study_leaders_still_cannot_register(self):
        leader = self.make_user("project_leader")

        for code in ("program_leader", "study_leader"):
            response = self.client_for(self.make_user(code)).post("/api/projects/", project_payload(leader), format="json")
            self.assertEqual(response.status_code, 403)
        self.assertFalse(Project.objects.exists())

    def test_leader_can_edit_their_own_project_but_not_the_crc_owned_fields(self):
        leader = self.make_user("project_leader")
        project = Project.objects.create(
            title="P", project_code="P-1", funding_type="core_funded", lead=leader, sdgs=[4], sectors=["education"],
        )
        client = self.client_for(leader)

        edited = client.patch(f"/api/projects/{project.id}/", {"title": "Better title", "project_code": "P-1"}, format="json")
        recoded = client.patch(f"/api/projects/{project.id}/", {"project_code": "P-2"}, format="json")

        self.assertEqual(edited.status_code, 200, edited.data)
        self.assertEqual(recoded.status_code, 400)
        self.assertIn("project_code", recoded.data)
        project.refresh_from_db()
        self.assertEqual((project.title, project.project_code), ("Better title", "P-1"))

    def test_project_leader_cannot_edit_another_leaders_project(self):
        leader, other = self.make_user("project_leader"), self.make_user("project_leader")
        project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=other)

        response = self.client_for(leader).patch(f"/api/projects/{project.id}/", {"title": "Hijacked"}, format="json")

        self.assertEqual(response.status_code, 400)
        project.refresh_from_db()
        self.assertEqual(project.title, "P")

    def test_code_available_sees_codes_outside_the_leaders_scope(self):
        """Client meeting 2026-10-01 (#3): a leader can't list other leaders' projects, so the wizard asks this."""
        leader, other = self.make_user("project_leader"), self.make_user("project_leader")
        Project.objects.create(title="P", project_code="LSPU-1", funding_type="core_funded", lead=other)
        client = self.client_for(leader)

        taken = client.get("/api/projects/code-available/", {"code": " LSPU-1 "})
        free = client.get("/api/projects/code-available/", {"code": "LSPU-2"})
        staff = self.client_for(self.make_user("project_staff")).get("/api/projects/code-available/", {"code": "LSPU-2"})

        self.assertEqual((taken.status_code, taken.data["available"]), (200, False))
        self.assertEqual((free.status_code, free.data["available"]), (200, True))
        self.assertEqual(staff.status_code, 403)

    def test_study_components_need_only_a_title(self):
        """Client meeting 2026-10-01 (#7): SF-018 lists Study 1, Study 2 by title; a study leader is optional."""
        leader, study_leader = self.make_user("project_leader"), self.make_user("study_leader")
        project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=leader)
        client = self.client_for(leader)

        untitled_lead = client.post("/api/studies/", {"project": project.id, "title": "Study 1"}, format="json")
        with_lead = client.post(
            "/api/studies/", {"project": project.id, "title": "Study 2", "lead": study_leader.id}, format="json"
        )
        wrong_role = client.post("/api/studies/", {"project": project.id, "title": "Study 3", "lead": leader.id}, format="json")

        self.assertEqual(untitled_lead.status_code, 201, untitled_lead.data)
        self.assertIsNone(untitled_lead.data["lead"])
        self.assertEqual(with_lead.status_code, 201, with_lead.data)
        self.assertEqual(wrong_role.status_code, 400)

    def test_endorser_rows_pick_a_role_and_an_account_of_that_role(self):
        """Client meeting 2026-10-01 (#8): Annex A is role -> account rows; text-only rows cover non-accounts."""
        leader, vp = self.make_user("project_leader"), self.make_user("vprei", first_name="Robert", last_name="Agatep")
        project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=leader)
        client = self.client_for(leader)

        picked = client.post("/api/project-endorsers/", {
            "project": project.id, "role_code": "vprei", "user": vp.id, "name": "Robert Agatep",
            "designation": "VPRDE", "signed_on": "2025-02-21",
        }, format="json")
        typed = client.post("/api/project-endorsers/", {
            "project": project.id, "name": "Adriel G. Roman", "designation": "Dean/Associate Dean",
        }, format="json")
        mismatched = client.post("/api/project-endorsers/", {
            "project": project.id, "role_code": "drd", "user": vp.id, "name": "Robert Agatep",
        }, format="json")
        outsider = self.client_for(self.make_user("project_leader")).post("/api/project-endorsers/", {
            "project": project.id, "name": "Someone",
        }, format="json")

        self.assertEqual(picked.status_code, 201, picked.data)
        self.assertEqual(typed.status_code, 201, typed.data)
        self.assertEqual(mismatched.status_code, 400)
        self.assertEqual(outsider.status_code, 400)
        self.assertEqual(ProjectEndorser.objects.filter(project=project).count(), 2)

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

    def test_annex_a_on_the_project_sheet_becomes_endorser_rows(self):
        self.fill_project(**{"Endorsed By (Dean/Associate Dean)": "Adriel G. Roman", "Recommending Approval (VPRDE)": "Robert C. Agatep"})

        response = self.upload()

        self.assertEqual(response.status_code, 201, response.data)
        rows = list(ProjectEndorser.objects.order_by("id").values_list("name", "designation", "role_code"))
        self.assertEqual(rows, [
            ("Adriel G. Roman", "Dean/Associate Dean", ""),
            ("Robert C. Agatep", "Vice President for Research, Development and Extension", "vprei"),
        ])

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

    def test_project_leader_can_import_a_project_they_lead(self):
        """Client meeting 2026-10-01: the Excel import follows the same rule as manual entry."""
        self.fill_project()

        response = self.upload(self.leader)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Project.objects.get().lead, self.leader)

    def test_project_leader_cannot_import_another_leaders_project(self):
        self.fill_project()
        other = self.make_user("project_leader")

        response = self.upload(other)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Project.objects.exists())

    def test_program_and_study_leaders_cannot_use_the_excel_import(self):
        self.fill_project()

        for code in ("program_leader", "study_leader"):
            self.assertEqual(self.upload(self.make_user(code)).status_code, 403)
        self.assertFalse(Project.objects.exists())
