"""Task 76-A: standard scores are absolute 0-100 (no min-max), and each run keeps the weights/formulas it used."""
import importlib
from unittest.mock import patch

from django.apps import apps

from accounts.testing import RMISTestCase
from decision_support import services
from decision_support.models import AHPMatrixRun, DecisionCriterion, FundingRecommendationRun
from research_projects.models import Project


class StandardScoreTests(RMISTestCase):
    def test_fixed_range_metrics_scale_to_0_100(self):
        cases = {
            "budget_utilization_pct": (35.7, 35.7),
            "compliance_score": (0.5, 50.0),
            "monitoring_health": (0.5, 50.0),
            "renewal_eligible": (1.0, 100.0),
            "overrun_risk_inverse": (0.0, 0.0),
            "risk_score_inverse": (20, 80.0),
        }
        for key, (raw, expected) in cases.items():
            self.assertAlmostEqual(services.standard_scores(key, {1: raw})[1], expected, msg=key)

    def test_values_are_clamped(self):
        self.assertEqual(services.standard_scores("budget_utilization_pct", {1: 130.0, 2: -5})[1], 100.0)
        self.assertEqual(services.standard_scores("budget_utilization_pct", {1: 130.0, 2: -5})[2], 0.0)

    def test_all_tied_zero_utilization_scores_zero_not_100(self):
        self.assertEqual(services.standard_scores("budget_utilization_pct", {1: 0.0, 2: 0.0}), {1: 0.0, 2: 0.0})

    def test_output_count_is_scored_against_the_highest_count(self):
        self.assertEqual(services.standard_scores("output_score", {1: 4, 2: 1, 3: 0}), {1: 100.0, 2: 25.0, 3: 0.0})
        self.assertEqual(services.standard_scores("output_score", {1: 0, 2: 0}), {1: 0.0, 2: 0.0})


