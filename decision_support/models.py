from django.conf import settings
from django.db import models

from research_projects.models import Project

CRITERIA_METRIC_CHOICES = (
    ("output_score", "Research Output Volume (publications + IP + creative works)"),
    ("compliance_score", "Compliance Completeness (ethics review clearance rate)"),
    ("budget_utilization_pct", "Budget Utilization %"),
    ("monitoring_health", "Monitoring/Reporting Health"),
    ("renewal_eligible", "Renewal Eligibility"),
    ("overrun_risk_inverse", "Forecast Overrun-Risk (inverse — no risk scores higher)"),
)


class DecisionCriterion(models.Model):
    """A criterion used in AHP weighting/WSM scoring. metric_key maps to a
    computable function in services.CRITERIA_METRICS — there's no Manual
    precedent for this module (docx-spec only), so the criteria set is a
    reasonable default drawn from data RMIS already tracks, not client-confirmed."""

    name = models.CharField(max_length=150, unique=True)
    metric_key = models.CharField(max_length=30, choices=CRITERIA_METRIC_CHOICES)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class AHPMatrixRun(models.Model):
    """One AHP pairwise-comparison weighting session. `weights` and
    `consistency_ratio` are computed and stored on finalize() — kept as a
    persisted snapshot (not live-recomputed) since a WSM run must be able to
    cite the exact weights that produced its rankings (traceability)."""

    STATUS_CHOICES = (("draft", "Draft"), ("finalized", "Finalized"))

    label = models.CharField(max_length=200)
    criteria = models.ManyToManyField(DecisionCriterion, related_name="ahp_runs")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ahp_runs")
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    weights = models.JSONField(default=dict, blank=True, help_text="{criterion_id: normalized weight}, set on finalize")
    consistency_ratio = models.FloatField(null=True, blank=True)
    is_consistent = models.BooleanField(null=True, blank=True, help_text="True when consistency_ratio <= 0.10")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.label


class AHPPairwiseComparison(models.Model):
    """Saaty 1-9 scale: value = how many times more important criterion_row is
    than criterion_col (values <1 mean col is more important). Only
    criterion_row.id < criterion_col.id pairs are stored — the reciprocal
    entry is derived at compute time, not duplicated in the table."""

    run = models.ForeignKey(AHPMatrixRun, on_delete=models.CASCADE, related_name="comparisons")
    criterion_row = models.ForeignKey(DecisionCriterion, on_delete=models.CASCADE, related_name="+")
    criterion_col = models.ForeignKey(DecisionCriterion, on_delete=models.CASCADE, related_name="+")
    value = models.FloatField(help_text="Saaty scale 1/9-9")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "criterion_row", "criterion_col"], name="unique_ahp_pair_per_run"),
        ]

    def __str__(self):
        return f"run {self.run_id}: {self.criterion_row_id} vs {self.criterion_col_id} = {self.value}"


class FundingRecommendationRun(models.Model):
    """One WSM scoring pass over a candidate set of projects, using a
    finalized AHP run's weights."""

    ahp_run = models.ForeignKey(AHPMatrixRun, on_delete=models.PROTECT, related_name="recommendation_runs")
    label = models.CharField(max_length=200)
    funding_type_filter = models.CharField(max_length=20, blank=True)
    campus_filter = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recommendation_runs")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.label


class ProjectScore(models.Model):
    """One project's WSM result within a FundingRecommendationRun. raw_scores
    and normalized_scores are kept per-criterion for full computational
    traceability, per the docx's explicit requirement."""

    run = models.ForeignKey(FundingRecommendationRun, on_delete=models.CASCADE, related_name="scores")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="decision_scores")
    raw_scores = models.JSONField(default=dict, help_text="{criterion_id: raw computed value}")
    normalized_scores = models.JSONField(default=dict, help_text="{criterion_id: min-max normalized 0-1}")
    composite_score = models.FloatField()
    rank = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "project"], name="unique_project_score_per_run"),
        ]
        ordering = ["rank"]

    def __str__(self):
        return f"run {self.run_id}: {self.project_id} rank {self.rank}"
