"""Client Task 86-A (2026-11-18, Figma BF-01..04): ARIMA horizon 1-24 months; Run = preview, Save Forecast saves.
Risk, DSS and the forecasting dashboard read saved runs only."""
from unittest import mock

from dashboard.services import compute_forecasting_dashboard
from decision_support.services import _overrun_risk_inverse
from risk_indicators.services import _forecast_overrun

from . import services
from .models import ForecastRun
from .tests import URL, ForecastTestCase


def flat_fit(values, steps):
    return [100.0] * steps, [[0, 200]] * steps


class HorizonAndSaveTests(ForecastTestCase):
    def setUp(self):
        super().setUp()
        self.disburse()
        self.client = self.client_for(self.leader)

    def trigger(self, **extra):
        with mock.patch.object(services, "_fit_and_forecast", side_effect=flat_fit):
            return self.client.post(URL + "trigger/", {"project": self.project.pk, **extra}, format="json")

    def test_horizon_sets_the_number_of_forecast_months_and_the_projection(self):
        for horizon in (1, 24):
            data = self.trigger(horizon=horizon).data
            self.assertEqual(len(data["forecasts"]), horizon)
            self.assertEqual(float(data["projected_total_at_horizon"]), 6000 + 100 * horizon)

    def test_default_horizon_stays_three_months(self):
        self.assertEqual(len(self.trigger().data["forecasts"]), 3)

    def test_horizon_outside_1_to_24_is_rejected(self):
        for bad in (0, 25, "x"):
            self.assertEqual(self.trigger(horizon=bad).status_code, 400, bad)
        self.assertEqual(ForecastRun.objects.count(), 0)

    def test_a_run_is_a_preview_until_saved(self):
        run_id = self.trigger(horizon=6).data["id"]
        self.assertFalse(ForecastRun.objects.get(pk=run_id).is_saved)
        self.assertEqual(self.client.get(URL).data, [])
        self.assertEqual(self.client.get(f"{URL}{run_id}/").status_code, 200)

        response = self.client.post(f"{URL}{run_id}/save/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_saved"])
        self.assertEqual([r["id"] for r in self.client.get(URL).data], [run_id])

    def test_a_new_run_replaces_my_unsaved_preview_but_keeps_saved_runs(self):
        saved = self.trigger().data["id"]
        self.client.post(f"{URL}{saved}/save/")
        first = self.trigger().data["id"]
        second = self.trigger().data["id"]
        self.assertFalse(ForecastRun.objects.filter(pk=first).exists())
        self.assertEqual(set(ForecastRun.objects.values_list("pk", flat=True)), {saved, second})

    def test_only_the_person_who_ran_it_can_save_a_preview(self):
        run_id = self.trigger().data["id"]
        self.assertEqual(self.client_for(self.finance).post(f"{URL}{run_id}/save/").status_code, 404)
        self.assertEqual(self.client_for(self.make_user("project_staff")).post(f"{URL}{run_id}/save/").status_code, 403)


class SavedRunsOnlyConsumerTests(ForecastTestCase):
    """F5: an unsaved preview must not change the risk flag, the DSS criterion or the forecasting dashboard."""

    def setUp(self):
        super().setUp()
        self.saved = ForecastRun.objects.create(project=self.project, run_by=self.leader, status="success",
                                                is_overrun_risk=False)
        ForecastRun.objects.create(project=self.project, run_by=self.leader, status="success", is_overrun_risk=True,
                                   is_saved=False)

    def test_risk_flag_reads_the_latest_saved_run(self):
        self.assertFalse(_forecast_overrun(self.project)["is_overrun_risk"])

    def test_dss_criterion_reads_the_latest_saved_run(self):
        self.assertEqual(_overrun_risk_inverse(self.project), 1.0)

    def test_forecasting_dashboard_reads_saved_runs(self):
        data = compute_forecasting_dashboard(user=self.make_user("system_admin"))
        self.assertEqual((data["overrun_risk_count"], [r["run"] for r in data["projects"]]), (0, [self.saved.pk]))