class RunTests(RMISTestCase):
    """Raw metric values are patched in so each scenario's numbers are exact (sample data, labelled)."""

    def setUp(self):
        self.admin = self.make_user("system_admin")
        self.budget = DecisionCriterion.objects.create(name="Budget", metric_key="budget_utilization_pct")
        self.compliance = DecisionCriterion.objects.create(name="Compliance", metric_key="compliance_score")
        self.model = AHPMatrixRun.objects.create(
            label="Model", created_by=self.admin, status="finalized", is_consistent=True, consistency_ratio=0.0,
            weights={str(self.budget.id): 0.7, str(self.compliance.id): 0.3},
        )
        self.model.criteria.set([self.budget, self.compliance])
        lead = self.make_user("project_leader")
        self.p1, self.p2, self.p3 = (
            Project.objects.create(title=f"Sample {c}", project_code=f"SAMPLE-{c}", funding_type="core_funded", lead=lead)
            for c in "ABC"
        )

    def run_with(self, raw):
        """raw = {metric_key: {project: value}}"""
        metrics = {k: (lambda p, k=k: raw[k][p]) for k in raw}
        with patch.dict(services.CRITERIA_METRICS, metrics):
            response = self.client_for(self.admin).post(
                "/api/decision-support/recommendation-runs/trigger/",
                {"ahp_run": self.model.id, "project_ids": [p.id for p in raw["budget_utilization_pct"]]},
                format="json",
            )
        self.assertEqual(response.status_code, 201, response.data)
        return {s["project"]: s for s in response.data["scores"]}, response.data

    def test_scenario_no_spending_no_reviews_is_not_100(self):
        # Sample of the shared DB's runs 8-11: 0% utilization, no ethics review (neutral 0.5) for everyone.
        scores, _ = self.run_with({
            "budget_utilization_pct": {self.p1: 0.0, self.p2: 0.0},
            "compliance_score": {self.p1: 0.5, self.p2: 0.5},
        })
        for s in scores.values():
            self.assertAlmostEqual(s["composite_score"], 0.15)  # 0 x 0.7 + 0.5 x 0.3

    def test_scenario_mixed_scores_follow_the_weights(self):
        scores, _ = self.run_with({
            "budget_utilization_pct": {self.p1: 80.0, self.p2: 20.0, self.p3: 50.0},
            "compliance_score": {self.p1: 0.0, self.p2: 1.0, self.p3: 0.5},
        })
        self.assertAlmostEqual(scores[self.p1.id]["composite_score"], 0.56)  # 0.8 x 0.7 + 0 x 0.3
        self.assertAlmostEqual(scores[self.p2.id]["composite_score"], 0.44)  # 0.2 x 0.7 + 1 x 0.3
        self.assertAlmostEqual(scores[self.p3.id]["composite_score"], 0.50)
        self.assertEqual([scores[p.id]["rank"] for p in (self.p1, self.p3, self.p2)], [1, 2, 3])
        self.assertEqual(scores[self.p2.id]["normalized_scores"], {str(self.budget.id): 0.2, str(self.compliance.id): 1.0})

    def test_scenario_changing_weights_changes_the_ranking(self):
        raw = {
            "budget_utilization_pct": {self.p1: 80.0, self.p2: 20.0},
            "compliance_score": {self.p1: 0.0, self.p2: 1.0},
        }
        self.model.weights = {str(self.budget.id): 0.2, str(self.compliance.id): 0.8}
        self.model.save()
        scores, _ = self.run_with(raw)
        self.assertAlmostEqual(scores[self.p1.id]["composite_score"], 0.16)
        self.assertAlmostEqual(scores[self.p2.id]["composite_score"], 0.84)
        self.assertEqual(scores[self.p2.id]["rank"], 1)

    def test_scenario_genuine_100_is_still_possible(self):
        scores, _ = self.run_with({
            "budget_utilization_pct": {self.p1: 100.0, self.p2: 10.0},
            "compliance_score": {self.p1: 1.0, self.p2: 1.0},
        })
        self.assertAlmostEqual(scores[self.p1.id]["composite_score"], 1.0)
        self.assertAlmostEqual(scores[self.p2.id]["composite_score"], 0.37)

    def test_run_keeps_its_weights_after_the_model_changes(self):
        _, data = self.run_with({
            "budget_utilization_pct": {self.p1: 80.0, self.p2: 20.0},
            "compliance_score": {self.p1: 0.0, self.p2: 1.0},
        })
        self.assertEqual(data["method"], "absolute_v2")
        self.assertEqual(data["weights_snapshot"], {str(self.budget.id): 0.7, str(self.compliance.id): 0.3})
        self.assertEqual(data["formulas_snapshot"][str(self.budget.id)], {"metric_key": "budget_utilization_pct", "mode": "standard"})

        self.model.weights = {str(self.budget.id): 0.1, str(self.compliance.id): 0.9}
        self.model.save()
        run = FundingRecommendationRun.objects.get(pk=data["id"])
        self.assertEqual(run.weights_snapshot[str(self.budget.id)], 0.7)
        result = services.sensitivity_analysis(run, self.budget.id, 0.0)
        self.assertEqual(result["old_weight"], 0.7)

    def test_backfill_labels_old_runs_without_touching_scores(self):
        run = FundingRecommendationRun.objects.create(ahp_run=self.model, label="old", created_by=self.admin)
        score = run.scores.create(project=self.p1, raw_scores={}, normalized_scores={"1": 1.0}, composite_score=1.0, rank=1)
        migration = importlib.import_module("decision_support.migrations.0003_run_snapshots_task76")
        migration.mark_old_runs(apps, None)
        run.refresh_from_db()
        score.refresh_from_db()
        self.assertEqual(run.method, "minmax_v1")
        self.assertEqual(run.weights_snapshot, {str(self.budget.id): 0.7, str(self.compliance.id): 0.3})
        self.assertEqual((score.composite_score, score.normalized_scores), (1.0, {"1": 1.0}))
