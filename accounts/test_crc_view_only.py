"""Client Task 41 (2026-11-03, Carl): CRC/CRD views projects, the Work Plan and Personnel & Tasks for auditing but takes
no action there (accounts 0031). The Project Leader -> CRC/CRD -> Finance/Accounting/Budget review stays as it was."""
from datetime import date
from decimal import Decimal

from accounts.testing import RMISTestCase
from budget_lib.models import LineItem, LineItemBudget
from budget_lib.tests import add_registration_rows, attach_approval_documents
from personnel.models import Task
from research_projects.models import Project, WorkPlanMilestone
from research_projects.tests import project_payload


class CrcViewOnlyTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self._patch("budget_lib.views.notify")
        self.leader = self.make_user("project_leader")
        self.staff = self.make_user("project_staff")
        self.crc = self.make_user("crc_chair")
        self.officer = self.make_user("finance_budget")
        self.project = Project.objects.create(
            title="P", project_code="P-1", funding_type="core_funded", lead=self.leader, total_cost="1000",
            start_date=date(2026, 1, 1), target_end_date=date(2026, 12, 31),
        )
        # Certified: visible to CRC/CRD and open for tasks (work starts once the LIB is certified)
        LineItemBudget.objects.create(project=self.project, version_number=1, status="certified")
        self.milestone = WorkPlanMilestone.objects.create(project=self.project, title="Survey", target_date=date(2026, 6, 30))
        self.task = Task.objects.create(project=self.project, title="Interview", assignee=self.staff, assigned_by=self.leader)
        self.crc_client = self.client_for(self.crc)

    def test_crc_cannot_register_or_edit_projects(self):
        self.assertEqual(self.crc_client.post("/api/projects/", project_payload(self.leader), format="json").status_code, 403)
        self.assertEqual(self.crc_client.patch(f"/api/projects/{self.project.pk}/", {"title": "X"}, format="json").status_code, 403)
        self.assertEqual(self.crc_client.patch(f"/api/projects/{self.project.pk}/", {"status": "completed"}, format="json").status_code, 403)
        self.project.refresh_from_db()
        self.assertEqual((self.project.title, self.project.status), ("P", "active"))

    def test_crc_cannot_change_the_work_plan(self):
        url = f"/api/milestones/{self.milestone.pk}/"
        new = {"project": self.project.pk, "title": "New", "target_date": "2026-07-31"}
        self.assertEqual(self.crc_client.post("/api/milestones/", new, format="json").status_code, 403)
        self.assertEqual(self.crc_client.patch(url, {"title": "Renamed"}, format="json").status_code, 403)
        self.assertEqual(self.crc_client.delete(url).status_code, 403)
        self.assertEqual(WorkPlanMilestone.objects.get().title, "Survey")

    def test_crc_cannot_act_on_personnel_or_tasks(self):
        task = {"project": self.project.pk, "title": "New", "assignee": self.staff.pk}
        self.assertEqual(self.crc_client.post("/api/personnel/tasks/", task, format="json").status_code, 403)
        # Task edits are open to assignees for their own status, so a non-assigner is refused by the serializer (400)
        self.assertIn(self.crc_client.patch(f"/api/personnel/tasks/{self.task.pk}/", {"title": "X"}, format="json").status_code, (400, 403))
        self.assertEqual(self.crc_client.delete(f"/api/personnel/tasks/{self.task.pk}/").status_code, 403)
        self.assertEqual(self.crc_client.post(f"/api/personnel/tasks/{self.task.pk}/review/", {"action": "approve"}, format="json").status_code, 403)
        self.assertEqual(self.crc_client.post("/api/personnel/staff-profiles/", {"user": self.staff.pk}, format="json").status_code, 403)
        self.assertEqual(self.crc_client.post("/api/personnel/assignments/", {"project": self.project.pk, "user": self.staff.pk}, format="json").status_code, 403)
        self.assertEqual(self.crc_client.post("/api/personnel/changes/", {"project": self.project.pk}, format="json").status_code, 403)
        self.assertEqual(Task.objects.get().title, "Interview")

    def test_crc_still_views_everything(self):
        for url in (f"/api/projects/{self.project.pk}/", f"/api/milestones/?project={self.project.pk}",
                    f"/api/personnel/tasks/?project={self.project.pk}", "/api/personnel/leaders/load/"):
            with self.subTest(url=url):
                self.assertEqual(self.crc_client.get(url).status_code, 200)
        tasks = self.crc_client.get(f"/api/personnel/tasks/?project={self.project.pk}").data
        rows = tasks["results"] if isinstance(tasks, dict) else tasks
        self.assertEqual([t["title"] for t in rows], ["Interview"])

    def test_leader_crc_finance_review_is_unchanged(self):
        project = Project.objects.create(
            title="Q", project_code="Q-1", funding_type="core_funded", lead=self.leader, total_cost="1000",
            start_date=date(2026, 1, 1), target_end_date=date(2026, 12, 31),
        )
        budget = LineItemBudget.objects.create(project=project, version_number=1)
        LineItem.objects.create(budget=budget, category="mooe", description="Travel", amount=Decimal("1000"))
        attach_approval_documents(project, self.leader)
        add_registration_rows(project)
        steps = [(self.leader, "submit", ""), (self.crc, "hold", "Fix travel."), (self.leader, "resubmit", ""),
                 (self.crc, "for-checking", ""), (self.officer, "start-certification", ""), (self.officer, "certify", "")]
        for user, step, remarks in steps:
            with self.subTest(step=step):
                response = self.client_for(user).post(f"/api/budget/budgets/{budget.pk}/{step}/", {"remarks": remarks}, format="json")
                self.assertEqual(response.status_code, 200, (step, response.data))
        budget.refresh_from_db()
        self.assertEqual(budget.status, "certified")

    def test_leader_keeps_task_actions(self):
        leader = self.client_for(self.leader)
        response = leader.patch(f"/api/personnel/tasks/{self.task.pk}/", {"title": "Interview 2"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
