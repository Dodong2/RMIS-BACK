"""Task 27 (2026-10-30): Budget Forecast for the Project Leader, row scope, unpaid commitments in the overrun flag."""
import datetime
from unittest import mock

from accounts.permissions import role_can
from accounts.testing import RMISTestCase
from budget_lib.models import LineItem, LineItemBudget
from financial_monitoring.models import Disbursement, ProcurementRequest
from research_projects.models import Project

from . import services
from .models import ForecastRun

URL = "/api/forecasting/runs/"


class ForecastTestCase(RMISTestCase):
    def setUp(self):
        super().setUp()
        self.leader = self.make_user("project_leader", campus="Siniloan")
        self.finance = self.make_user("finance_budget", campus="Siniloan")
        self.project = self.make_project("NTP-1", self.leader, "Siniloan")
        self.item = self.make_item(self.project, amount=10000)

    def make_project(self, code, lead, campus="Siniloan", funding_type="institutional"):
        return Project.objects.create(title=code, project_code=code, funding_type=funding_type, lead=lead, campus=campus)

    def make_item(self, project, amount):
        budget = LineItemBudget.objects.create(project=project, version_number=1, status="certified")
        return LineItem.objects.create(budget=budget, category="mooe", description="Supplies", amount=amount)

    def disburse(self, months=6, amount=1000, **fields):
        return [
            Disbursement.objects.create(line_item=self.item, amount=amount, disbursed_on=datetime.date(2026, m, 1),
                                        recorded_by=self.finance, **fields)
            for m in range(1, months + 1)
        ]

    def request(self, amount, status="submitted"):
        return ProcurementRequest.objects.create(line_item=self.item, description="Item", amount=amount, project_year=1,
                                                 quarter=1, status=status, requested_by=self.leader)

    def run_flat(self):
        """Actual 6,000 + forecast 3 x 100 = 6,300, with the ARIMA fit stubbed so the figures are exact."""
        self.disburse()
        fit = ([100.0, 100.0, 100.0], [[0, 200]] * 3)
        with mock.patch.object(services, "_fit_and_forecast", return_value=fit):
            return services.run_forecast(self.project, self.leader)


class OverrunTests(ForecastTestCase):
    def test_without_commitments_the_figures_stay_actual_plus_forecast(self):
        run = self.run_flat()
        self.assertEqual((run.status, run.actual_to_date, float(run.projected_total_at_horizon)), ("success", 6000, 6300.0))
        self.assertFalse(run.is_overrun_risk)

    def test_unpaid_commitments_can_trip_the_flag_without_changing_the_projection(self):
        self.request(3701)  # 6,300 + 3,701 = 10,001 > 10,000
        run = self.run_flat()
        self.assertTrue(run.is_overrun_risk)
        self.assertEqual(float(run.projected_total_at_horizon), 6300.0)

    def test_exactly_the_approved_budget_is_not_an_overrun(self):
        self.request(3700)
        self.assertFalse(self.run_flat().is_overrun_risk)

    def test_paid_and_cancelled_requests_are_not_commitments(self):
        paid = self.request(5000, "completed")
        Disbursement.objects.create(line_item=self.item, amount=5000, disbursed_on=datetime.date(2026, 7, 1),
                                    recorded_by=self.finance, procurement_request=paid)
        self.request(9000, "cancelled")
        self.request(250, "returned")
        self.assertEqual(services.unpaid_commitments(self.project), 250)

    def test_a_paid_request_counts_once_in_the_flag(self):
        paid = self.request(3000, "completed")
        Disbursement.objects.create(line_item=self.item, amount=3000, disbursed_on=datetime.date(2026, 7, 1),
                                    recorded_by=self.finance, procurement_request=paid)
        run = self.run_flat()  # actual 9,000 + forecast 300 = 9,300; counted twice it would be 12,300
        self.assertEqual(float(run.projected_total_at_horizon), 9300.0)
        self.assertFalse(run.is_overrun_risk)

    def test_a_real_arima_fit_still_runs_on_disbursements(self):
        for month, amount in enumerate([1000, 1200, 900, 1500, 1100, 1300, 1400, 1000, 1600], start=1):
            Disbursement.objects.create(line_item=self.item, amount=amount, disbursed_on=datetime.date(2026, month, 1),
                                        recorded_by=self.finance)
        run = services.run_forecast(self.project, self.leader)
        self.assertEqual((run.status, run.months_of_history, run.forecasts.count()), ("success", 9, 3))
        self.assertIsNotNone(run.mae)

    def test_short_history_is_still_insufficient_data(self):
        self.disburse(months=5)
        run = services.run_forecast(self.project, self.leader)
        self.assertEqual((run.status, run.is_overrun_risk), ("insufficient_data", False))


