from django.conf import settings
from django.db import models


class PlanningTarget(models.Model):
    """A target issued by the Planning Office for a strategic-plan parameter,
    manually entered here so RMIS can compare it against its own tracked
    actuals. RMIS does not compute the Planning Office's own methodology
    (plantilla positions, academic rank weighting, etc.) — only the target
    number and the comparison against what RMIS already records."""

    METRIC_CHOICES = (
        ("completed_projects", "Completed Projects"),
        ("publications", "Publications"),
        ("ip_disclosures", "IP Disclosures"),
        ("budget_utilization_pct", "Budget Utilization %"),
    )

    metric = models.CharField(max_length=30, choices=METRIC_CHOICES)
    campus = models.CharField(max_length=100, blank=True, help_text="Blank = institution-wide")
    target_year = models.PositiveIntegerField()
    target_value = models.DecimalField(max_digits=12, decimal_places=2)

    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="planning_targets_set")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["metric", "campus", "target_year"], name="unique_planning_target"),
        ]

    def __str__(self):
        scope = self.campus or "institution-wide"
        return f"{self.get_metric_display()} {self.target_year} ({scope})"
