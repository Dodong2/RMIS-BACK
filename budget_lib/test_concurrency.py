"""Client 2026-10-18 endorsement chain under real concurrent requests (config/concurrency.py)."""
from decimal import Decimal

from accounts.testing import ConcurrencyTestCase
from research_projects.models import Project

from .models import BudgetReview, LineItem, LineItemBudget


class EndorsementHappensOnceTests(ConcurrencyTestCase):
    def test_two_crc_chairs_endorsing_at_once_endorse_once(self):
        leader = self.make_user("project_leader")
        project = Project.objects.create(title="P", project_code="P-1", funding_type="core_funded", lead=leader,
                                         total_cost=Decimal("500"))
        budget = LineItemBudget.objects.create(project=project, version_number=1)
        LineItem.objects.create(budget=budget, category="mooe", description="Travel", amount=Decimal("500"))
        self.widen("budget_lib.views.total_cost_problem")

        def endorse(user):
            client = self.client_for(user)
            return lambda: client.post(f"/api/budget/budgets/{budget.id}/endorse/", {}, format="json")

        first, second = self.run_concurrently(endorse(self.make_user("crc_chair")), endorse(self.make_user("crc_chair")))

        self.assertEqual(sorted([first.status_code, second.status_code]), [200, 400])
        self.assertEqual(BudgetReview.objects.filter(budget=budget, action="endorsed").count(), 1)
