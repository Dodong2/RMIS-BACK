from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from accounts.testing import RMISTestCase
from budget_lib.models import LineItem, LineItemBudget
from financial_monitoring.models import BudgetRealignment, Disbursement, ProcurementRequest
from financial_monitoring.serializers import uncommitted_balance
from research_projects.models import Project

URL = "/api/financial/realignments/"


def with_year_one(item):
    """Task 22: a one-year project (Q1-Q4 = Year 1) with the item's amount spread evenly over its four quarters."""
    project = item.budget.project
    project.start_date = date.today() - timedelta(days=30)
    project.target_end_date = project.start_date + timedelta(days=330)
    project.save(update_fields=["start_date", "target_end_date"])
    item.allocations = [{"period": f"Q{q}", "amount": str(Decimal(item.amount) / 4)} for q in range(1, 5)]
    item.save(update_fields=["allocations"])
    return item


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

        new_item = {"from_line_item": self.travel.id, "new_item_category": "co", "new_item_description": "Rent Expenses", "amount": "1000", "justification": "Need it"}
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
        self.item = with_year_one(LineItem.objects.create(budget=budget, category="mooe", description="Supplies", amount=10000))
        self.leader_client = self.client_for(self.leader)
        self.officer = self.make_user("procurement_officer_lib", first_name="Ana", last_name="Cruz")
        self.officer_client = self.client_for(self.officer)
        response = self.leader_client.post(PR_URL, {
            "line_item": self.item.id, "description": "Reagents", "amount": "4000", "project_year": 1, "quarter": 4,
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

    def test_completed_request_is_posted_as_a_disbursement(self):
        """Client 2026-10-12: completing a request moves the project's Actual and Available."""
        self.officer_client.post(f"{PR_URL}{self.pr.id}/receive/")
        self.status("ready_for_release")
        self.assertFalse(Disbursement.objects.exists())

        self.assertEqual(self.status("completed").status_code, 200)
        disbursement = Disbursement.objects.get()
        self.assertEqual((disbursement.line_item, disbursement.amount), (self.item, 4000))
        self.assertEqual(disbursement.procurement_request, self.pr)
        self.assertEqual(disbursement.reference_number, f"PR-{self.pr.id:04d}")
        self.assertEqual(disbursement.recorded_by, self.officer)

        summary = self.leader_client.get(f"/api/financial/budgets/{self.item.budget_id}/summary/").data
        self.assertEqual((summary["totals"]["actual"], summary["totals"]["available"]), (4000, 6000))
        ledger = self.leader_client.get("/api/financial/disbursements/", {"budget": self.item.budget_id}).data
        self.assertEqual(ledger[0]["procurement_request"], self.pr.id)

        # The released money no longer counts as an open request, so a new one can use the rest.
        response = self.leader_client.post(PR_URL, {
            "line_item": self.item.id, "description": "More", "amount": "6000", "project_year": 1, "quarter": 4,
        })
        self.assertEqual(response.status_code, 201, response.data)
        response = self.leader_client.post(PR_URL, {
            "line_item": self.item.id, "description": "Too much", "amount": "1", "project_year": 1, "quarter": 4,
        })
        self.assertEqual(response.status_code, 400)

    def test_open_request_reserves_its_amount_from_manual_disbursements_and_realignments(self):
        """2026-10-12 concurrency audit: Actual + open requests may never exceed Adjusted, whatever the order."""
        finance = self.client_for(self.make_user("finance_budget"))
        response = finance.post("/api/financial/disbursements/", {
            "line_item": self.item.id, "amount": "6001", "reference_number": "OR-9", "disbursed_on": "2026-10-12",
        })
        self.assertEqual(response.status_code, 400)  # 4000 is reserved by the open request
        other = LineItem.objects.create(budget=self.item.budget, category="mooe", description="Seminar", amount=1000)
        response = self.leader_client.post("/api/financial/realignments/", [{
            "from_line_item": self.item.id, "to_line_item": other.id, "amount": "6001", "justification": "x",
        }], format="json")
        self.assertEqual(response.status_code, 400)


BALANCE_URL = "/api/financial/procurement-balance/"
TWO_YEARS = {  # irregular on purpose: Year 1 = 100,000 (no Q3), Year 2 = 100,000 (Q1-Q2 only)
    "Y1Q1": 30000, "Y1Q2": 40000, "Y1Q3": 0, "Y1Q4": 30000, "Y2Q1": 60000, "Y2Q2": 40000, "Y2Q3": 0, "Y2Q4": 0,
}


class YearBudgetTests(RMISTestCase):
    """Task 22 (2026-10-30): procurement is charged against a project year of the LIB item; the year's available
    amount (approved - non-cancelled requests) is the hard cap, the quarter is optional and informational."""

    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader")
        self.project = Project.objects.create(
            title="P", project_code="P-2Y", funding_type="core_funded", lead=self.leader,
            start_date=date(2026, 1, 1), target_end_date=date(2027, 12, 31),
        )
        self.budget = LineItemBudget.objects.create(project=self.project, version_number=1, status="certified")
        self.item = LineItem.objects.create(
            budget=self.budget, category="mooe", description="Internet Subscription Expenses", amount=200000,
            allocations=[{"period": p, "amount": str(a)} for p, a in TWO_YEARS.items()],
        )
        self.leader_client = self.client_for(self.leader)

    def file(self, amount, year=1, quarter=None):
        payload = {"line_item": self.item.id, "description": "Internet", "amount": str(amount), "project_year": year}
        if quarter is not None:
            payload["quarter"] = quarter
        return self.leader_client.post(PR_URL, payload)

    def year(self, number):
        response = self.leader_client.get(BALANCE_URL, {"line_item": self.item.id})
        self.assertEqual(response.status_code, 200, response.data)
        return next(y for y in response.data["years"] if y["year"] == number)

    def figures(self, number):
        y = self.year(number)
        return {key: y[key] for key in ("approved", "committed", "paid", "unpaid", "available")}

    def test_balance_lists_each_year_with_its_own_allocation_and_quarters(self):
        response = self.leader_client.get(BALANCE_URL, {"line_item": self.item.id})
        self.assertEqual([y["year"] for y in response.data["years"]], [1, 2])
        self.assertEqual(self.figures(1), {"approved": 100000, "committed": 0, "paid": 0, "unpaid": 0, "available": 100000})
        self.assertEqual([(q["quarter"], q["allocation"]) for q in self.year(1)["quarters"]], [(1, 30000), (2, 40000), (4, 30000)])
        self.assertEqual([q["quarter"] for q in self.year(2)["quarters"]], [1, 2])

    def test_unpaid_request_reserves_the_year_and_blocks_an_over_budget_one(self):
        """The client's example: 100,000 approved, 30,000 filed -> 70,000 available, 0 paid; 80,000 is refused."""
        self.assertEqual(self.file(30000).status_code, 201)
        self.assertEqual(self.figures(1), {"approved": 100000, "committed": 30000, "paid": 0, "unpaid": 30000, "available": 70000})

        response = self.file(80000)
        self.assertEqual(response.status_code, 400)
        budget = response.data["budget"]
        self.assertEqual((budget["code"], budget["available"], budget["unpaid"]), ("insufficient_budget", "70000.00", "30000.00"))
        self.assertIn("Insufficient available budget", budget["detail"])
        self.assertEqual(ProcurementRequest.objects.count(), 1)
        # Year 2 is its own allocation.
        self.assertEqual(self.file(80000, year=2).status_code, 201)
        self.assertEqual(self.figures(1)["available"], 70000)

    def test_payment_moves_unpaid_to_paid_without_changing_available(self):
        pr = ProcurementRequest.objects.get(pk=self.file(30000).data["id"])
        Disbursement.objects.create(line_item=self.item, amount=30000, disbursed_on=date(2026, 6, 1),
                                    recorded_by=self.leader, procurement_request=pr)
        self.assertEqual(self.figures(1), {"approved": 100000, "committed": 30000, "paid": 30000, "unpaid": 0, "available": 70000})

    def test_completed_but_unpaid_still_reserves_and_cancelled_releases(self):
        pr = ProcurementRequest.objects.get(pk=self.file(30000).data["id"])
        ProcurementRequest.objects.filter(pk=pr.pk).update(status="completed")
        self.assertEqual(self.figures(1)["unpaid"], 30000)
        self.assertEqual(uncommitted_balance(self.item), 170000)
        ProcurementRequest.objects.filter(pk=pr.pk).update(status="cancelled")
        self.assertEqual(self.figures(1)["available"], 100000)
        self.assertEqual(uncommitted_balance(self.item), 200000)

    def test_quarter_is_optional_and_only_informational(self):
        response = self.file(20000)
        self.assertEqual((response.status_code, response.data["quarter"], response.data["project_year"]), (201, None, 1))
        self.assertEqual(self.file(50000, quarter=1).status_code, 201)  # above Q1's 30,000: the year is the cap
        q1 = self.year(1)["quarters"][0]
        self.assertEqual((q1["allocation"], q1["committed"], q1["remaining"]), (30000, 50000, -20000))
        self.assertEqual(self.figures(1)["available"], 30000)

    def test_invalid_year_quarter_or_amount_is_rejected(self):
        self.assertIn("project_year", self.file(1000, year=3).data)
        self.assertIn("quarter", self.file(1000, year=1, quarter=3).data)  # Q3 of Year 1 has no allocation
        self.assertIn("quarter", self.file(1000, year=2, quarter=4).data)
        self.assertIn("amount", self.file(0).data)
        missing = self.leader_client.post(PR_URL, {"line_item": self.item.id, "description": "x", "amount": "1"})
        self.assertIn("project_year", missing.data)
        self.assertFalse(ProcurementRequest.objects.exists())

    def test_realignments_count_in_the_year_they_were_approved(self):
        other = LineItem.objects.create(budget=self.budget, category="mooe", description="Travel", amount=50000)
        for source, target, day in ((other, self.item, date(2027, 3, 1)), (self.item, other, date(2026, 5, 1))):
            BudgetRealignment.objects.create(
                from_line_item=source, to_line_item=target, amount=10000, tier="minor", status="approved",
                justification="x", requested_by=self.leader, reviewed_at=datetime.combine(day, time(9), tzinfo=UTC),
            )
        self.assertEqual((self.figures(1)["approved"], self.figures(2)["approved"]), (90000, 110000))

    def test_manual_disbursement_counts_in_the_year_of_its_date(self):
        Disbursement.objects.create(line_item=self.item, amount=5000, disbursed_on=date(2027, 2, 1), recorded_by=self.leader)
        self.assertEqual(self.figures(2), {"approved": 100000, "committed": 5000, "paid": 5000, "unpaid": 0, "available": 95000})
        self.assertEqual(self.figures(1)["committed"], 0)

    def test_returned_request_keeps_its_reservation_and_resubmit_does_not_reserve_twice(self):
        pr = ProcurementRequest.objects.get(pk=self.file(60000).data["id"])
        officer = self.client_for(self.make_user("procurement_officer_lib"))
        officer.post(f"{PR_URL}{pr.id}/receive/")
        officer.post(f"{PR_URL}{pr.id}/status/", {"status": "returned_for_revision", "remarks": "Use a 42-inch unit"})
        self.assertEqual(self.figures(1)["committed"], 60000)

        self.assertEqual(self.leader_client.post(f"{PR_URL}{pr.id}/resubmit/", {"amount": "100001"}).status_code, 400)
        response = self.leader_client.post(f"{PR_URL}{pr.id}/resubmit/", {"amount": "100000", "quarter": 2})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((self.figures(1)["committed"], self.figures(1)["available"]), (100000, 0))

    def test_other_leader_cannot_see_or_spend_the_budget(self):
        stranger = self.client_for(self.make_user("project_leader"))
        self.assertEqual(stranger.get(BALANCE_URL, {"line_item": self.item.id}).status_code, 404)
        response = stranger.post(PR_URL, {"line_item": self.item.id, "description": "x", "amount": "1", "project_year": 1})
        self.assertIn(response.status_code, (400, 403, 404))
        self.assertFalse(ProcurementRequest.objects.exists())

    def test_only_the_current_certified_lib_of_an_active_project(self):
        self.project.status = "completed"
        self.project.save(update_fields=["status"])
        self.assertEqual(self.file(1000).status_code, 400)
        self.project.status = "active"
        self.project.save(update_fields=["status"])
        self.budget.is_current = False
        self.budget.save(update_fields=["is_current"])
        self.assertEqual(self.file(1000).status_code, 400)
        self.assertFalse(ProcurementRequest.objects.exists())

    def test_a_failed_create_leaves_no_reservation(self):
        self._patch("financial_monitoring.views.record_procurement_event", side_effect=RuntimeError("boom"))
        self.leader_client.raise_request_exception = False
        self.assertEqual(self.file(30000).status_code, 500)
        self.assertFalse(ProcurementRequest.objects.exists())
        self.assertEqual(self.figures(1)["available"], 100000)
