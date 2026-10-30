from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from accounts.testing import RMISTestCase
from budget_lib.models import LineItem, LineItemBudget
from financial_monitoring.tests import with_year_one
from financial_monitoring.models import BudgetRealignment, Disbursement, ProcurementRequest, ProcurementStatusEvent
from research_projects.models import Project

URL = "/api/dashboard/procurement/"
PR_URL = "/api/financial/procurement-requests/"


class ProcurementDashboardTests(RMISTestCase):
    """2026-10-22: one Procurement Officer - LIB dashboard shared by every account of the role (same scope = same data),
    with per-request LIB figures, processing days and a per-account status history."""

    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader", first_name="Lea", last_name="Lim")
        self.leader_client = self.client_for(self.leader)
        self.item = self.certified_item("P-1", "Siniloan", 10000)
        self.other_item = self.certified_item("P-2", "Santa Cruz", 5000)
        self.ana = self.make_user("procurement_officer_lib", first_name="Ana", last_name="Cruz")
        self.ben = self.make_user("procurement_officer_lib", first_name="Ben", last_name="Reyes")
        self.ana_client, self.ben_client = self.client_for(self.ana), self.client_for(self.ben)

    def certified_item(self, code, campus, amount):
        project = Project.objects.create(
            title=code, project_code=code, funding_type="core_funded", lead=self.leader, campus=campus, college="CCS",
        )
        budget = LineItemBudget.objects.create(project=project, version_number=1, status="certified")
        return with_year_one(LineItem.objects.create(budget=budget, category="mooe", description="Office Supplies Expenses", amount=amount))

    def file(self, item, amount, description="Reagents"):
        response = self.leader_client.post(PR_URL, {
            "line_item": item.id, "description": description, "amount": str(amount), "project_year": 1, "quarter": 4,
        })
        self.assertEqual(response.status_code, 201, response.data)
        return ProcurementRequest.objects.get(pk=response.data["id"])

    def move(self, client, pr, status, remarks=None):
        payload = {"status": status, **({"remarks": remarks} if remarks is not None else {})}
        response = client.post(f"{PR_URL}{pr.id}/status/", payload)
        self.assertEqual(response.status_code, 200, response.data)

    def row(self, data, pr):
        return next(r for r in data["requests"] if r["id"] == pr.id)

    def test_every_officer_account_gets_the_same_dashboard(self):
        self.file(self.item, 4000)
        self.file(self.other_item, 1000)

        ana, ben = self.ana_client.get(URL), self.ben_client.get(URL)

        self.assertEqual((ana.status_code, ben.status_code), (200, 200))
        self.assertEqual(ana.json(), ben.json())
        self.assertEqual(len(ana.data["requests"]), 2)

    def test_row_figures(self):
        done = self.file(self.item, 3000, "Paper")
        open_pr = self.file(self.item, 4000)
        self.ana_client.post(f"{PR_URL}{done.id}/receive/")
        self.move(self.ana_client, done, "completed")
        ProcurementRequest.objects.filter(pk=done.pk).update(requested_at=timezone.now() - timedelta(days=5, hours=1))
        ProcurementRequest.objects.filter(pk=open_pr.pk).update(requested_at=timezone.now() - timedelta(days=2, hours=1))

        data = self.ana_client.get(URL).data
        closed, still_open = self.row(data, done), self.row(data, open_pr)

        # 10,000 LIB - 3,000 released - 4,000 reserved by the open request
        self.assertEqual((closed["lib_adjusted"], closed["lib_uncommitted"]), (Decimal("10000"), Decimal("3000")))
        self.assertEqual(closed["released"], Decimal("3000"))
        self.assertEqual(closed["processing_days"], 5)
        self.assertEqual((closed["request_no"], closed["campus"], closed["college"]), (f"PR-{done.pk:04d}", "Siniloan", "CCS"))
        # The open request may use what's left with its own 4,000 put back
        self.assertEqual(still_open["available"], Decimal("7000"))
        self.assertFalse(still_open["exceeds_available"])
        self.assertEqual(still_open["released"], 0)
        self.assertEqual(still_open["processing_days"], 2)

        # A manual disbursement that eats the balance flags the open request
        Disbursement.objects.create(line_item=self.item, amount=Decimal("6500"), disbursed_on=timezone.now().date(), recorded_by=self.leader)
        still_open = self.row(self.ana_client.get(URL).data, open_pr)
        self.assertEqual(still_open["available"], Decimal("500"))
        self.assertTrue(still_open["exceeds_available"])

    def test_audit_trail_keeps_each_account(self):
        pr = self.file(self.item, 4000)
        self.ana_client.post(f"{PR_URL}{pr.id}/receive/")
        self.move(self.ben_client, pr, "returned_for_revision", "Attach a quotation")
        self.assertEqual(self.leader_client.post(f"{PR_URL}{pr.id}/resubmit/", {"amount": "3500"}).status_code, 200)
        self.ben_client.post(f"{PR_URL}{pr.id}/receive/")
        self.move(self.ana_client, pr, "returned_for_revision", "Wrong supplier")

        data = self.ana_client.get(URL).data
        trail = [(e["actor"], e["from_status"], e["to_status"]) for e in reversed(data["events"])]
        self.assertEqual(trail, [
            ("Lea Lim", "", "requested"),
            ("Ana Cruz", "requested", "under_review"),
            ("Ben Reyes", "under_review", "returned_for_revision"),
            ("Lea Lim", "returned_for_revision", "requested"),
            ("Ben Reyes", "requested", "under_review"),
            ("Ana Cruz", "under_review", "returned_for_revision"),
        ])
        self.assertEqual(data["events"][0]["remarks"], "Wrong supplier")
        self.assertEqual(data["events"][0]["actor_role"], "Procurement Officer - LIB")
        self.assertEqual(self.row(data, pr)["returned_count"], 2)

    def test_campus_scoped_officer_sees_and_moves_only_their_campus(self):
        mine, theirs = self.file(self.item, 1000), self.file(self.other_item, 1000)
        carla = self.client_for(self.make_user("procurement_officer_lib", campus="Siniloan"))

        data = carla.get(URL).data
        self.assertEqual([r["id"] for r in data["requests"]], [mine.id])
        self.assertEqual({e["procurement"] for e in data["events"]}, {mine.id})
        self.assertEqual(carla.post(f"{PR_URL}{theirs.id}/receive/").status_code, 404)
        self.assertEqual(carla.post(f"{PR_URL}{theirs.id}/status/", {"status": "completed"}).status_code, 404)
        self.assertEqual(carla.post(f"{PR_URL}{mine.id}/receive/").status_code, 200)
        self.assertEqual(ProcurementRequest.objects.get(pk=theirs.pk).status, "requested")

    def test_only_the_procurement_office_and_admin_open_it(self):
        self.assertEqual(self.client_for(self.make_user("system_admin")).get(URL).status_code, 200)
        for role in ("finance_budget", "project_leader", "vprei", "project_staff"):
            self.assertEqual(self.client_for(self.make_user(role)).get(URL).status_code, 403, role)

    def test_events_are_recorded_for_every_transition(self):
        pr = self.file(self.item, 2000)
        self.ana_client.post(f"{PR_URL}{pr.id}/receive/")
        for step in ("for_procurement", "delivered", "completed"):
            self.move(self.ana_client, pr, step)
        self.assertEqual(
            list(ProcurementStatusEvent.objects.filter(procurement=pr).order_by("id").values_list("to_status", flat=True)),
            ["requested", "under_review", "for_procurement", "delivered", "completed"],
        )