class AccessTests(ForecastTestCase):
    def setUp(self):
        super().setUp()
        self.other_leader = self.make_user("project_leader", campus="Sta. Cruz")
        self.other = self.make_project("NTP-2", self.other_leader, "Sta. Cruz")
        self.make_item(self.other, amount=5000)
        self.mine = ForecastRun.objects.create(project=self.project, run_by=self.leader, status="insufficient_data")
        self.theirs = ForecastRun.objects.create(project=self.other, run_by=self.other_leader, status="insufficient_data")

    def ids(self, user):
        return {row["id"] for row in self.client_for(user).get(URL).data}

    def test_permission_roles(self):
        # Client Task 66 (2026-11-16): Project Leader, RIUH, CRC/CRD, Finance (+ system_admin); not VP for REI.
        for code in ("system_admin", "project_leader", "riuh", "crc_chair", "finance_budget"):
            self.assertTrue(role_can(self.make_user(code), "forecasting.run"), code)
        for code in ("vprei", "university_admin", "procurement_officer_lib", "project_staff"):
            self.assertFalse(role_can(self.make_user(code), "forecasting.run"), code)

    def test_leader_runs_their_own_project(self):
        response = self.client_for(self.leader).post(URL + "trigger/", {"project": self.project.pk})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["unpaid_commitments"], "0")

    def test_leader_cannot_run_another_leaders_project(self):
        self.assertEqual(self.client_for(self.leader).post(URL + "trigger/", {"project": self.other.pk}).status_code, 404)

    def test_finance_of_another_campus_cannot_run(self):
        self.assertEqual(self.client_for(self.finance).post(URL + "trigger/", {"project": self.other.pk}).status_code, 404)

    def test_staff_cannot_run(self):
        self.assertEqual(self.client_for(self.make_user("project_staff")).post(URL + "trigger/", {"project": self.project.pk}).status_code, 403)

    def test_an_active_core_funded_project_can_be_run(self):
        core = self.make_project("NTP-3", self.leader, funding_type="core_funded")
        self.make_item(core, amount=1000)
        self.assertEqual(self.client_for(self.leader).post(URL + "trigger/", {"project": core.pk}).status_code, 201)

    def test_list_and_detail_follow_the_row_scope(self):
        self.assertEqual(self.ids(self.leader), {self.mine.pk})
        self.assertEqual(self.ids(self.finance), {self.mine.pk})
        self.assertEqual(self.ids(self.make_user("system_admin")), {self.mine.pk, self.theirs.pk})
        client = self.client_for(self.leader)
        self.assertEqual(client.get(f"{URL}{self.mine.pk}/").status_code, 200)
        self.assertEqual(client.get(f"{URL}{self.theirs.pk}/").status_code, 404)

    def test_filtering_by_another_project_returns_nothing(self):
        rows = self.client_for(self.leader).get(URL, {"project": self.other.pk}).data
        self.assertEqual(len(rows), 0)

    def test_serializer_shows_todays_unpaid_commitments(self):
        self.request(250)
        row = self.client_for(self.leader).get(f"{URL}{self.mine.pk}/").data
        self.assertEqual(float(row["unpaid_commitments"]), 250.0)


class ActiveProjectsAndRolesTests(ForecastTestCase):
    """Client Task 66 (2026-11-16): only Active projects (current LIB certified), the four roles, campus scope."""

    PROJECTS = "/api/forecasting/projects/"

    def setUp(self):
        super().setUp()
        self.pending = self.make_project("NTP-P", self.leader)
        LineItemBudget.objects.create(project=self.pending, version_number=1, status="endorsed")
        self.no_lib = self.make_project("NTP-N", self.leader)
        self.elsewhere = self.make_project("NTP-E", self.make_user("project_leader", campus="Sta. Cruz"), "Sta. Cruz")
        self.make_item(self.elsewhere, amount=1000)
        self.old_run = ForecastRun.objects.create(project=self.pending, run_by=self.leader, status="insufficient_data")

    def codes(self, user):
        response = self.client_for(user).get(self.PROJECTS)
        self.assertEqual(response.status_code, 200)
        return {row["project_code"] for row in response.data}

    def test_dropdown_lists_only_active_projects_in_scope_for_each_role(self):
        self.assertEqual(self.codes(self.leader), {"NTP-1"})
        for code in ("finance_budget", "riuh", "crc_chair"):
            self.assertEqual(self.codes(self.make_user(code, campus="Siniloan")), {"NTP-1"}, code)
        self.assertEqual(self.codes(self.make_user("system_admin")), {"NTP-1", "NTP-E"})
        row = self.client_for(self.leader).get(self.PROJECTS).data[0]
        self.assertEqual(set(row), {"id", "project_code", "title"})

    def test_a_non_active_project_cannot_be_run_or_read_by_id(self):
        client = self.client_for(self.make_user("system_admin"))
        for project in (self.pending, self.no_lib):
            self.assertEqual(client.post(URL + "trigger/", {"project": project.pk}).status_code, 404)
        self.assertEqual(client.get(URL, {"project": self.pending.pk}).data, [])
        self.assertEqual(client.get(f"{URL}{self.old_run.pk}/").status_code, 404)

    def test_a_returned_or_superseded_lib_is_not_active(self):
        LineItemBudget.objects.filter(project=self.project).update(is_current=False)
        LineItemBudget.objects.create(project=self.project, version_number=2, status="returned")
        self.assertEqual(self.codes(self.leader), set())

    def test_riuh_and_crc_can_run_their_campus_project_only(self):
        for code in ("riuh", "crc_chair"):
            client = self.client_for(self.make_user(code, campus="Siniloan"))
            with mock.patch.object(services, "_fit_and_forecast", return_value=([1.0] * 3, [[0, 2]] * 3)):
                self.assertEqual(client.post(URL + "trigger/", {"project": self.project.pk}).status_code, 201, code)
            self.assertEqual(client.post(URL + "trigger/", {"project": self.elsewhere.pk}).status_code, 404, code)

    def test_other_roles_get_403_everywhere(self):
        for code in ("vprei", "university_admin", "procurement_officer_lib", "project_staff"):
            client = self.client_for(self.make_user(code, campus="Siniloan"))
            for response in (
                client.get(self.PROJECTS),
                client.get(URL),
                client.get(f"{URL}{self.old_run.pk}/"),
                client.post(URL + "trigger/", {"project": self.project.pk}),
            ):
                self.assertEqual(response.status_code, 403, code)
