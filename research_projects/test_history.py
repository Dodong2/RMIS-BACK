"""Client Task 65-C (2026-11-16): the History tab shows the recorded workflow, newest first, and only to users who
may open the project."""

from accounts.testing import RMISTestCase
from budget_lib.models import BudgetEventLog, BudgetReview, LineItemBudget
from research_projects.models import Project, ProjectStatusHistory


class ProjectHistoryTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader", campus="Siniloan", first_name="Ana", last_name="Cruz")
        self.crc = self.make_user("crc_chair", campus="Siniloan", first_name="Ben", last_name="Reyes")
        self.finance = self.make_user("finance_budget", campus="Siniloan", first_name="Cora", last_name="Santos")
        self.project = Project.objects.create(title="P", project_code="NTP-H", ntp_number="NTP-H", funding_type="institutional",
                                              lead=self.leader, campus="Siniloan")
        self.budget = LineItemBudget.objects.create(project=self.project, version_number=1, status="certified")
        self.url = f"/api/projects/{self.project.pk}/history/"

    def review(self, action, user, remarks=""):
        return BudgetReview.objects.create(budget=self.budget, action=action, acted_by=user, remarks=remarks)

    def history(self, user=None):
        response = self.client_for(user or self.leader).get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_a_project_with_no_records_shows_only_its_registration(self):
        rows = self.history()
        self.assertEqual([r["title"] for r in rows], ["Project registered in RMIS"])
        self.assertEqual(rows[0]["remarks"], "NTP NTP-H")

    def test_the_review_trail_newest_first_with_actor_role_and_remarks(self):
        self.review("submitted", self.leader)
        self.review("held_crc", self.crc, "Check the line item budget")
        self.review("resubmitted", self.leader, "Fixed")
        self.review("ready", self.crc)
        self.review("commented", self.finance, "Looks good")
        self.review("certification_started", self.finance)
        self.review("certified", self.finance)

        rows = self.history()
        self.assertEqual([r["title"] for r in rows], [
            "Certified by Finance/Accounting/Budget — project is Active",
            "Budget review started (certification in progress)",
            "Review comment",
            "Marked for checking by CRC/CRD — forwarded to Finance/Accounting/Budget for budget review",
            "Resubmitted after revision",
            "Returned for revision by CRC/CRD",
            "Submitted for review",
            "Project registered in RMIS",
        ])
        returned = rows[5]
        self.assertEqual((returned["actor_name"], returned["actor_role"], returned["remarks"]),
                         (self.crc.display_name, "CRC/CRD", "Check the line item budget"))
        self.assertEqual([r["kind"] for r in rows if r["kind"] != "status"], ["comment"])

    def test_finance_return_and_later_lib_version_are_labelled(self):
        v2 = LineItemBudget.objects.create(project=self.project, version_number=2, status="returned")
        BudgetReview.objects.create(budget=v2, action="held_budget", acted_by=self.finance, remarks="Check the LIB")
        self.assertEqual(self.history()[0]["title"], "Returned for revision by Finance/Accounting/Budget (LIB version 2)")

    def test_lib_edits_and_lifecycle_changes_are_separate_events(self):
        BudgetEventLog.objects.create(
            project=self.project, project_ref=self.project.pk, actor=self.finance, actor_name="Cora Santos",
            actor_email="c@x.ph", actor_role="finance_budget", event="LIB_LINE_ITEM_EDITED_BY_FINANCE",
            description="Finance/Accounting/Budget updated LIB line item Supplies (LIB version 1).", target_type="x",
        )
        ProjectStatusHistory.objects.create(project=self.project, from_status="active", to_status="completed",
                                            changed_by=self.leader, remarks="Done")
        rows = self.history()
        self.assertEqual((rows[0]["kind"], rows[0]["title"]), ("status", "Project status changed: Ongoing → Completed"))
        self.assertEqual((rows[1]["kind"], rows[1]["title"], rows[1]["actor_role"]), ("update", "LIB updated", "Finance/Accounting/Budget"))

    def test_other_roles_see_it_when_they_may_open_the_project(self):
        self.review("submitted", self.leader)
        for user in (self.crc, self.finance, self.make_user("riuh", campus="Siniloan"), self.make_user("system_admin")):
            self.assertEqual(self.history(user)[0]["title"], "Submitted for review")

    def test_404_outside_the_users_projects(self):
        for user in (self.make_user("project_leader", campus="Siniloan"), self.make_user("crc_chair", campus="Sta. Cruz"),
                     self.make_user("project_staff")):
            self.assertEqual(self.client_for(user).get(self.url).status_code, 404)
