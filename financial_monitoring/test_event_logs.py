"""Event Logs Budget, procurement/realignment/disbursement part (client Task 46-B, 2026-11-06)."""
from datetime import date
from decimal import Decimal

from accounts.testing import RMISTestCase
from budget_lib.models import BudgetEventLog, LineItem, LineItemBudget
from research_projects.models import Project

from .tests import with_year_one

PR_URL = "/api/financial/procurement-requests/"
RA_URL = "/api/financial/realignments/"


class ProcurementEventLogTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader", first_name="Ana", last_name="Cruz", staff_id="1001")
        self.officer = self.make_user("procurement_officer_lib", first_name="Leo", last_name="Santos", staff_id="3003")
        self.finance = self.make_user("finance_budget", staff_id="2002")
        self.project = Project.objects.create(title="Vetiver", project_code="NTP-46B", funding_type="core_funded", lead=self.leader)
        budget = LineItemBudget.objects.create(project=self.project, version_number=1, status="certified")
        self.item = with_year_one(LineItem.objects.create(budget=budget, category="mooe", description="Supplies", amount=10000))
        self.leader_client, self.officer_client = self.client_for(self.leader), self.client_for(self.officer)

    def file_request(self, **data):
        payload = {"line_item": self.item.id, "description": "Reagents", "amount": "4000", "project_year": 1, "quarter": 4, **data}
        return self.leader_client.post(PR_URL, payload)

    def log(self, event):
        return BudgetEventLog.objects.get(event=event)

    def test_the_whole_procurement_flow_is_logged_with_its_actors(self):
        pr = self.file_request().data["id"]
        self.officer_client.post(f"{PR_URL}{pr}/receive/")
        self.officer_client.post(f"{PR_URL}{pr}/status/", {"status": "returned_for_revision", "remarks": "Attach a quotation"})
        self.leader_client.post(f"{PR_URL}{pr}/resubmit/", {"amount": "4500", "remarks": "Quotation attached"})
        self.officer_client.post(f"{PR_URL}{pr}/receive/")
        self.officer_client.post(f"{PR_URL}{pr}/status/", {"status": "for_procurement"})
        self.officer_client.post(f"{PR_URL}{pr}/status/", {"status": "completed"})
        paid = self.client_for(self.finance).post(f"{PR_URL}{pr}/pay/", {"paid_on": str(date.today()), "reference_number": "DV-1"})
        self.assertEqual(paid.status_code, 200, paid.data)

        rows = list(BudgetEventLog.objects.order_by("id").values_list("event", "actor_role"))
        self.assertEqual(rows, [
            ("PROCUREMENT_REQUEST_CREATED", "project_leader"), ("PROCUREMENT_REQUEST_RECEIVED", "procurement_officer_lib"),
            ("PROCUREMENT_RETURNED_FOR_REVISION", "procurement_officer_lib"), ("PROCUREMENT_REQUEST_RESUBMITTED", "project_leader"),
            ("PROCUREMENT_REQUEST_RECEIVED", "procurement_officer_lib"), ("PROCUREMENT_STATUS_UPDATED", "procurement_officer_lib"),
            ("PROCUREMENT_COMPLETED", "procurement_officer_lib"), ("PROCUREMENT_PAYMENT_CONFIRMED", "finance_budget"),
        ])
        self.assertTrue(all(log.project_id == self.project.pk and log.target_id == pr for log in BudgetEventLog.objects.all()))
        returned = self.log("PROCUREMENT_RETURNED_FOR_REVISION")
        self.assertEqual((returned.actor_name, returned.actor_staff_id, returned.remarks, returned.previous, returned.new),
                         ("Leo Santos", "3003", "Attach a quotation", {"status": "under_review"}, {"status": "returned_for_revision"}))
        resubmitted = self.log("PROCUREMENT_REQUEST_RESUBMITTED")
        self.assertEqual((resubmitted.previous, resubmitted.new, resubmitted.remarks, resubmitted.amount),
                         ({"status": "returned_for_revision", "amount": "4000.00"}, {"status": "requested", "amount": "4500.00"},
                          "Quotation attached", Decimal("4500.00")))
        payment = self.log("PROCUREMENT_PAYMENT_CONFIRMED")
        self.assertEqual((payment.new["reference_number"], payment.new["paid"], payment.details["line_item_description"]),
                         ("DV-1", "4500.00", "Supplies"))

    def test_refused_and_retried_actions_log_nothing_extra(self):
        self.assertEqual(self.file_request(amount="999999").status_code, 400)  # over the year's balance
        pr = self.file_request().data["id"]
        self.assertEqual(self.officer_client.post(f"{PR_URL}{pr}/status/", {"status": "completed"}).status_code, 400)  # receive first
        self.assertEqual(self.leader_client.post(f"{PR_URL}{pr}/receive/").status_code, 403)
        self.officer_client.post(f"{PR_URL}{pr}/receive/")
        self.assertEqual(self.officer_client.post(f"{PR_URL}{pr}/receive/").status_code, 400)  # a second click
        pay = {"paid_on": str(date.today()), "reference_number": "DV-1"}
        self.assertEqual(self.client_for(self.finance).post(f"{PR_URL}{pr}/pay/", pay).status_code, 400)  # not completed
        self.assertEqual(list(BudgetEventLog.objects.order_by("id").values_list("event", flat=True)),
                         ["PROCUREMENT_REQUEST_CREATED", "PROCUREMENT_REQUEST_RECEIVED"])

    def test_an_idempotent_replay_does_not_log_twice(self):
        payload = {"line_item": self.item.id, "description": "Reagents", "amount": "4000", "project_year": 1, "quarter": 4}
        first = self.leader_client.post(PR_URL, payload, HTTP_IDEMPOTENCY_KEY="same-click")
        again = self.leader_client.post(PR_URL, payload, HTTP_IDEMPOTENCY_KEY="same-click")
        self.assertEqual((first.status_code, again.status_code), (201, 201))
        self.assertEqual(BudgetEventLog.objects.filter(event="PROCUREMENT_REQUEST_CREATED").count(), 1)

    def test_disbursement_and_realignment_are_logged(self):
        finance = self.client_for(self.finance)
        response = finance.post("/api/financial/disbursements/", {
            "line_item": self.item.id, "amount": "1500", "reference_number": "OR-9", "disbursed_on": "2026-10-12", "payee": "Shop",
        })
        self.assertEqual(response.status_code, 201, response.data)
        other = LineItem.objects.create(budget=self.item.budget, category="mooe", description="Seminar", amount=1000)
        response = self.leader_client.post(RA_URL, [{"from_line_item": self.item.id, "to_line_item": other.id, "amount": "500",
                                                     "justification": "More participants"}], format="json")
        self.assertEqual(response.status_code, 201, response.data)
        realignment = response.data[0]["id"]
        self.assertEqual(finance.post(f"{RA_URL}{realignment}/review/", {"decision": "approved"}).status_code, 200)

        disbursed = self.log("DISBURSEMENT_RECORDED")
        self.assertEqual((disbursed.actor_role, disbursed.amount, disbursed.new["reference_number"], disbursed.new["payee"]),
                         ("finance_budget", Decimal("1500.00"), "OR-9", "Shop"))
        requested, approved = self.log("REALIGNMENT_REQUESTED"), self.log("REALIGNMENT_APPROVED")
        self.assertEqual((requested.actor_role, requested.remarks, requested.amount, requested.details["to_line_item_description"]),
                         ("project_leader", "More participants", Decimal("500.00"), "Seminar"))
        self.assertEqual((approved.actor_role, approved.previous, approved.target_id), ("finance_budget", {"status": "pending_approval"}, realignment))
        self.assertEqual(approved.new["status"], "approved")

    def test_rejected_realignment_is_logged_as_rejected(self):
        other = LineItem.objects.create(budget=self.item.budget, category="mooe", description="Seminar", amount=1000)
        realignment = self.leader_client.post(RA_URL, [{"from_line_item": self.item.id, "to_line_item": other.id, "amount": "500",
                                                        "justification": "x"}], format="json").data[0]["id"]
        self.client_for(self.make_user("system_admin")).post(f"{RA_URL}{realignment}/review/", {"decision": "rejected"})
        rejected = self.log("REALIGNMENT_REJECTED")
        self.assertEqual((rejected.actor_role, rejected.new), ("system_admin", {"status": "rejected"}))
