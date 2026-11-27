"""Transactions page (client Task 88-A, 2026-11-27): the Event Logs Budget rows, read-only, for System Admin,
Finance/Accounting/Budget and Procurement Officer - LIB, campus-scoped, with filters, paging and export."""
import datetime

from django.utils import timezone

from accounts.testing import RMISTestCase
from research_projects.models import Project

from .events import log_budget_event
from .models import BudgetEventLog, LineItemBudget

URL = "/api/budget/transactions/"


class TransactionTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader", first_name="Ana", last_name="Cruz", campus="Siniloan")
        self.lb_leader = self.make_user("project_leader", first_name="Ben", last_name="Diaz", campus="Los Baños")
        self.admin = self.make_user("system_admin")
        self.finance = self.make_user("finance_budget", campus="Siniloan")
        self.procurement = self.make_user("procurement_officer_lib", campus="Siniloan")
        self.siniloan = self.project("NTP-S1", self.leader, "Siniloan", "CAS")
        self.los_banos = self.project("NTP-L1", self.lb_leader, "Los Baños", "CCS")
        self.gone = self.project("NTP-OLD", self.leader, "Siniloan", "CAS")
        self.log(self.leader, self.siniloan, "LIB_SUBMITTED", "Submitted the LIB.")
        self.log(self.procurement, self.siniloan, "PROCUREMENT_COMPLETED", "Completed procurement request #1 (Reagents).", amount=4000)
        self.log(self.lb_leader, self.los_banos, "LIB_SUBMITTED", "Submitted the LIB.")
        self.log(self.leader, self.gone, "LIB_SUBMITTED", "Submitted the LIB.")
        self.gone_ref = self.gone.pk
        self.gone.delete()

    def project(self, code, lead, campus, college):
        project = Project.objects.create(title=f"Study {code}", project_code=code, funding_type="core_funded", lead=lead,
                                         campus=campus, college=college)
        LineItemBudget.objects.create(project=project, version_number=1, status="certified")
        return project

    def log(self, user, project, event, description, **kwargs):
        return log_budget_event(user, project, event, description, project, **kwargs)

    def get(self, user, **params):
        return self.client_for(user).get(URL, params)

    def codes(self, response):
        self.assertEqual(response.status_code, 200, response.data)
        return sorted(row["project_code"] for row in response.data["results"])

    def test_only_the_three_roles_open_it(self):
        for role in ("project_leader", "crc_chair", "riuh", "vprei", "university_admin", "project_staff"):
            user = self.make_user(role, campus="Siniloan")
            for path in ("", "filters/", "export/"):
                self.assertEqual(self.client_for(user).get(URL + path).status_code, 403, (role, path))
        for user in (self.admin, self.finance, self.procurement):
            self.assertEqual(self.get(user).status_code, 200)

    def test_campus_roles_see_their_campus_and_admin_sees_all_including_deleted_projects(self):
        self.assertEqual(self.codes(self.get(self.finance)), ["NTP-S1", "NTP-S1"])
        self.assertEqual(self.codes(self.get(self.procurement)), ["NTP-S1", "NTP-S1"])
        self.assertEqual(self.codes(self.get(self.admin)), ["NTP-L1", "NTP-OLD", "NTP-S1", "NTP-S1"])

    def test_row_shape(self):
        row = next(r for r in self.get(self.admin, event="PROCUREMENT_COMPLETED").data["results"])
        self.assertEqual((row["college"], row["project_leader"], row["actor_role"], row["amount"]),
                         ("CAS", "Ana Cruz", "procurement_officer_lib", "4000.00"))
        old = self.get(self.admin, project=self.gone_ref).data["results"][0]
        self.assertEqual((old["project"], old["project_code"], old["college"], old["project_leader"]), (None, "NTP-OLD", "", ""))

    def test_filters(self):
        self.assertEqual(self.codes(self.get(self.admin, college="ccs")), ["NTP-L1"])
        self.assertEqual(self.codes(self.get(self.admin, leader=self.lb_leader.pk)), ["NTP-L1"])
        self.assertEqual(self.codes(self.get(self.admin, project=self.siniloan.pk)), ["NTP-S1", "NTP-S1"])
        self.assertEqual(self.codes(self.get(self.admin, q="reagents")), ["NTP-S1"])
        self.assertEqual(self.codes(self.get(self.admin, event="PROCUREMENT_COMPLETED")), ["NTP-S1"])
        BudgetEventLog.objects.filter(project_code="NTP-L1").update(created_at=timezone.now() - datetime.timedelta(days=40))
        today = timezone.localdate()
        self.assertEqual(self.codes(self.get(self.admin, date_to=str(today - datetime.timedelta(days=30)))), ["NTP-L1"])
        self.assertNotIn("NTP-L1", self.codes(self.get(self.admin, date_from=str(today))))
        self.assertEqual(self.get(self.admin, date_from="11/27/2026").status_code, 400)
        self.assertEqual(self.get(self.admin, leader="abc").status_code, 400)

    def test_paging(self):
        page = self.get(self.admin, page_size=3).data
        self.assertEqual((page["count"], len(page["results"]), page["next"] is not None), (4, 3, True))
        self.assertEqual(len(self.get(self.admin, page_size=3, page=2).data["results"]), 1)

    def test_filter_choices_follow_the_scope(self):
        data = self.client_for(self.finance).get(URL + "filters/").data
        self.assertEqual([p["project_code"] for p in data["projects"]], ["NTP-S1"])
        self.assertEqual((data["colleges"], [u["name"] for u in data["leaders"]]), (["CAS"], ["Ana Cruz"]))
        self.assertEqual(data["events"], ["LIB_SUBMITTED", "PROCUREMENT_COMPLETED"])
        admin = self.client_for(self.admin).get(URL + "filters/").data
        self.assertEqual([p["project_code"] for p in admin["projects"]], ["NTP-L1", "NTP-OLD", "NTP-S1"])

    def test_export_follows_the_filters(self):
        client = self.client_for(self.finance)
        xlsx = client.get(URL + "export/", {"file_format": "xlsx", "event": "PROCUREMENT_COMPLETED"})
        self.assertEqual(xlsx.status_code, 200)
        self.assertTrue(xlsx.content.startswith(b"PK"))
        self.assertIn("attachment", xlsx["Content-Disposition"])
        pdf = client.get(URL + "export/", {"file_format": "pdf"})
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertEqual(client.get(URL + "export/", {"file_format": "csv"}).status_code, 400)
