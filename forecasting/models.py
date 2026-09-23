from django.conf import settings
from django.db import models

from research_projects.models import Project

FORECASTABLE_FUNDING_TYPES = ("institutional", "externally_funded")


class ForecastRun(models.Model):
    """One ARIMA fit+forecast attempt for a project. Institutional/Externally-funded
    projects only (Core-Funded is excluded per the docx's module scope)."""

    STATUS_CHOICES = (
        ("success", "Success"),
        ("insufficient_data", "Insufficient Data"),
        ("failed", "Failed"),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="forecast_runs")
    run_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="forecast_runs")
    run_at = models.DateTimeField(auto_now_add=True)

    months_of_history = models.PositiveIntegerField(default=0)
    arima_order = models.CharField(max_length=20, blank=True, help_text="(p, d, q) used to fit the model")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    error_message = models.CharField(max_length=300, blank=True)

    # Backtest accuracy (holdout forecast vs. actual) — null when there wasn't
    # enough history to hold months out and still fit a model.
    mae = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    rmse = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    mape = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, help_text="Mean Absolute Percentage Error")

    # Overrun-risk flag: actual-to-date + forecast horizon vs. the current approved budget.
    approved_budget_total = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    actual_to_date = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    projected_total_at_horizon = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    is_overrun_risk = models.BooleanField(default=False)

    class Meta:
        ordering = ["-run_at"]

    def __str__(self):
        return f"{self.project.project_code} forecast run {self.run_at:%Y-%m-%d}"


class MonthlyForecast(models.Model):
    forecast_run = models.ForeignKey(ForecastRun, on_delete=models.CASCADE, related_name="forecasts")
    period = models.DateField()
    predicted_amount = models.DecimalField(max_digits=14, decimal_places=2)
    lower_bound = models.DecimalField(max_digits=14, decimal_places=2)
    upper_bound = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["period"]

    def __str__(self):
        return f"{self.forecast_run_id} - {self.period:%Y-%m}"
