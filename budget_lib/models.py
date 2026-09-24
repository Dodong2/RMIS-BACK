from django.conf import settings
from django.db import models

from research_projects.models import Project

# Manual Art. III 1: max P100,000/year for institutionally-funded dry research. Advisory only
# (client decision 2026-09-24): real LIBs like sheet P77 (P120k) exceed it, so it's flagged, not rejected.
INSTITUTIONAL_DRY_RESEARCH_CAP = 100000
APP_FLAG_THRESHOLD = 50000


class LineItemBudget(models.Model):
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("certified", "Certified"),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="budgets")
    version_number = models.PositiveIntegerField()
    is_current = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    certified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="certified_budgets"
    )
    certified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "version_number"], name="unique_project_budget_version"),
        ]

    def __str__(self):
        return f"{self.project.project_code} budget v{self.version_number}"


class LineItem(models.Model):
    CATEGORY_CHOICES = (
        ("ps", "Personal Services"),
        ("mooe", "Maintenance and Other Operating Expenses"),
        ("co", "Capital Outlay"),
    )

    budget = models.ForeignKey(LineItemBudget, on_delete=models.CASCADE, related_name="line_items")
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    description = models.CharField(max_length=300)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    # DPMIS-based spec BM-02/04/05: annual allocation, funding source, counterpart funding
    fiscal_year = models.PositiveIntegerField(null=True, blank=True)
    funding_source = models.CharField(max_length=150, blank=True, help_text="e.g. LSPU GAA, DOST-PCAARRD, LGU")
    is_counterpart = models.BooleanField(default=False, help_text="Counterpart (institutional share) funding")
    is_app_flagged = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        self.is_app_flagged = self.amount > APP_FLAG_THRESHOLD
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_category_display()} - {self.description}"
