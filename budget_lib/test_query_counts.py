"""Task 68-A (2026-11-17): the list endpoints the frontend refetches after every procurement/LIB action ran one query
per row (N+1), ~75 ms each against Supabase (budgets list: 260 queries, 20 s). These tests lock in that the query count
no longer grows with the number of rows, and that the prefetched list gives the same values as the plain detail read."""
from django.db import connection
from django.test.utils import CaptureQueriesContext

from accounts.testing import RMISTestCase
from budget_lib.models import BudgetReview, LineItem, LineItemBudget, LineItemEdit
from financial_monitoring.models import ProcurementRequest
from forecasting.models import ForecastRun, MonthlyForecast
from research_projects.models import Project

LISTS = ["/api/financial/procurement-requests/", "/api/budget/budgets/", "/api/projects/",
         "/api/budget/line-items/?is_app_flagged=true"]


class ListQueryCountTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.make_user("system_admin")
        self.finance = self.make_user("finance_budget")
        self.officer = self.make_user("procurement_officer_lib")
        self.client = self.client_for(self.admin)
        self.made = 0

    def add_project(self, lib_status="certified", hold=None):
        self.made += 1
        leader = self.make_user("project_leader", first_name=f"Lead{self.made}")
        project = Project.objects.create(title=f"P{self.made}", project_code=f"P-{self.made}", funding_type="core_funded",
                                         lead=leader, status="active")
        budget = LineItemBudget.objects.create(project=project, version_number=1, status=lib_status,
                                               endorsed_by=self.finance, certified_by=self.finance)
        for n in range(2):
            item = LineItem.objects.create(budget=budget, category="mooe", description=f"Item {n}", amount=60000 + n)
            LineItemEdit.objects.create(line_item=item, budget=budget, changes={}, reason="fix", edited_by=self.finance)
            ProcurementRequest.objects.create(line_item=item, description="Buy", amount=100, project_year=1,
                                              requested_by=leader, received_by=self.officer, status="under_review")
        BudgetReview.objects.create(budget=budget, action=hold or "endorsed", acted_by=self.finance)
        run = ForecastRun.objects.create(project=project, run_by=self.admin, status="success")
        MonthlyForecast.objects.create(forecast_run=run, period="2026-01-01", predicted_amount=1, lower_bound=0, upper_bound=2)
        return project, budget

    def count(self, url):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return len(queries)

    def test_list_queries_do_not_grow_with_rows(self):
        first, _ = self.add_project()
        urls = [*LISTS, f"/api/forecasting/runs/?project={first.pk}"]
        one = {url: self.count(url) for url in urls}
        for _ in range(3):
            self.add_project()
        self.add_project(lib_status="returned", hold="held_budget")
        four = {url: self.count(url) for url in urls}
        self.assertEqual(one, four)

    def test_prefetched_list_matches_the_detail_read(self):
        self.add_project()
        held, held_budget = self.add_project(lib_status="returned", hold="held_budget")
        BudgetReview.objects.create(budget=held_budget, action="comment", acted_by=self.finance)  # not a hold: skipped
        projects = {p["id"]: p for p in self.client.get("/api/projects/").data}
        budgets = {b["id"]: b for b in self.client.get("/api/budget/budgets/").data}
        for pk, row in projects.items():
            detail = self.client.get(f"/api/projects/{pk}/").data
            self.assertEqual((row["review_status"], row["review_status_label"]), (detail["review_status"], detail["review_status_label"]))
        for pk, row in budgets.items():
            detail = self.client.get(f"/api/budget/budgets/{pk}/").data
            for field in ("total_amount", "hold_level", "line_items", "reviews", "endorsed_by_name", "certified_by_name"):
                self.assertEqual(row[field], detail[field], field)
        self.assertEqual(projects[held.pk]["review_status"], "returned_budget")
        self.assertEqual(budgets[held_budget.pk]["hold_level"], "budget")
        self.assertEqual(budgets[held_budget.pk]["total_amount"], 120001)

    def test_project_without_lib_is_still_draft(self):
        leader = self.make_user("project_leader")
        project = Project.objects.create(title="No LIB", project_code="NL-1", funding_type="core_funded", lead=leader)
        row = next(p for p in self.client.get("/api/projects/").data if p["id"] == project.pk)
        self.assertEqual(row["review_status"], "draft")
