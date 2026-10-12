"""2026-10-12 concurrency audit: finalized AHP weights are computed once and never overwritten."""
from accounts.testing import RMISTestCase
from decision_support.models import AHPMatrixRun, DecisionCriterion


class FinalizeOnceTests(RMISTestCase):
    def test_finalized_run_rejects_a_second_finalize_and_new_comparisons(self):
        admin = self.make_user("system_admin")
        a = DecisionCriterion.objects.create(name="Outputs", metric_key="output_score")
        b = DecisionCriterion.objects.create(name="Compliance", metric_key="compliance_score")
        run = AHPMatrixRun.objects.create(label="2026", created_by=admin)
        run.criteria.set([a, b])
        client = self.client_for(admin)
        base = f"/api/decision-support/ahp-runs/{run.id}"
        pair = {"comparisons": [{"criterion_row": a.id, "criterion_col": b.id, "value": 3}]}

        self.assertEqual(client.post(f"{base}/comparisons/", pair, format="json").status_code, 201)
        self.assertEqual(client.post(f"{base}/finalize/").status_code, 200)
        weights = AHPMatrixRun.objects.get().weights
        self.assertEqual(client.post(f"{base}/finalize/").status_code, 400)
        self.assertEqual(client.post(f"{base}/comparisons/", pair, format="json").status_code, 400)
        self.assertEqual(AHPMatrixRun.objects.get().weights, weights)

    def test_a_bad_pair_saves_none_of_the_batch(self):
        admin = self.make_user("system_admin")
        a = DecisionCriterion.objects.create(name="Outputs", metric_key="output_score")
        b = DecisionCriterion.objects.create(name="Compliance", metric_key="compliance_score")
        run = AHPMatrixRun.objects.create(label="2026", created_by=admin)
        run.criteria.set([a, b])
        response = self.client_for(admin).post(f"/api/decision-support/ahp-runs/{run.id}/comparisons/", {"comparisons": [
            {"criterion_row": a.id, "criterion_col": b.id, "value": 3},
            {"criterion_row": a.id, "criterion_col": 99999, "value": 3},
        ]}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(run.comparisons.exists())
