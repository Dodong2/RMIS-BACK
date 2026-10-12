from accounts.testing import RMISTestCase
from budget_lib.models import LineItem, LineItemBudget
from financial_monitoring.models import BudgetRealignment, ProcurementRequest
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
        self.equipment = LineItem.objects.create(budget=budget, category="co", description="Equipment", amount=10000)
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

    def test_reviewers_cannot_file_a_request(self):
        """Client 2026-10-11: finance_budget and system_admin only approve."""
        for role in ("finance_budget", "system_admin"):
            response = self.client_for(self.make_user(role)).post(URL, [self.row(self.travel, self.seminar, 1000)], format="json")
            self.assertEqual(response.status_code, 403)

    def test_empty_list_is_rejected(self):
        self.assertEqual(self.client.post(URL, [], format="json").status_code, 400)

    def test_realignment_must_stay_within_the_same_class(self):
        response = self.client.post(URL, [self.row(self.travel, self.equipment, 1000)], format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("same class", str(response.data))

        new_item = {"from_line_item": self.travel.id, "new_item_category": "co", "new_item_description": "Laptop", "amount": "1000", "justification": "Need it"}
        self.assertEqual(self.client.post(URL, [new_item], format="json").status_code, 400)
        new_item["new_item_category"] = "mooe"
        self.assertEqual(self.client.post(URL, [new_item], format="json").status_code, 201)


PR_URL = "/api/financial/procurement-requests/"


class ProcurementTrackingTests(RMISTestCase):
    """Client 2026-10-12: Request Submitted -> Received (Under Review) -> officer-picked statuses -> Completed."""

    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader")
        project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=self.leader)
        budget = LineItemBudget.objects.create(project=project, version_number=1, status="certified")
        self.item = LineItem.objects.create(budget=budget, category="mooe", description="Supplies", amount=10000)
        self.leader_client = self.client_for(self.leader)
        self.officer = self.make_user("procurement_officer_lib", first_name="Ana", last_name="Cruz")
        self.officer_client = self.client_for(self.officer)
        response = self.leader_client.post(PR_URL, {
            "line_item": self.item.id, "description": "Reagents", "amount": "4000", "fiscal_year": 2026, "quarter": 4,
        })
        self.assertEqual(response.status_code, 201, response.data)
        self.pr = ProcurementRequest.objects.get()

    def status(self, new_status, remarks=None):
        payload = {"status": new_status, **({"remarks": remarks} if remarks is not None else {})}
        return self.officer_client.post(f"{PR_URL}{self.pr.id}/status/", payload)

    def test_new_request_is_submitted_and_must_be_received_first(self):
        self.assertEqual(self.pr.status, "requested")
        self.assertEqual(self.status("for_procurement").status_code, 400)

        response = self.officer_client.post(f"{PR_URL}{self.pr.id}/receive/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "under_review")
        self.assertEqual(response.data["received_by_name"], "Ana Cruz")
        self.assertEqual(self.officer_client.post(f"{PR_URL}{self.pr.id}/receive/").status_code, 400)

    def test_leader_cannot_receive_or_update(self):
        self.assertEqual(self.leader_client.post(f"{PR_URL}{self.pr.id}/receive/").status_code, 403)
        self.assertEqual(self.leader_client.post(f"{PR_URL}{self.pr.id}/status/", {"status": "completed"}).status_code, 403)

    def test_officer_picks_statuses_until_completed(self):
        self.officer_client.post(f"{PR_URL}{self.pr.id}/receive/")
        for step in ("for_procurement", "order_placed", "delivered", "completed"):
            self.assertEqual(self.status(step).status_code, 200, step)
        self.pr.refresh_from_db()
        self.assertIsNotNone(self.pr.completed_at)
        self.assertEqual(self.status("delivered").status_code, 400)
        self.assertEqual(len(self.officer_client.get(PR_URL, {"active": "true"}).data), 0)
        self.assertEqual(self.leader_client.get(PR_URL).data[0]["status"], "completed")

    def test_return_for_revision_needs_remarks_and_leader_resubmits(self):
        self.officer_client.post(f"{PR_URL}{self.pr.id}/receive/")
        self.assertEqual(self.status("returned_for_revision", "").status_code, 400)
        self.assertEqual(self.status("returned_for_revision", "Attach a quotation").status_code, 200)
        self.assertEqual(self.status("for_procurement").status_code, 400)

        response = self.leader_client.post(f"{PR_URL}{self.pr.id}/resubmit/", {"description": "Reagents (quoted)", "amount": "9000"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "requested")
        self.assertIsNone(response.data["received_by"])
        self.assertEqual(response.data["amount"], "9000.00")
        self.assertEqual(response.data["remarks"], "")

    def test_resubmit_only_when_returned_and_within_balance(self):
        self.assertEqual(self.leader_client.post(f"{PR_URL}{self.pr.id}/resubmit/", {"description": "x"}).status_code, 400)
        self.officer_client.post(f"{PR_URL}{self.pr.id}/receive/")
        self.status("returned_for_revision", "Too high")
        self.assertEqual(self.leader_client.post(f"{PR_URL}{self.pr.id}/resubmit/", {"amount": "10001"}).status_code, 400)
