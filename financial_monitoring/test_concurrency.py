"""Module 5 money flows under real concurrent requests (threads, separate DB connections). See ConcurrencyTestCase."""
from datetime import date

from django.db.models import Sum

from accounts.testing import ConcurrencyTestCase
from budget_lib.models import LineItem, LineItemBudget
from financial_monitoring.models import BudgetRealignment, Disbursement, ProcurementRequest
from research_projects.models import Project

PR_URL = "/api/financial/procurement-requests/"
BALANCE = "financial_monitoring.serializers.line_item_balance"


class MoneyConcurrencyTests(ConcurrencyTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader")
        self.project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=self.leader)
        self.budget = LineItemBudget.objects.create(project=self.project, version_number=1, status="certified")
        self.item = LineItem.objects.create(budget=self.budget, category="mooe", description="Supplies", amount=10000)
        self.other = LineItem.objects.create(budget=self.budget, category="mooe", description="Seminar", amount=10000)
        self.officer = self.make_user("procurement_officer_lib")
        self.finance = self.make_user("finance_budget")

    def request_procurement(self, amount, key=None):
        client = self.client_for(self.leader)
        headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
        return lambda: client.post(PR_URL, {
            "line_item": self.item.id, "description": "Reagents", "amount": str(amount), "fiscal_year": 2026, "quarter": 4,
        }, **headers)

    def committed_on_item(self):
        open_requests = ProcurementRequest.objects.filter(line_item=self.item).aggregate(t=Sum("amount"))["t"] or 0
        spent = Disbursement.objects.filter(line_item=self.item).aggregate(t=Sum("amount"))["t"] or 0
        return open_requests + spent

    def test_two_procurement_requests_cannot_overspend_a_line_item(self):
        self.widen(BALANCE)
        first, second = self.run_concurrently(self.request_procurement(6000), self.request_procurement(6000))
        self.assertEqual(sorted([first.status_code, second.status_code]), [201, 400])
        self.assertEqual(ProcurementRequest.objects.count(), 1)
        self.assertLessEqual(self.committed_on_item(), 10000)

    def test_procurement_request_and_manual_disbursement_cannot_overspend_together(self):
        self.widen(BALANCE, seconds=2)  # both requests do several remote queries first; keep the window wide
        finance = self.client_for(self.finance)
        disburse = lambda: finance.post("/api/financial/disbursements/", {  # noqa: E731
            "line_item": self.item.id, "amount": "5000", "reference_number": "OR-1", "disbursed_on": str(date.today()),
        })
        procure, disbursed = self.run_concurrently(self.request_procurement(8000), disburse)
        self.assertEqual(sorted([procure.status_code, disbursed.status_code]), [201, 400])
        self.assertLessEqual(self.committed_on_item(), 10000)

    def test_two_approvals_of_a_new_item_realignment_create_one_item(self):
        realignment = BudgetRealignment.objects.create(
            from_line_item=self.item, new_item_category="mooe", new_item_description="Laptop rental", amount=3000,
            tier="bor", status="pending_bor", justification="Need it", requested_by=self.leader,
        )
        self.widen("financial_monitoring.views.review_realignment", before=True)
        approve = lambda: self.client_for(self.finance).post(  # noqa: E731
            f"/api/financial/realignments/{realignment.id}/review/", {"decision": "approved"})
        first, second = self.run_concurrently(approve, approve)
        self.assertEqual(sorted([first.status_code, second.status_code]), [200, 400])
        self.assertEqual(LineItem.objects.filter(description="Laptop rental").count(), 1)

    def test_two_completed_clicks_post_one_disbursement_and_no_500(self):
        pr = ProcurementRequest.objects.create(
            line_item=self.item, description="Reagents", amount=4000, fiscal_year=2026, quarter=4,
            status="ready_for_release", requested_by=self.leader,
        )
        self.widen("financial_monitoring.views.post_procurement_disbursement", before=True)
        complete = lambda: self.client_for(self.officer).post(f"{PR_URL}{pr.id}/status/", {"status": "completed"})  # noqa: E731
        first, second = self.run_concurrently(complete, complete)
        self.assertEqual(sorted([first.status_code, second.status_code]), [200, 400])
        self.assertEqual(Disbursement.objects.filter(procurement_request=pr).count(), 1)

    def test_same_idempotency_key_sent_twice_at_once_creates_one_request(self):
        self.widen(BALANCE)
        key = "form-6b1f2c3d-0001"
        first, second = self.run_concurrently(self.request_procurement(1000, key), self.request_procurement(1000, key))
        self.assertIn(first.status_code, (201, 409))
        self.assertIn(second.status_code, (201, 409))
        self.assertIn(201, (first.status_code, second.status_code))
        self.assertEqual(ProcurementRequest.objects.count(), 1)
