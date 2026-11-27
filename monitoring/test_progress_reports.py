"""Project Progress Reports page (client Task 89-A, 2026-11-27): one row per project with its report status, for
System Admin, Project Leader, RIUH and CRC/CRD only, in their usual project scope."""
import datetime

from django.db import connection
from django.test.utils import CaptureQueriesContext

from accounts.testing import RMISTestCase
from budget_lib.models import LineItemBudget
from monitoring.models import MidtermReport, MonthlyProgressReport, QuarterlyProgressReport, TerminalReport
from research_projects.models import Project

URL = "/api/monitoring/progress-reports/"


class ProgressReportTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader", first_name="Ana", last_name="Cruz", campus="Siniloan")
        self.lb_leader = self.make_user("project_leader", first_name="Ben", last_name="Diaz", campus="Los Baños")
        self.admin = self.make_user("system_admin")
        self.cas = self.project("S-CAS", self.leader, "Siniloan", "CAS")
        self.ccs = self.project("S-CCS", self.leader, "Siniloan", "CCS")
        self.lb = self.project("L-CCS", self.lb_leader, "Los Baños", "CCS")

    def project(self, code, lead, campus, college):
        project = Project.objects.create(title=f"Study {code}", project_code=code, funding_type="core_funded", lead=lead,
                                         campus=campus, college=college, target_end_date=datetime.date(2030, 12, 31))
        LineItemBudget.objects.create(project=project, version_number=1, status="certified")
        return project

    def get(self, user, **params):
        return self.client_for(user).get(URL, params)

    def codes(self, user, **params):
        response = self.get(user, **params)
        self.assertEqual(response.status_code, 200, response.data)
        return [row["project_code"] for row in response.data["results"]]

    def test_only_the_four_roles_open_it(self):
        for role in ("vprei", "university_admin", "finance_budget", "procurement_officer_lib", "project_staff"):
            self.assertEqual(self.get(self.make_user(role, campus="Siniloan")).status_code, 403, role)
        for role in ("riuh", "crc_chair"):
            self.assertEqual(self.get(self.make_user(role, campus="Siniloan")).status_code, 200, role)

    def test_each_role_keeps_its_project_scope(self):
        self.assertEqual(self.codes(self.admin), ["L-CCS", "S-CAS", "S-CCS"])
        self.assertEqual(self.codes(self.leader), ["S-CAS", "S-CCS"])
        self.assertEqual(self.codes(self.make_user("crc_chair", campus="Siniloan")), ["S-CAS", "S-CCS"])
        self.assertEqual(self.codes(self.make_user("riuh", campus="Siniloan", college_unit="CAS")), ["S-CAS"])

    def test_report_status_per_project(self):
        for period in (datetime.date(2026, 8, 1), datetime.date(2026, 9, 1)):
            MonthlyProgressReport.objects.create(project=self.cas, period=period, submitted_by=self.leader)
        MidtermReport.objects.create(project=self.cas, project_year=1, submitted_by=self.leader)
        TerminalReport.objects.create(project=self.cas, submitted_by=self.leader, is_certified=True)
        QuarterlyProgressReport.objects.create(project=self.cas, year=2026, quarter=1, status="approved", created_by=self.leader)
        QuarterlyProgressReport.objects.create(project=self.cas, year=2026, quarter=2, status="endorsed", created_by=self.leader)
        rows = {r["project_code"]: r for r in self.get(self.admin).data["results"]}
        cas = rows["S-CAS"]
        self.assertEqual((cas["college"], cas["project_leader"]), ("CAS", "Ana Cruz"))
        self.assertEqual(cas["monthly"], {"count": 2, "latest_period": datetime.date(2026, 9, 1)})
        self.assertEqual(cas["midterm"], {"count": 1, "years": [1]})
        self.assertEqual(cas["terminal"], {"submitted": True, "certified": True})
        self.assertEqual(cas["quarterly"], {"count": 2, "approved": 1, "latest": {"year": 2026, "quarter": 2, "status": "endorsed"}})
        empty = rows["S-CCS"]
        self.assertEqual((empty["monthly"]["count"], empty["midterm"]["count"], empty["terminal"]["submitted"], empty["quarterly"]["latest"]),
                         (0, 0, False, None))

    def test_search_college_and_paging(self):
        self.assertEqual(self.codes(self.admin, q="diaz"), ["L-CCS"])
        self.assertEqual(self.codes(self.admin, q="s-ca"), ["S-CAS"])
        self.assertEqual(self.codes(self.admin, college="ccs"), ["L-CCS", "S-CCS"])
        page = self.get(self.admin, page_size=2).data
        self.assertEqual((page["count"], len(page["results"]), page["next"] is not None), (3, 2, True))

    def test_query_count_does_not_grow_with_projects(self):
        with CaptureQueriesContext(connection) as few:
            self.get(self.admin)
        for i in range(4):
            project = self.project(f"X-{i}", self.leader, "Siniloan", "CAS")
            MonthlyProgressReport.objects.create(project=project, period=datetime.date(2026, 9, 1), submitted_by=self.leader)
        with CaptureQueriesContext(connection) as many:
            self.get(self.admin)
        self.assertEqual(len(many), len(few))
