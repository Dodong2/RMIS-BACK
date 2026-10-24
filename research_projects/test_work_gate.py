"""Carl 2026-10-24 (D5): no work on a project until its reviews are completed (the Budget Officer certified its LIB):
tasks, Work Logs, staff assignments, monitoring reports, research outputs and compliance records. Every role."""
import datetime

from accounts.testing import RMISTestCase
from budget_lib.models import LineItemBudget
from outputs.models import ExpectedOutput
from personnel.models import Task
from research_projects.models import Project


class WorkGateTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.make_user("system_admin")
        self.leader = self.make_user("project_leader")
        self.staff = self.make_user("project_staff")
        self.project = Project.objects.create(
            title="P", project_code="P-1", funding_type="core_funded", lead=self.leader, start_date=datetime.date(2026, 1, 1),
            target_end_date=datetime.date(2027, 12, 31),
        )
        self.budget = LineItemBudget.objects.create(project=self.project, version_number=1)
        self.task = Task.objects.create(project=self.project, title="Old task", assignee=self.staff, assigned_by=self.leader)
        self.review_task = Task.objects.create(project=self.project, title="Sent for review", assignee=self.staff,
                                               assigned_by=self.leader, status="for_review")
        self.output = ExpectedOutput.objects.create(project=self.project, category="people_services", description="D")

    def certify(self):
        LineItemBudget.objects.filter(pk=self.budget.pk).update(status="certified")

    def writes(self):
        p, today = self.project.pk, "2026-10-24"
        admin, leader, staff = self.client_for(self.admin), self.client_for(self.leader), self.client_for(self.staff)
        return {
            "task": lambda: leader.post("/api/personnel/tasks/", {"project": p, "title": "T", "assignee": self.staff.pk,
                                                                  "start_date": today, "due_date": "2026-10-31"}, format="json"),
            "deliverable": lambda: leader.post(f"/api/personnel/tasks/{self.task.pk}/deliverables/", {"text": "Draft report"}, format="json"),
            "task review": lambda: leader.post(f"/api/personnel/tasks/{self.review_task.pk}/review/", {"action": "approve"}, format="json"),
            "work log": lambda: staff.post(f"/api/personnel/tasks/{self.task.pk}/updates/", {"note": "Did it", "hours": "2"}, format="json"),
            "assignment": lambda: admin.post("/api/personnel/assignments/", {"user": self.staff.pk, "project": p, "start_date": today}, format="json"),
            "monthly report": lambda: admin.post("/api/monitoring/monthly-reports/", {"project": p, "period": today}, format="json"),
            "extension": lambda: admin.post("/api/monitoring/extension-requests/", {"project": p, "requested_end_date": "2028-06-30",
                                                                                    "justification": "Delays"}, format="json"),
            "publication": lambda: admin.post("/api/outputs/publications/", {"project": p, "lead_author": self.leader.pk, "title": "T",
                                                                             "publication_type": "journal_article", "published_on": today}, format="json"),
            "IP": lambda: admin.post("/api/outputs/ip-records/", {"project": p, "creator": self.leader.pk, "title": "T", "ip_type": "patent"}, format="json"),
            "6P actual count": lambda: admin.patch(f"/api/outputs/expected-outputs/{self.output.pk}/", {"manual_actual_count": 2}, format="json"),
            "ethics review": lambda: admin.post("/api/compliance/ethics-reviews/", {"project": p, "review_body": "trc"}, format="json"),
            "AI declaration": lambda: admin.post("/api/compliance/ai-declarations/", {"project": p, "tool_name": "X", "purpose": "Y",
                                                                                      "extent": "minor", "declared_on": today}, format="json"),
        }

    def test_no_work_before_the_reviews_are_completed(self):
        for status in ("draft", "submitted", "for_checking", "endorsed", "returned"):
            LineItemBudget.objects.filter(pk=self.budget.pk).update(status=status)
            for name, write in self.writes().items():
                response = write()

                self.assertEqual(response.status_code, 400, f"{status} {name}: {getattr(response, 'data', '')}")
                self.assertIn("Work on it starts once its reviews are completed", str(response.data), f"{status} {name}")
        self.assertEqual(Task.objects.count(), 2)
        self.assertEqual(Task.objects.get(pk=self.review_task.pk).status, "for_review")

    def test_work_starts_once_the_lib_is_certified(self):
        self.certify()

        for name, write in self.writes().items():
            response = write()

            self.assertIn(response.status_code, (200, 201), f"{name}: {getattr(response, 'data', '')}")

    def test_registration_rows_still_save_on_a_draft(self):
        """The wizard and the Excel import add 6Ps and the work plan right after registering (Draft)."""
        response = self.client_for(self.admin).post(
            "/api/outputs/expected-outputs/", {"project": self.project.pk, "category": "patents", "description": "E"}, format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
