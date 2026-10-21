"""LIB review workflow (client 2026-10-21, replaces the 2026-10-18 endorse/return chain): the Project Leader submits,
the CRC Chair reviews (Start Review -> For Checking -> Ready for Certification), the Budget Officer certifies (Start
Certification -> Certify). Either level can put it On Hold for the Project Leader, who edits and resubmits to the CRC
Chair. Every step is kept in the review history, each submission with a snapshot of its line items."""
from datetime import date
from decimal import Decimal

from accounts.testing import RMISTestCase
from research_projects.models import Project

from .models import LineItem, LineItemBudget


class LibWorkflowTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader")
        self.crc = self.make_user("crc_chair")
        self.officer = self.make_user("finance_budget")
        self.project = Project.objects.create(
            title="P", project_code="P-1", funding_type="core_funded", lead=self.leader, campus="San Pablo",
            total_cost="1000", start_date=date(2026, 1, 1), target_end_date=date(2026, 12, 31),
        )
        self.budget = LineItemBudget.objects.create(project=self.project, version_number=1)
        self.item = LineItem.objects.create(budget=self.budget, category="mooe", description="Travel", amount=Decimal("1000"))

    def act(self, user, action, **data):
        return self.client_for(user).post(f"/api/budget/budgets/{self.budget.id}/{action}/", data, format="json")

    def status(self):
        self.budget.refresh_from_db()
        return self.budget.status

    def move_to(self, status):
        LineItemBudget.objects.filter(pk=self.budget.pk).update(status=status)

    def test_full_chain_from_draft_to_certified(self):
        steps = [(self.leader, "submit", "submitted"), (self.crc, "start-review", "crc_processing"),
                 (self.crc, "for-checking", "for_checking"), (self.crc, "ready", "endorsed"),
                 (self.officer, "start-certification", "certifying"), (self.officer, "certify", "certified")]
        for user, action, expected in steps:
            response = self.act(user, action)
            self.assertEqual(response.status_code, 200, (action, response.data))
            self.assertEqual(self.status(), expected, action)
        self.assertEqual((self.budget.endorsed_by, self.budget.certified_by), (self.crc, self.officer))
        self.assertEqual([r["action"] for r in response.data["reviews"]],
                         ["submitted", "review_started", "for_checking", "ready", "certification_started", "certified"])

    def test_steps_cannot_be_skipped(self):
        self.assertEqual(self.act(self.crc, "start-review").status_code, 400)  # not submitted yet
        self.act(self.leader, "submit")
        for action in ("for-checking", "ready"):
            self.assertEqual(self.act(self.crc, action).status_code, 400, action)
        for action in ("start-certification", "certify"):
            self.assertEqual(self.act(self.officer, action).status_code, 400, action)
        self.act(self.crc, "start-review")
        self.assertEqual(self.act(self.crc, "ready").status_code, 400)  # always through For Checking (client Q5)
        self.assertEqual(self.status(), "crc_processing")
        self.move_to("endorsed")
        self.assertEqual(self.act(self.officer, "certify").status_code, 400)  # Start Certification first (Q6)
        self.assertEqual(self.status(), "endorsed")

    def test_each_step_belongs_to_its_role(self):
        for user in (self.crc, self.officer, self.make_user("project_leader")):
            self.assertIn(self.act(user, "submit").status_code, (403, 404), user.role.code)
        self.act(self.leader, "submit")
        for user in (self.officer, self.leader, self.make_user("drd"), self.make_user("riuh")):
            self.assertEqual(self.act(user, "start-review").status_code, 403, user.role.code)
        self.move_to("endorsed")
        for user in (self.crc, self.leader):
            self.assertEqual(self.act(user, "start-certification").status_code, 403, user.role.code)
        self.move_to("certifying")
        self.assertEqual(self.act(self.crc, "certify").status_code, 403)
        self.assertEqual(self.status(), "certifying")

    def test_crc_chair_outside_campus_gets_404(self):
        self.act(self.leader, "submit")
        other = self.make_user("crc_chair", scope={"campus": "Los Baños"})
        self.assertEqual(self.act(other, "start-review").status_code, 404)
        self.assertEqual(self.status(), "submitted")

    def test_submit_refuses_grand_total_not_equal_to_total_cost(self):
        LineItem.objects.filter(pk=self.item.pk).update(amount="900")
        response = self.act(self.leader, "submit")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Total Project/Study Cost", str(response.data))
        self.assertEqual(self.status(), "draft")

    def test_submit_refuses_empty_lib(self):
        self.item.delete()
        self.assertEqual(self.act(self.leader, "submit").status_code, 400)

    def test_the_leader_edits_a_draft_but_not_a_submitted_lib(self):
        url = f"/api/budget/line-items/{self.item.id}/"
        leader = self.client_for(self.leader)
        self.assertEqual(leader.patch(url, {"justification": "Field visits"}, format="json").status_code, 200)
        new_row = {"budget": self.budget.id, "category": "mooe", "description": "Travel", "amount": "10"}
        for status in ("submitted", "crc_processing", "for_checking", "endorsed", "certifying", "certified"):
            self.move_to(status)
            self.assertEqual(leader.patch(url, {"justification": "X"}, format="json").status_code, 400, status)
            self.assertEqual(leader.post("/api/budget/line-items/", new_row, format="json").status_code, 400, status)
            self.assertEqual(leader.delete(url).status_code, 400, status)

    def test_only_the_project_leader_encodes(self):
        # Client Q9 (2026-10-21): procurement and program leaders no longer encode LIBs.
        row = {"budget": self.budget.id, "category": "mooe", "description": "Travel", "amount": "10"}
        for code in ("crc_chair", "finance_budget"):
            self.assertEqual(self.client_for(self.make_user(code)).post("/api/budget/line-items/", row, format="json").status_code, 403, code)

    def test_hold_needs_remarks(self):
        self.act(self.leader, "submit")
        self.assertEqual(self.act(self.crc, "hold").status_code, 400)
        self.assertEqual(self.status(), "submitted")

    def test_crc_chair_holds_from_its_review_states(self):
        for status in ("submitted", "crc_processing", "for_checking"):
            self.move_to(status)
            response = self.act(self.crc, "hold", remarks="Fix travel")
            self.assertEqual(response.status_code, 200, status)
            self.assertEqual((self.status(), response.data["hold_level"]), ("returned", "crc"), status)
        self.assertEqual(response.data["reviews"][-1]["action"], "held_crc")

    def test_budget_officer_holds_from_ready_and_in_progress(self):
        for status in ("endorsed", "certifying"):
            self.move_to(status)
            response = self.act(self.officer, "hold", remarks="Wrong unit cost")
            self.assertEqual(response.status_code, 200, status)
            self.assertEqual((self.status(), response.data["hold_level"]), ("returned", "budget"), status)

    def test_hold_belongs_to_the_level_holding_the_lib(self):
        self.move_to("submitted")
        self.assertEqual(self.act(self.officer, "hold", remarks="x").status_code, 403)
        self.move_to("endorsed")
        self.assertEqual(self.act(self.crc, "hold", remarks="x").status_code, 403)
        for status in ("draft", "certified", "returned"):
            self.move_to(status)
            self.assertEqual(self.act(self.crc, "hold", remarks="x").status_code, 400, status)

    def test_the_leader_edits_an_on_hold_lib_and_resubmits_to_the_crc_chair(self):
        self.act(self.leader, "submit")
        self.move_to("endorsed")
        self.act(self.officer, "hold", remarks="Fix travel")
        edit = self.client_for(self.leader).patch(f"/api/budget/line-items/{self.item.id}/", {"justification": "Two trips"}, format="json")
        self.assertEqual(edit.status_code, 200, edit.data)

        response = self.act(self.leader, "resubmit", remarks="Fixed")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.status(), "submitted")  # client Q7: back to Awaiting CRC Chair
        self.assertIsNone(response.data["hold_level"])
        self.assertEqual([(r["action"], r["remarks"]) for r in response.data["reviews"]],
                         [("submitted", ""), ("held_budget", "Fix travel"), ("resubmitted", "Fixed")])

    def test_only_the_project_leader_resubmits(self):
        self.move_to("returned")
        for user in (self.crc, self.officer, self.make_user("project_leader"), self.make_user("system_admin")):
            self.assertIn(self.act(user, "resubmit").status_code, (403, 404), user.role.code)
        self.assertEqual(self.status(), "returned")

    def test_resubmit_refuses_grand_total_not_equal_to_total_cost(self):
        self.move_to("returned")
        LineItem.objects.filter(pk=self.item.pk).update(amount="900")
        self.assertEqual(self.act(self.leader, "resubmit").status_code, 400)
        self.assertEqual(self.status(), "returned")

    def test_each_submission_keeps_a_snapshot_of_the_line_items(self):
        # Client Q11: what was submitted stays on record even after the leader edits an On Hold LIB.
        self.act(self.leader, "submit")
        self.act(self.crc, "hold", remarks="Fix")
        self.client_for(self.leader).patch(f"/api/budget/line-items/{self.item.id}/", {"justification": "Two trips"}, format="json")
        response = self.act(self.leader, "resubmit")

        submitted, held, resubmitted = response.data["reviews"]
        self.assertEqual(submitted["snapshot"][0]["justification"], "")
        self.assertEqual(resubmitted["snapshot"][0]["justification"], "Two trips")
        self.assertEqual((submitted["snapshot"][0]["amount"], held["snapshot"]), ("1000.00", []))

    def test_old_libs_keep_their_status_and_history_labels(self):
        self.move_to("returned")
        from .models import BudgetReview
        BudgetReview.objects.create(budget=self.budget, action="returned", remarks="Old return", acted_by=self.crc)

        data = self.client_for(self.leader).get(f"/api/budget/budgets/{self.budget.id}/").data

        self.assertEqual((data["status"], data["reviews"][0]["action"]), ("returned", "returned"))

    def test_a_line_item_cannot_move_out_of_a_locked_lib(self):
        # Audit 2026-10-21: PATCH {"budget": <a draft LIB>} only checked the new LIB, so an item could leave a
        # certified one.
        LineItemBudget.objects.filter(pk=self.budget.pk).update(status="certified")
        draft = LineItemBudget.objects.create(project=self.project, version_number=2)

        response = self.client_for(self.leader).patch(f"/api/budget/line-items/{self.item.id}/", {"budget": draft.id}, format="json")

        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.budget_id, self.budget.id)

    def test_a_line_item_stays_in_its_own_lib_even_while_draft(self):
        other = LineItemBudget.objects.create(project=self.project, version_number=2)

        response = self.client_for(self.leader).patch(f"/api/budget/line-items/{self.item.id}/", {"budget": other.id}, format="json")

        self.assertIn("budget", response.data)
        self.item.refresh_from_db()
        self.assertEqual(self.item.budget_id, self.budget.id)
