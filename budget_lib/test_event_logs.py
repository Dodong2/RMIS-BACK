"""Event Logs Budget (client Task 46, 2026-11-06): a database-only record of who did which LIB action on which project.
Logged roles (Carl's Q5): project_leader, procurement_officer_lib, finance_budget and system_admin; crc_chair is not."""
import datetime
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib import admin
from django.utils import timezone

from accounts.testing import RMISTestCase
from research_projects.models import Project

from .models import BudgetEventLog, LineItem, LineItemBudget
from .tests import add_registration_rows, attach_approval_documents


class BudgetEventLogTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader", first_name="Ana", last_name="Cruz", staff_id="1001")
        self.crc = self.make_user("crc_chair")
        self.officer = self.make_user("finance_budget", first_name="Ben", last_name="Reyes", staff_id="2002")
        self.admin = self.make_user("system_admin")
        self.project = Project.objects.create(
            title="Vetiver Study", project_code="NTP-46", ntp_number="NTP-46", funding_type="core_funded", lead=self.leader,
            campus="San Pablo", total_cost="1000", start_date=date(2026, 1, 1), target_end_date=date(2026, 12, 31),
        )
        self.budget = LineItemBudget.objects.create(project=self.project, version_number=1)
        self.item = LineItem.objects.create(budget=self.budget, category="mooe", description="Travel", amount=Decimal("1000"))
        attach_approval_documents(self.project, self.leader)
        add_registration_rows(self.project)

    def act(self, user, step, **data):
        return self.client_for(user).post(f"/api/budget/budgets/{self.budget.id}/{step}/", data, format="json")

    def events(self):
        return list(BudgetEventLog.objects.order_by("id").values_list("event", flat=True))

    def test_submit_records_actor_project_and_status_change(self):
        self.assertEqual(self.act(self.leader, "submit").status_code, 200)
        log = BudgetEventLog.objects.get()
        self.assertEqual(log.event, "LIB_SUBMITTED")
        self.assertEqual((log.actor, log.actor_name, log.actor_email, log.actor_staff_id, log.actor_role),
                         (self.leader, "Ana Cruz", self.leader.email, "1001", "project_leader"))
        self.assertEqual((log.project, log.project_ref, log.project_code, log.project_title),
                         (self.project, self.project.pk, "NTP-46", "Vetiver Study"))
        self.assertEqual((log.target_type, log.target_id), ("budget_lib.LineItemBudget", self.budget.pk))
        self.assertEqual((log.previous, log.new), ({"status": "draft"}, {"status": "submitted"}))
        self.assertTrue(timezone.is_aware(log.created_at))

    def test_full_chain_logs_the_logged_roles_only(self):
        self.act(self.leader, "submit")
        self.act(self.crc, "for-checking")  # CRC/CRD is not a logged role (Q5)
        self.act(self.officer, "start-certification")
        self.act(self.officer, "certify")
        self.assertEqual(self.events(), ["LIB_SUBMITTED", "LIB_CERTIFICATION_STARTED", "LIB_CERTIFIED"])
        certified = BudgetEventLog.objects.get(event="LIB_CERTIFIED")
        self.assertEqual((certified.actor_role, certified.previous, certified.new),
                         ("finance_budget", {"status": "certifying"}, {"status": "certified"}))

    def test_system_admin_actions_are_logged(self):
        self.act(self.leader, "submit")
        self.assertEqual(self.act(self.admin, "hold", remarks="Fix the travel line").status_code, 200)
        hold = BudgetEventLog.objects.get(event="LIB_PUT_ON_HOLD")
        self.assertEqual((hold.actor_role, hold.remarks, hold.new), ("system_admin", "Fix the travel line", {"status": "returned"}))

    def test_hold_resubmit_and_comment_keep_the_remarks(self):
        self.act(self.leader, "submit")
        LineItemBudget.objects.filter(pk=self.budget.pk).update(status="certifying")
        self.assertEqual(self.act(self.officer, "comment", remarks="Check the unit cost").status_code, 200)
        self.act(self.officer, "hold", remarks="Unit cost too high")
        self.act(self.leader, "resubmit")
        rows = list(BudgetEventLog.objects.order_by("id").values_list("event", "remarks"))
        self.assertEqual(rows, [("LIB_SUBMITTED", ""), ("LIB_REVIEW_COMMENT", "Check the unit cost"),
                                ("LIB_PUT_ON_HOLD", "Unit cost too high"), ("LIB_RESUBMITTED", "")])

    def test_refused_or_repeated_steps_log_nothing(self):
        self.assertEqual(self.act(self.officer, "certify").status_code, 404)  # not forwarded: hidden from Finance
        self.assertEqual(self.act(self.make_user("project_leader"), "submit").status_code, 404)  # not their project
        LineItem.objects.filter(pk=self.item.pk).update(amount=Decimal("999"))
        self.assertEqual(self.act(self.leader, "submit").status_code, 400)  # Grand Total != Total Cost
        self.assertEqual(self.events(), [])
        LineItem.objects.filter(pk=self.item.pk).update(amount=Decimal("1000"))
        self.assertEqual(self.act(self.leader, "submit").status_code, 200)
        self.assertEqual(self.act(self.leader, "submit").status_code, 400)  # a retry of the same step
        self.assertEqual(self.events(), ["LIB_SUBMITTED"])

    def test_line_item_add_edit_remove_by_the_leader(self):
        client = self.client_for(self.leader)
        row = {"budget": self.budget.id, "category": "mooe", "description": "Training Expenses", "amount": "10"}
        new_id = client.post("/api/budget/line-items/", row, format="json").data["id"]
        client.patch(f"/api/budget/line-items/{new_id}/", {"justification": "Seminar"}, format="json")
        client.delete(f"/api/budget/line-items/{new_id}/")
        added, edited, removed = BudgetEventLog.objects.order_by("id")
        self.assertEqual((added.event, added.target_id, added.amount, added.new["description"]),
                         ("LIB_LINE_ITEM_ADDED", new_id, Decimal("10"), "Training Expenses"))
        self.assertEqual((edited.event, edited.previous, edited.new),
                         ("LIB_LINE_ITEM_EDITED", {"justification": ""}, {"justification": "Seminar"}))
        self.assertEqual((removed.event, removed.target_id, removed.previous["description"], removed.new),
                         ("LIB_LINE_ITEM_REMOVED", new_id, "Training Expenses", None))

    def test_refused_line_item_edit_logs_nothing(self):
        LineItemBudget.objects.filter(pk=self.budget.pk).update(status="submitted")
        response = self.client_for(self.leader).patch(f"/api/budget/line-items/{self.item.id}/", {"justification": "X"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.events(), [])

    def test_finance_edit_keeps_old_and_new_values_and_the_reason(self):
        LineItemBudget.objects.filter(pk=self.budget.pk).update(status="certifying")
        self.item.quantity, self.item.unit_cost = Decimal("2"), Decimal("500")
        self.item.allocations = [{"period": "Q1", "amount": "1000.00"}]
        self.item.save()
        items = [{"id": self.item.id, "specification": "Bus fare", "reason": "Per the canvass"}]
        response = self.client_for(self.officer).post(f"/api/budget/budgets/{self.budget.id}/finance-edit/", {"items": items}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        log = BudgetEventLog.objects.get()
        self.assertEqual((log.event, log.target_id, log.remarks, log.amount),
                         ("LIB_LINE_ITEM_EDITED_BY_FINANCE", self.item.pk, "Per the canvass", Decimal("1000.00")))
        self.assertEqual((log.previous, log.new), ({"specification": ""}, {"specification": "Bus fare"}))

    def test_refused_finance_edit_logs_nothing(self):
        LineItemBudget.objects.filter(pk=self.budget.pk).update(status="certifying")
        self.item.quantity, self.item.unit_cost = Decimal("2"), Decimal("500")
        self.item.allocations = [{"period": "Q1", "amount": "1000.00"}]
        self.item.save()
        items = [{"id": self.item.id, "unit_cost": "400", "reason": "Lower"}]  # Grand Total would no longer match
        response = self.client_for(self.officer).post(f"/api/budget/budgets/{self.budget.id}/finance-edit/", {"items": items}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.events(), [])

    def test_the_log_outlives_profile_changes_and_a_deleted_project(self):
        self.act(self.leader, "submit")
        self.leader.first_name = "Changed"
        self.leader.save()
        Project.objects.filter(pk=self.project.pk).delete()
        log = BudgetEventLog.objects.get()
        self.assertEqual((log.project, log.project_ref, log.project_code, log.actor_name),
                         (None, self.project.pk, "NTP-46", "Ana Cruz"))

    def test_display_time_follows_the_readable_format(self):
        log = BudgetEventLog(created_at=datetime.datetime(2026, 7, 10, 5, 34, tzinfo=datetime.timezone.utc))
        self.assertEqual(log.display_time, "Jul 10, 2026 · 1:34 PM")  # 05:34 UTC = 1:34 PM Asia/Manila
        log.created_at = datetime.datetime(2026, 1, 5, 0, 5, tzinfo=ZoneInfo("Asia/Manila"))
        self.assertEqual(log.display_time, "Jan 5, 2026 · 12:05 AM")

    def test_no_admin_page_for_the_log(self):
        self.assertNotIn(BudgetEventLog, admin.site._registry)


class RegistrationLibEventLogTests(RMISTestCase):
    """Task 46-B (Carl 2026-11-06): the LIB saved with a registration is logged too."""

    ROWS = [
        {"category": "mooe", "description": "Traveling Expenses - Local", "fiscal_year": 2026, "unit": "pax", "quantity": "4", "unit_cost": "2500"},
        {"category": "co", "description": "Information and Communication Technology Equipment", "fiscal_year": 2026, "unit": "unit",
         "quantity": "1", "unit_cost": "7500"},
    ]

    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader", staff_id="1001")
        self.project = Project.objects.create(title="B", project_code="B-1", funding_type="core_funded", lead=self.leader)

    def post_lib(self, rows):
        return self.client_for(self.leader).post(f"/api/projects/{self.project.id}/lib/", {"line_items": rows}, format="json")

    def test_registration_lib_step_logs_every_line_item(self):
        self.assertEqual(self.post_lib(self.ROWS).status_code, 201)
        log = BudgetEventLog.objects.get()
        self.assertEqual((log.event, log.actor_role, log.amount, log.details["source"]),
                         ("LIB_CREATED_AT_REGISTRATION", "project_leader", Decimal("17500.00"), "registration LIB step"))
        self.assertEqual([(i["description"], i["amount"]) for i in log.new["line_items"]],
                         [("Traveling Expenses - Local", "10000.00"), ("Information and Communication Technology Equipment", "7500.00")])

    def test_refused_registration_lib_logs_nothing(self):
        self.assertEqual(self.post_lib([{**self.ROWS[0], "unit": "nope"}]).status_code, 400)
        self.assertFalse(BudgetEventLog.objects.exists())
        self.post_lib(self.ROWS)
        self.assertEqual(self.post_lib(self.ROWS).status_code, 400)  # already has a LIB
        self.assertEqual(BudgetEventLog.objects.count(), 1)
