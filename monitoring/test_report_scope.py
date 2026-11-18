"""Task 83-B (2026-11-18): Monthly, Midterm and Terminal reports only for a project in the submitter's scope, with a
document of that same project."""
import datetime

from accounts.testing import RMISTestCase
from budget_lib.models import LineItemBudget
from document_management.models import Document
from monitoring.models import MidtermReport, MonthlyProgressReport, TerminalReport
from personnel.models import ProjectAssignment
from research_projects.models import Project

KINDS = (
    ("monthly-reports", {"period": "2026-09-01"}, MonthlyProgressReport),
    ("midterm-reports", {"project_year": 1}, MidtermReport),
    ("terminal-reports", {}, TerminalReport),
)


class ReportScopeTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self._patch("monitoring.views.notify")
        self.leader = self.make_user("project_leader")
        self.other_leader = self.make_user("project_leader")
        self.admin = self.make_user("system_admin")
        self.own = self.project("OWN-1", self.leader, "Siniloan")
        self.other = self.project("OTH-1", self.other_leader, "Los Baños")

    def project(self, code, lead, campus):
        project = Project.objects.create(title=code, project_code=code, funding_type="core_funded", lead=lead,
                                         campus=campus, target_end_date=datetime.date(2030, 12, 31))
        LineItemBudget.objects.create(project=project, version_number=1, status="certified")
        return project

    def document(self, project):
        return Document.objects.create(project=project, document_type="other", version_number=1,
                                       storage_path=f"{project.project_code}/r.pdf", file_name="r.pdf", file_size=1,
                                       uploaded_by=self.admin)

    def post(self, user, url, project, body, document=None):
        data = {"project": project.pk, **body}
        if document:
            data["document"] = document.pk
        return self.client_for(user).post(f"/api/monitoring/{url}/", data, format="json")

    def test_leader_submits_each_report_with_own_document(self):
        for url, body, model in KINDS:
            with self.subTest(url=url):
                doc = self.document(self.own)
                response = self.post(self.leader, url, self.own, body, doc)
                self.assertEqual(response.status_code, 201, response.data)
                report = model.objects.get(pk=response.data["id"])
                self.assertEqual((report.project_id, report.document_id, report.submitted_by_id),
                                 (self.own.pk, doc.pk, self.leader.pk))

    def test_leader_cannot_submit_for_another_leaders_project(self):
        for url, body, model in KINDS:
            with self.subTest(url=url):
                response = self.post(self.leader, url, self.other, body)
                self.assertEqual(response.status_code, 400)
                self.assertIn("project", response.data)
                self.assertFalse(model.objects.exists())

    def test_document_of_another_project_is_rejected(self):
        doc = self.document(self.other)
        for user in (self.leader, self.admin):
            for url, body, model in KINDS:
                with self.subTest(user=user.role.code, url=url):
                    response = self.post(user, url, self.own, body, doc)
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("document", response.data)
                    self.assertFalse(model.objects.exists())

    def test_staff_only_on_assigned_project(self):
        staff = self.make_user("project_staff")
        ProjectAssignment.objects.create(user=staff, project=self.own, start_date=datetime.date(2026, 1, 1))
        self.assertEqual(self.post(staff, "monthly-reports", self.own, {"period": "2026-09-01"}).status_code, 201)
        self.assertEqual(self.post(staff, "monthly-reports", self.other, {"period": "2026-09-01"}).status_code, 400)

    def test_riuh_only_on_own_campus(self):
        riuh = self.make_user("riuh", campus="Siniloan")
        self.assertEqual(self.post(riuh, "monthly-reports", self.own, {"period": "2026-09-01"}).status_code, 201)
        self.assertEqual(self.post(riuh, "monthly-reports", self.other, {"period": "2026-09-01"}).status_code, 400)

    def test_system_admin_any_project(self):
        self.assertEqual(self.post(self.admin, "terminal-reports", self.other, {}).status_code, 201)

    def test_role_without_report_permission_is_denied(self):
        for code in ("finance_budget", "procurement_officer_lib", "crc_chair"):
            with self.subTest(code=code):
                response = self.post(self.make_user(code), "monthly-reports", self.own, {"period": "2026-09-01"})
                self.assertEqual(response.status_code, 403)

    def test_unauthenticated_is_rejected(self):
        from rest_framework.test import APIClient
        response = APIClient().post("/api/monitoring/monthly-reports/", {"project": self.own.pk, "period": "2026-09-01"},
                                    format="json")
        self.assertEqual(response.status_code, 401)
