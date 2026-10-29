"""2026-10-22 real-time: every LIB review step (and a new LIB) sends one "budget.lib.updated" signal to the budget.*
roles and the project lead, so the next level sees the LIB without a refresh. Ids only, no status (client Q10)."""
from datetime import date
from decimal import Decimal

from accounts.testing import RMISTestCase
from realtime.notify import to_role, to_user
from research_projects.models import Project

from .models import LineItem, LineItemBudget
from .tests import add_registration_rows, attach_approval_documents

BUDGET_ROLES = {"system_admin", "crc_chair", "finance_budget"}


class LibSignalTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.notify = self._patch("budget_lib.views.notify")
        self.leader = self.make_user("project_leader")
        self.crc = self.make_user("crc_chair")
        self.officer = self.make_user("finance_budget")
        self.project = Project.objects.create(
            title="P", project_code="P-1", funding_type="core_funded", lead=self.leader, campus="San Pablo",
            total_cost="1000", start_date=date(2026, 1, 1), target_end_date=date(2026, 12, 31),
        )
        self.budget = LineItemBudget.objects.create(project=self.project, version_number=1)
        LineItem.objects.create(budget=self.budget, category="mooe", description="Travel", amount=Decimal("1000"))
        attach_approval_documents(self.project, self.leader)
        add_registration_rows(self.project)

    def act(self, user, step, **data):
        return self.client_for(user).post(f"/api/budget/budgets/{self.budget.id}/{step}/", data, format="json")

    def assert_signal(self, budget_id=None):
        self.assertEqual(self.notify.call_count, 1)
        (groups, event_type), data = self.notify.call_args
        self.notify.reset_mock()
        self.assertEqual(event_type, "budget.lib.updated")
        self.assertEqual(data, {"id": budget_id or self.budget.id, "project": self.project.id})
        self.assertEqual(set(groups), {*map(to_role, BUDGET_ROLES), to_user(self.leader.pk)})

    def test_every_step_signals_once(self):
        steps = [(self.leader, "submit"), (self.crc, "start-review"), (self.crc, "hold"), (self.leader, "resubmit"),
                 (self.crc, "start-review"), (self.crc, "for-checking"), (self.crc, "ready"),
                 (self.officer, "start-certification"), (self.officer, "certify")]
        for user, step in steps:
            with self.subTest(step=step):
                response = self.act(user, step, remarks="Fix travel." if step == "hold" else "")
                self.assertEqual(response.status_code, 200, (step, response.data))
                self.assert_signal()

    def test_refused_step_sends_nothing(self):
        self.assertEqual(self.act(self.crc, "start-review").status_code, 404)  # still Draft, hidden from the CRC Chair (D2)
        self.assertEqual(self.act(self.crc, "submit").status_code, 404)  # not the leader; the Draft is hidden from them (D2)
        self.act(self.leader, "submit")
        self.notify.reset_mock()
        self.assertEqual(self.act(self.crc, "hold").status_code, 400)  # remarks required
        self.notify.assert_not_called()

    def test_new_lib_signals(self):
        response = self.client_for(self.leader).post("/api/budget/budgets/", {"project": self.project.id}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assert_signal(response.data["id"])
