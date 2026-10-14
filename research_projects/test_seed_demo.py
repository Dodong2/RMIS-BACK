from io import StringIO

from django.core.management import CommandError, call_command

from accounts.models import User
from accounts.testing import RMISTestCase
from dashboard.services import compute_portfolio_dashboard, compute_project_dashboard
from financial_monitoring.models import Disbursement, ProcurementRequest
from monitoring.models import QuarterlyProgressReport, TerminalReport
from research_projects.models import Project

DEMO_ROLES = ("project_leader", "finance_budget", "procurement_officer_lib", "riuh", "drd")


class SeedDemoTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        for code in DEMO_ROLES:
            self.make_user(code)

    def seed(self, *args):
        call_command("seed_demo", *args, stdout=StringIO())

    def test_creates_three_end_to_end_projects(self):
        self.seed()
        demo = Project.objects.filter(project_code__startswith="DEMO-")
        self.assertEqual(demo.count(), 3)
        self.assertEqual(sorted(demo.values_list("status", flat=True)), ["active", "completed", "completed"])
        for p in demo:
            self.assertTrue(p.budgets.filter(is_current=True, status="certified").exists(), p.project_code)
            self.assertTrue(p.milestones.exists())
            self.assertTrue(p.monthly_reports.exists())
            self.assertTrue(p.quarterly_reports.filter(status="approved").exists())
            proc = ProcurementRequest.objects.get(line_item__budget__project=p)
            self.assertEqual(proc.status, "completed")
            self.assertTrue(Disbursement.objects.filter(procurement_request=proc).exists())
        for p in demo.filter(status="completed"):
            self.assertTrue(TerminalReport.objects.get(project=p).is_certified)
            self.assertTrue(p.status_history.filter(to_status="completed").exists())
            self.assertTrue(p.publications.exists())

    def test_quarterly_report_has_full_event_trail(self):
        self.seed()
        report = QuarterlyProgressReport.objects.filter(project__project_code__startswith="DEMO-").first()
        self.assertEqual(
            list(report.events.order_by("id").values_list("to_status", flat=True)),
            ["draft", "submitted", "under_review", "endorsed", "approved"],
        )

    def test_dashboards_see_demo_projects(self):
        self.seed()
        self.assertEqual(compute_project_dashboard()["by_status"], {"active": 1, "completed": 2})
        self.assertEqual(len(compute_portfolio_dashboard()["by_college"]), 3)

    def test_running_twice_does_not_duplicate(self):
        self.seed()
        self.seed()
        self.assertEqual(Project.objects.filter(project_code__startswith="DEMO-").count(), 3)
        self.assertEqual(ProcurementRequest.objects.count(), 3)

    def test_clear_removes_only_demo_data(self):
        lead = self.make_user("project_leader")
        real = Project.objects.create(title="Real", project_code="FRN-2026-999", funding_type="institutional", lead=lead)
        self.seed()
        self.seed("--clear")
        self.assertFalse(Project.objects.filter(project_code__startswith="DEMO-").exists())
        self.assertFalse(Disbursement.objects.exists())
        self.assertFalse(ProcurementRequest.objects.exists())
        self.assertTrue(Project.objects.filter(pk=real.pk).exists())

    def test_missing_role_stops_with_clear_message(self):
        User.objects.filter(role__code="drd").update(is_active=False)
        with self.assertRaisesMessage(CommandError, "drd"):
            self.seed()
        self.assertFalse(Project.objects.filter(project_code__startswith="DEMO-").exists())
