"""Upload via Excel review (client Task 45-B, 2026-11-06): ?review=1 returns every value of the workbook as Manual
Entry's draft plus its issues, and saves nothing. Also the Co-Project Leader rule (Carl's Q1) shared with Manual Entry."""
import datetime
import io

import openpyxl

from accounts.testing import RMISTestCase
from budget_lib.models import BudgetEventLog, LineItem
from research_projects.models import CollegeUnit, CooperatingAgency, Project, ProjectTeamMember, RdeThrust
from research_projects.rde_agenda import seed_rde_agenda

from . import tests as base


class ExcelReviewTests(RMISTestCase):
    fill_project = base.ExcelImportTests.fill_project

    def setUp(self):
        super().setUp()
        self.admin = self.make_user("system_admin")
        self.leader = self.make_user("project_leader", email="leader@lspu.test", staff_id="111111", campus="Siniloan",
                                     gender="female", first_name="Lea", last_name="Dimaano")
        self.staff = self.make_user("project_staff", email="ben@lspu.test", staff_id="222222", gender="male",
                                    first_name="Ben", last_name="Reyes")
        CollegeUnit.objects.create(name="CTE")
        seed_rde_agenda(RdeThrust)
        CooperatingAgency.objects.create(name="DOST-PCAARRD")
        self.workbook = openpyxl.load_workbook(io.BytesIO(self.client_for(self.admin).get("/api/projects/import-template/").content))

    def review(self, user=None):
        buffer = io.BytesIO()
        self.workbook.save(buffer)
        buffer.seek(0)
        buffer.name = "registration.xlsx"
        return self.client_for(user or self.admin).post("/api/projects/import/?review=1", {"file": buffer}, format="multipart")

    def issues(self, response):
        return [(i["key"], i.get("index"), i["field"]) for i in response.data["issues"]]

    def test_a_clean_workbook_comes_back_as_the_wizard_draft_and_nothing_is_saved(self):
        self.fill_project(Campus=None, **{"Cooperating Agency/ies": "DOST-PCAARRD"})
        self.workbook["Project Team"].append(["Co-Project Leader", "ben@lspu.test", "222222"])
        self.workbook["Study Components"].append(["Study on soils", None])
        self.workbook["Expected Outputs (6Ps)"].append(["Patent", "Novel technology", 1])
        self.workbook["Target Beneficiaries"].append(["Farmers", "Rice farmers", 200])
        self.workbook["Budget Requirements"].append([2026, "MOOE", "traveling expenses - local", None, "pax", 4, 2500, None, 10000])
        self.workbook["Work Plan"].append(["Logistic preparations", datetime.datetime(2026, 1, 1), datetime.datetime(2026, 3, 31)])

        response = self.review()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["issues"], [])
        draft = response.data["draft"]
        project = draft["project"]
        self.assertEqual((project["title"], project["ntp_number"], project["lead"], project["campus"], project["sdgs"]),
                         ("Bridging Academia and Communities", "LSPU-X1", self.leader.pk, "Siniloan", [4, 11, 17]))
        self.assertEqual((project["lead_gender"], project["cooperating_agencies"]), ("female", "DOST-PCAARRD"))
        self.assertEqual(draft["team"], [{"id": 1, "member_role": "co_leader", "name": "Ben Reyes", "gender": "male", "user": self.staff.pk}])
        line = draft["line_items"][0]
        self.assertEqual((line["description"], line["amount"], line["allocations"][0]),
                         ("Traveling Expenses - Local", "10000.00", {"period": "Q1", "amount": "10000.00"}))
        self.assertEqual(draft["milestones"][0]["title"], "Logistic preparations")
        self.assertEqual((Project.objects.count(), LineItem.objects.count(), BudgetEventLog.objects.count()), (0, 0, 0))

    def test_a_value_no_longer_in_the_admin_list_is_left_blank_and_listed(self):
        self.fill_project(**{"College Unit - Implementing Unit": "College of Removed Things", "Campus": "Calamba"})
        response = self.review()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sorted(self.issues(response)), [("campus", None, "Campus"),
                                                         ("implementing_unit", None, "College Unit - Implementing Unit")])
        project = response.data["draft"]["project"]
        self.assertEqual((project["implementing_unit"], project["campus"], project["title"]),
                         ("", "Siniloan", "Bridging Academia and Communities"))  # blank Campus = the leader's, never a guess

    def test_the_staff_ids_are_required(self):
        self.fill_project(**{"Project Leader Staff ID": None})
        self.workbook["Project Team"].append(["Team Member", "ben@lspu.test", None])
        self.workbook["Project Team"].append(["Team Member", None, None])
        response = self.review()
        self.assertEqual(self.issues(response), [("lead", None, "Project Leader Staff ID"), ("team", 0, "Staff ID"),
                                                 ("team", 1, "RMIS E-mail")])
        self.assertEqual(response.data["draft"]["project"]["lead"], self.leader.pk)  # the e-mail still found the account
        self.assertEqual([t["name"] for t in response.data["draft"]["team"]], ["Ben Reyes", ""])

    def test_staff_id_and_e_mail_of_different_accounts(self):
        self.fill_project()
        self.workbook["Project Team"].append(["Team Member", "leader@lspu.test", "222222"])
        response = self.review()
        self.assertEqual(self.issues(response), [("team", 0, "Staff ID")])
        self.assertIn("two different RMIS accounts", response.data["issues"][0]["message"])

    def test_one_co_leader_with_a_leader_or_staff_account(self):
        finance = self.make_user("finance_budget", email="fin@lspu.test", staff_id="444444")
        self.fill_project()
        self.workbook["Project Team"].append(["Co-Project Leader", "fin@lspu.test", "444444"])
        self.workbook["Project Team"].append(["Co-Project Leader", "ben@lspu.test", "222222"])
        response = self.review()
        issues = response.data["issues"]
        self.assertEqual([(i["index"], i["field"]) for i in issues], [(0, "Role"), (1, "Role")])
        self.assertIn(f"{finance.display_name} can't be the Co-Project Leader", issues[0]["message"])
        self.assertEqual(issues[1]["message"], "A project has only one Co-Project Leader.")

    def test_budget_rows_are_checked_like_registration(self):
        self.fill_project()
        self.workbook["Budget Requirements"].append([2026, "MOOE", "Common Office Supplies", None, "pax", 1, 100, None, 100])
        self.workbook["Budget Requirements"].append([2026, "MOOE", "Traveling Expenses - Local", None, "pax", 4, 2500, None, 9000])
        response = self.review()
        self.assertEqual(self.issues(response), [("line_items", 0, "Particulars"), ("line_items", 1, "Y1 Q1 - Y3 Q4")])
        self.assertEqual(response.data["draft"]["line_items"][0]["description"], "Common Office Supplies")  # kept as typed

    def test_bad_cells_name_their_row_and_unreadable_files_are_refused(self):
        self.fill_project(**{"Start Date": "someday"})
        self.workbook["Work Plan"].append(["Logistic preparations", None, None])
        response = self.review()
        self.assertEqual(self.issues(response), [("start_date", None, "Start Date"), ("milestones", 0, "End Date")])
        bad = self.client_for(self.admin).post("/api/projects/import/?review=1", {"file": io.BytesIO(b"not xlsx")}, format="multipart")
        self.assertEqual(bad.status_code, 400)

    def test_only_registration_roles_can_review(self):
        self.fill_project()
        self.assertEqual(self.review(self.staff).status_code, 403)
        self.assertEqual(self.review(self.leader).status_code, 200)