class FinanceSharedAccountsTests(RMISTestCase):
    """2026-10-22: several Finance/Accounting/Budget accounts share one dashboard; a campus-scoped one can't write to
    another campus's records by id."""

    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader")
        self.items = {}
        for code, campus in (("P-1", "Siniloan"), ("P-2", "Santa Cruz")):
            project = Project.objects.create(title=code, project_code=code, funding_type="core_funded", lead=self.leader, campus=campus)
            budget = LineItemBudget.objects.create(project=project, version_number=1, status="certified")
            self.items[campus] = with_year_one(LineItem.objects.create(budget=budget, category="mooe", description="Training Expenses", amount=5000))
            LineItem.objects.create(budget=budget, category="mooe", description="Office Supplies Expenses", amount=1000)

    def test_two_finance_accounts_get_the_same_budget_dashboard(self):
        first = self.client_for(self.make_user("finance_budget")).get("/api/dashboard/budget/")
        second = self.client_for(self.make_user("finance_budget")).get("/api/dashboard/budget/")
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual(first.json(), second.json())

    def test_campus_scoped_finance_cannot_disburse_or_review_elsewhere(self):
        finance = self.client_for(self.make_user("finance_budget", campus="Siniloan"))
        payload = {"amount": "100", "reference_number": "OR-1", "disbursed_on": "2026-10-22"}

        response = finance.post("/api/financial/disbursements/", {**payload, "line_item": self.items["Santa Cruz"].id})
        self.assertEqual(response.status_code, 400)
        self.assertIn("outside your scope", str(response.data))
        response = finance.post("/api/financial/disbursements/", {**payload, "line_item": self.items["Siniloan"].id})
        self.assertEqual(response.status_code, 201, response.data)

        source = self.items["Santa Cruz"]
        realignment = BudgetRealignment.objects.create(
            from_line_item=source, to_line_item=source.budget.line_items.exclude(pk=source.pk).get(),
            amount=Decimal("100"), justification="x", requested_by=self.leader, status="pending_approval",
        )
        response = finance.post(f"/api/financial/realignments/{realignment.id}/review/", {"decision": "approve"})
        self.assertEqual(response.status_code, 404)
        realignment.refresh_from_db()
        self.assertEqual(realignment.status, "pending_approval")
