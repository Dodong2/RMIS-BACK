"""LIB endorsement chain (client 2026-10-18): CRC Chair endorses, then the Budget Officer certifies. Either one can
return the LIB to the Project Leader, who edits it and resubmits. Every step is kept in the review history."""
from datetime import date
from decimal import Decimal

from accounts.testing import RMISTestCase
from research_projects.models import Project

from .models import LineItem, LineItemBudget


class EndorsementTests(RMISTestCase):
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

    def test_crc_chair_endorses_then_budget_officer_certifies(self):
        self.assertEqual(self.act(self.crc, "endorse").status_code, 200)
        self.assertEqual(self.status(), "endorsed")
        self.assertEqual(self.budget.endorsed_by, self.crc)
        response = self.act(self.officer, "certify")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.status(), "certified")
        self.assertEqual([r["action"] for r in response.data["reviews"]], ["endorsed", "certified"])
        self.assertEqual(response.data["endorsed_by_name"], self.crc.display_name)

    def test_budget_officer_cannot_certify_before_endorsement(self):
        self.assertEqual(self.act(self.officer, "certify").status_code, 400)
        self.assertEqual(self.status(), "draft")

    def test_only_crc_chair_endorses(self):
        for user in (self.officer, self.make_user("drd"), self.make_user("riuh"), self.leader):
            self.assertEqual(self.act(user, "endorse").status_code, 403, user.role.code)
        self.assertEqual(self.status(), "draft")

    def test_crc_chair_outside_campus_cannot_endorse(self):
        other = self.make_user("crc_chair", scope={"campus": "Los Baños"})
        self.assertEqual(self.act(other, "endorse").status_code, 404)
        self.assertEqual(self.status(), "draft")

    def test_endorse_refuses_grand_total_not_equal_to_total_cost(self):
        LineItem.objects.filter(pk=self.item.pk).update(amount="900")
        response = self.act(self.crc, "endorse")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Total Project/Study Cost", str(response.data))
        self.assertEqual(self.status(), "draft")

    def test_endorse_refuses_empty_lib(self):
        self.item.delete()
        self.assertEqual(self.act(self.crc, "endorse").status_code, 400)

    def test_return_needs_remarks(self):
        self.assertEqual(self.act(self.crc, "return").status_code, 400)
        self.assertEqual(self.status(), "draft")

    def test_crc_chair_returns_and_leader_resubmits(self):
        self.assertEqual(self.act(self.crc, "return", remarks="Fix travel").status_code, 200)
        self.assertEqual(self.status(), "returned")
        edit = self.client_for(self.leader).patch(f"/api/budget/line-items/{self.item.id}/", {"description": "Travel (fixed)"}, format="json")
        self.assertEqual(edit.status_code, 200, edit.data)
        response = self.act(self.leader, "resubmit", remarks="Fixed")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.status(), "draft")
        self.assertEqual(
            [(r["action"], r["remarks"]) for r in response.data["reviews"]],
            [("returned", "Fix travel"), ("resubmitted", "Fixed")],
        )

    def test_budget_officer_returns_an_endorsed_lib(self):
        self.act(self.crc, "endorse")
        self.assertEqual(self.act(self.crc, "return", remarks="Too late").status_code, 403)
        self.assertEqual(self.act(self.officer, "return", remarks="Wrong unit cost").status_code, 200)
        self.assertEqual(self.status(), "returned")

    def test_budget_officer_cannot_return_a_draft(self):
        self.assertEqual(self.act(self.officer, "return", remarks="x").status_code, 403)

    def test_only_the_project_leader_resubmits(self):
        self.act(self.crc, "return", remarks="Fix")
        for user in (self.crc, self.officer, self.make_user("project_leader"), self.make_user("system_admin")):
            self.assertIn(self.act(user, "resubmit").status_code, (403, 404))
        self.assertEqual(self.status(), "returned")

    def test_resubmit_refuses_grand_total_not_equal_to_total_cost(self):
        self.act(self.crc, "return", remarks="Fix")
        LineItem.objects.filter(pk=self.item.pk).update(amount="900")
        self.assertEqual(self.act(self.leader, "resubmit").status_code, 400)
        self.assertEqual(self.status(), "returned")

    def test_endorsed_and_certified_libs_are_locked(self):
        url = f"/api/budget/line-items/{self.item.id}/"
        leader = self.client_for(self.leader)
        self.act(self.crc, "endorse")
        self.assertEqual(leader.patch(url, {"description": "X"}, format="json").status_code, 400)
        self.assertEqual(leader.delete(url).status_code, 400)
        new_row = {"budget": self.budget.id, "category": "mooe", "description": "Snacks", "amount": "10"}
        self.assertEqual(leader.post("/api/budget/line-items/", new_row, format="json").status_code, 400)
        self.act(self.officer, "certify")
        self.assertEqual(leader.patch(url, {"description": "X"}, format="json").status_code, 400)

    def test_wrong_state_actions_are_refused(self):
        self.assertEqual(self.act(self.leader, "resubmit").status_code, 400)
        self.act(self.crc, "endorse")
        self.assertEqual(self.act(self.crc, "endorse").status_code, 400)
        self.act(self.officer, "certify")
        self.assertEqual(self.act(self.officer, "certify").status_code, 400)
        self.assertEqual(self.act(self.officer, "return", remarks="x").status_code, 400)
