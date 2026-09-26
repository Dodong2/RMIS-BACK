"""Calls every /api/ route with every HTTP method it accepts, as several roles, on a small seeded dataset, and fails
on any 5xx. Catches crashes (bad imports, broken querysets, serializer errors) anywhere before deploying."""
import re

from django.urls import URLPattern, URLResolver, get_resolver

from accounts.testing import RMISTestCase
from budget_lib.models import LineItem, LineItemBudget
from research_projects.models import Program, Project, Study, WorkPlanMilestone

SWEEP_ROLES = ["system_admin", "riuh", "project_leader", "project_staff", "finance_budget"]
METHODS = ["get", "post", "put", "patch", "delete"]


def api_routes(patterns=None, prefix=""):
    """Every route under /api/ as a path template like "/api/projects/<int:pk>/"."""
    for entry in patterns if patterns is not None else get_resolver().url_patterns:
        route = (prefix + str(entry.pattern)).replace("^", "").replace("?$", "").replace("$", "")
        if isinstance(entry, URLResolver):
            yield from api_routes(entry.url_patterns, route)
        elif isinstance(entry, URLPattern) and route.startswith("api/"):
            yield "/" + route, entry.callback


def allowed_methods(callback):
    view_class = getattr(callback, "view_class", None) or getattr(callback, "cls", None)
    if view_class is None:
        return ["get"]
    return [m for m in METHODS if hasattr(view_class, m)]


class ApiSweepTests(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.users = {code: self.make_user(code) for code in SWEEP_ROLES}
        leader = self.users["project_leader"]
        program = Program.objects.create(title="Program", funding_type="core_funded", lead=self.make_user("program_leader"))
        self.project = Project.objects.create(
            title="Project", project_code="SWEEP-1", funding_type="core_funded", lead=leader, program=program,
            sdgs=[4], sectors=["education"],
        )
        Study.objects.create(project=self.project, title="Study", lead=self.make_user("study_leader"))
        WorkPlanMilestone.objects.create(project=self.project, title="Milestone", target_date="2026-12-31")
        budget = LineItemBudget.objects.create(project=self.project, version_number=1)
        LineItem.objects.create(budget=budget, category="mooe", description="Travel", amount=1000)

    def url_for(self, template):
        # Fill every <converter:name> with the seeded project's id; unrelated ids simply 404, which is fine.
        return re.sub(r"<(?:\w+:)?\w+>", str(self.project.pk), template)

    def test_no_route_returns_a_server_error_for_any_role(self):
        failures = []
        routes = list(api_routes())
        self.assertGreater(len(routes), 100)
        for code, user in self.users.items():
            client = self.client_for(user)
            for template, callback in routes:
                url = self.url_for(template)
                for method in allowed_methods(callback):
                    response = getattr(client, method)(url, {}, format="json")
                    if response.status_code >= 500:
                        failures.append(f"{code} {method.upper()} {url} -> {response.status_code}")
        self.assertEqual(failures, [])

    def test_every_route_requires_login_except_the_public_auth_ones(self):
        public = {
            "/api/auth/register/", "/api/auth/google/request/", "/api/auth/google/exchange/", "/api/roles/",
            "/api/auth/login/", "/api/auth/logout/", "/api/auth/token/verify/", "/api/auth/token/refresh/",
        }
        open_routes = []
        for template, callback in api_routes():
            url = self.url_for(template)
            if template in public:
                continue
            for method in allowed_methods(callback):
                response = getattr(self.client, method)(url, {}, format="json")
                if response.status_code not in (401, 403, 405):
                    open_routes.append(f"{method.upper()} {url} -> {response.status_code}")
        self.assertEqual(open_routes, [])
