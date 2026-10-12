"""2026-10-12 concurrency audit: monitoring decisions happen once, under a row lock (config/concurrency.py)."""
import datetime

from accounts.testing import RMISTestCase
from monitoring.models import ExtensionRequest, RenewalApplication, TerminalReport
from research_projects.models import Project


class MonitoringDecisionsHappenOnceTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader")
        self.project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=self.leader,
                                              target_end_date=datetime.date(2030, 12, 31))
        self.admin = self.client_for(self.make_user("system_admin"))

    def test_renewal_decision_cannot_be_overwritten(self):
        application = RenewalApplication.objects.create(project=self.project, application_year=2, submitted_by=self.leader)
        url = f"/api/monitoring/renewal-applications/{application.id}/decide/"
        self.assertEqual(self.admin.post(url, {"status": "approved"}).status_code, 200)
        response = self.admin.post(url, {"status": "denied"})
        self.assertEqual(response.status_code, 400)
        application.refresh_from_db()
        self.assertEqual(application.status, "approved")

    def test_terminal_report_is_certified_once(self):
        report = TerminalReport.objects.create(project=self.project, submitted_by=self.leader)
        url = f"/api/monitoring/terminal-reports/{report.id}/certify/"
        self.assertEqual(self.admin.post(url).status_code, 200)
        first_stamp = TerminalReport.objects.get().certified_at
        self.assertEqual(self.admin.post(url).status_code, 400)
        self.assertEqual(TerminalReport.objects.get().certified_at, first_stamp)

    def test_extension_is_approved_once(self):
        extension = ExtensionRequest.objects.create(
            project=self.project, current_end_date=self.project.target_end_date,
            requested_end_date=datetime.date(2031, 6, 30), justification="Typhoon delays", submitted_by=self.leader,
        )
        url = f"/api/monitoring/extension-requests/{extension.id}/action/"
        self.assertEqual(self.admin.post(url, {"action": "endorse"}).status_code, 200)
        self.assertEqual(self.admin.post(url, {"action": "approve"}).status_code, 200)
        self.assertEqual(self.admin.post(url, {"action": "approve"}).status_code, 400)
        self.assertEqual(self.admin.post(url, {"action": "deny"}).status_code, 400)
