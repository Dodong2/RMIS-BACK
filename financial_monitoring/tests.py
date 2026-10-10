from accounts.testing import RMISTestCase
from budget_lib.models import LineItem, LineItemBudget
from financial_monitoring.models import BudgetRealignment
from research_projects.models import Project

URL = "/api/financial/realignments/"


class BulkRealignmentTests(RMISTestCase):
    """Client 2026-10-10: several realignments in one submission, one open request per project, per-item review."""

    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader")
        self.project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=self.leader)
        budget = LineItemBudget.objects.create(project=self.project, version_number=1, status="certified")
        self.travel = LineItem.objects.create(budget=budget, category="mooe", description="Travel", amount=10000)
        self.seminar = LineItem.objects.create(budget=budget, category="mooe", description="Seminar", amount=10000)
        self.supplies = LineItem.objects.create(budget=budget, category="mooe", description="Supplies", amount=10000)
        self.client = self.client_for(self.leader)

    def row(self, source, target, amount):
        return {"from_line_item": source.id, "to_line_item": target.id, "amount": str(amount), "justification": "Need it"}

    def test_bulk_request_is_saved_under_one_batch(self):
        response = self.client.post(URL, [self.row(self.travel, self.seminar, 1000), self.row(self.supplies, self.seminar, 2000)], format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(BudgetRealignment.objects.values("batch").distinct().count(), 1)
        self.assertEqual(BudgetRealignment.objects.filter(status="pending_approval").count(), 2)

    def test_single_object_still_works(self):
        response = self.client.post(URL, self.row(self.travel, self.seminar, 1000), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNotNone(response.data["batch"])

    def test_no_new_request_while_one_is_pending(self):
        self.client.post(URL, [self.row(self.travel, self.seminar, 1000)], format="json")
        response = self.client.post(URL, [self.row(self.supplies, self.seminar, 1000)], format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("pending", str(response.data))

    def test_can_request_again_in_the_same_year_once_reviewed(self):
        self.client.post(URL, [self.row(self.travel, self.seminar, 1000)], format="json")
        reviewer = self.client_for(self.make_user("finance_budget"))
        realignment = BudgetRealignment.objects.get()
        self.assertEqual(reviewer.post(f"{URL}{realignment.id}/review/", {"decision": "approved"}).status_code, 200)

        response = self.client.post(URL, [self.row(self.supplies, self.seminar, 1000)], format="json")
        self.assertEqual(response.status_code, 201, response.data)

    def test_rows_sharing_a_source_must_fit_its_balance_together(self):
        response = self.client.post(URL, [self.row(self.travel, self.seminar, 6000), self.row(self.travel, self.supplies, 6000)], format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(BudgetRealignment.objects.exists())

    def test_invalid_row_rejects_the_whole_batch(self):
        response = self.client.post(URL, [self.row(self.travel, self.seminar, 1000), self.row(self.travel, self.travel, 1000)], format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(BudgetRealignment.objects.exists())

    def test_empty_list_is_rejected(self):
        self.assertEqual(self.client.post(URL, [], format="json").status_code, 400)