class CoLeaderRuleTests(RMISTestCase):
    """Carl's Q1 (2026-11-06): Manual Entry and Edit Registration share the rule through ProjectTeamMemberSerializer."""

    def setUp(self):
        super().setUp()
        self.admin, self.leader = self.make_user("system_admin"), self.make_user("project_leader")

    # Task 47-A: a registration needs a LIB whose Grand Total equals the Total Project/Study Cost (100,000.00)
    LIB = [{"category": "mooe", "description": "Traveling Expenses - Local", "fiscal_year": 2027, "unit": "lot",
            "quantity": "1", "unit_cost": "100000", "allocations": [{"period": "Q1", "amount": "100000"}]}]

    def register(self, team):
        return self.client_for(self.admin).post("/api/projects/", {**base.project_payload(self.leader), "team": team, "line_items": self.LIB},
                                                format="json")

    def row(self, user=None, name="Co"):
        return {"member_role": "co_leader", "name": name, "gender": "", "user": user.pk if user else None}

    def test_project_leader_project_staff_or_a_typed_name(self):
        for i, user in enumerate([self.make_user("project_leader"), self.make_user("project_staff"), None]):
            response = self.client_for(self.admin).post("/api/projects/", {
                **base.project_payload(self.leader), "ntp_number": f"NTP-CO-{i}", "title": f"Co-leader {i}", "team": [self.row(user)],
                "line_items": self.LIB}, format="json")
            self.assertEqual(response.status_code, 201, (i, response.data))

    def test_other_roles_and_a_second_co_leader_are_refused(self):
        response = self.register([self.row(self.make_user("finance_budget"))])
        self.assertEqual(response.status_code, 400)
        self.assertIn("can't be the Co-Project Leader", str(response.data))
        response = self.register([self.row(name="A"), self.row(name="B")])
        self.assertEqual(response.status_code, 400)
        self.assertIn("only one Co-Project Leader", str(response.data))
        self.assertFalse(Project.objects.exists())

    def test_editing_the_one_co_leader_is_fine(self):
        project_id = self.register([self.row(name="A")]).data["id"]
        member = ProjectTeamMember.objects.get(project_id=project_id)
        response = self.client_for(self.admin).patch(f"/api/project-team/{member.pk}/", {"name": "A. Cruz"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)  # its own row isn't "another" Co-Project Leader
