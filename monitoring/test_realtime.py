"""2026-10-13 real-time: each monitoring write sends one small signal (realtime/notify.py) to the monitoring roles,
the project lead and the submitter. The browser refetches through DRF, so the signal carries ids only."""
import datetime

from accounts.testing import RMISTestCase
from budget_lib.models import LineItemBudget
from monitoring.models import ExtensionRequest, ProjectEvaluation, RenewalApplication, TerminalReport
from realtime.consumers import campus_role_group
from realtime.notify import to_role, to_user
from research_projects.models import Project

MONITORING_ROLES = {"system_admin", "vprei", "university_admin"}
# Task 21 (2026-10-30): RIUH and CRC/CRD are reached through the project's campus group (and their campus-less accounts)
CAMPUS_ROLES = ("riuh", "crc_chair")


def certify(project):
    """Work on a project starts once its LIB is certified (Carl 2026-10-24, D5)."""
    LineItemBudget.objects.create(project=project, version_number=1, status="certified")


class MonitoringSignalTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.notify = self._patch("monitoring.views.notify")
        self.leader = self.make_user("project_leader")
        self.staff = self.make_user("project_staff")
        self.project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=self.leader,
                                              target_end_date=datetime.date(2030, 12, 31))
        certify(self.project)
        self.admin = self.client_for(self.make_user("system_admin"))

    def sent(self):
        """The one signal sent: (groups, type, data)."""
        self.assertEqual(self.notify.call_count, 1)
        (groups, event_type), data = self.notify.call_args
        self.notify.reset_mock()
        return groups, event_type, data

    def assert_signal(self, event_type, *users, **data):
        groups, sent_type, sent_data = self.sent()
        self.assertEqual(sent_type, event_type)
        self.assertEqual(sent_data, {"project": self.project.id, **data})
        expected = {*map(to_role, MONITORING_ROLES), *(campus_role_group(code, c) for code in CAMPUS_ROLES for c in (self.project.campus, "")),
                    to_user(self.leader.pk), *(to_user(u.pk) for u in users)}
        self.assertEqual(set(groups), expected)

    def test_progress_reports(self):
        staff = self.client_for(self.staff)
        for kind, url, body in (
            ("monthly", "monthly-reports", {"period": "2026-09-01"}),
            ("midterm", "midterm-reports", {"project_year": 1}),
            ("terminal", "terminal-reports", {}),
        ):
            with self.subTest(kind=kind):
                response = staff.post(f"/api/monitoring/{url}/", {"project": self.project.id, **body}, format="json")
                self.assertEqual(response.status_code, 201, response.data)
                self.assert_signal("monitoring.report.created", self.staff, id=response.data["id"], kind=kind)

    def test_terminal_certification(self):
        report = TerminalReport.objects.create(project=self.project, submitted_by=self.staff)
        self.assertEqual(self.admin.post(f"/api/monitoring/terminal-reports/{report.id}/certify/").status_code, 200)
        self.assert_signal("monitoring.report.certified", self.staff, id=report.id, kind="terminal")

    def test_evaluation_schedule_outcome_and_score(self):
        response = self.admin.post("/api/monitoring/evaluations/", {
            "project": self.project.id, "project_year": 1, "scheduled_date": "2026-11-01"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        evaluation_id = response.data["id"]
        self.assert_signal("monitoring.evaluation.changed", id=evaluation_id)

        response = self.admin.patch(f"/api/monitoring/evaluations/{evaluation_id}/", {"outcome": "passed"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_signal("monitoring.evaluation.changed", id=evaluation_id)

        criterion = self.admin.post("/api/monitoring/evaluation-criteria/", {"name": "Quality", "weight": 100}, format="json")
        self.assertEqual(criterion.status_code, 201, criterion.data)
        self.notify.reset_mock()  # the rubric is global, not a project record: no signal expected or checked
        response = self.admin.post(f"/api/monitoring/evaluations/{evaluation_id}/scores/",
                                   {"criterion": criterion.data["id"], "score": 4}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assert_signal("monitoring.evaluation.changed", id=evaluation_id)

    def test_renewal_submit_and_decide(self):
        response = self.client_for(self.leader).post("/api/monitoring/renewal-applications/", {
            "project": self.project.id, "application_year": 2, "underspend_justification": "x"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        renewal_id = response.data["id"]
        self.assert_signal("monitoring.renewal.created", self.leader, id=renewal_id, status="pending")

        url = f"/api/monitoring/renewal-applications/{renewal_id}/decide/"
        self.assertEqual(self.admin.post(url, {"status": "approved"}).status_code, 200)
        self.assert_signal("monitoring.renewal.decided", self.leader, id=renewal_id, status="approved")

    def test_extension_submit_and_actions(self):
        response = self.client_for(self.leader).post("/api/monitoring/extension-requests/", {
            "project": self.project.id, "requested_end_date": "2031-06-30", "justification": "Typhoon"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        extension_id = response.data["id"]
        self.assert_signal("monitoring.extension.created", self.leader, id=extension_id, status="pending")

        url = f"/api/monitoring/extension-requests/{extension_id}/action/"
        for action, status in (("endorse", "endorsed"), ("approve", "approved")):
            self.assertEqual(self.admin.post(url, {"action": action}).status_code, 200)
            self.assert_signal("monitoring.extension.updated", self.leader, id=extension_id, status=status)

    def test_rejected_writes_send_nothing(self):
        renewal = RenewalApplication.objects.create(project=self.project, application_year=2, submitted_by=self.leader,
                                                    status="approved")
        extension = ExtensionRequest.objects.create(
            project=self.project, current_end_date=self.project.target_end_date,
            requested_end_date=datetime.date(2031, 6, 30), justification="x", submitted_by=self.leader)
        evaluation = ProjectEvaluation.objects.create(project=self.project, scheduled_date=datetime.date(2026, 11, 1))
        leader = self.client_for(self.leader)
        responses = [
            self.admin.post(f"/api/monitoring/renewal-applications/{renewal.id}/decide/", {"status": "denied"}),  # 400
            self.admin.post(f"/api/monitoring/extension-requests/{extension.id}/action/", {"action": "approve"}),  # 400
            leader.post(f"/api/monitoring/extension-requests/{extension.id}/action/", {"action": "endorse"}),  # 403
            leader.patch(f"/api/monitoring/evaluations/{evaluation.id}/", {"outcome": "passed"}, format="json"),  # 403
            self.client_for(self.staff).post("/api/monitoring/monthly-reports/", {"project": self.project.id}),  # 400
        ]
        self.assertEqual([r.status_code for r in responses], [400, 400, 403, 403, 400])
        self.notify.assert_not_called()
