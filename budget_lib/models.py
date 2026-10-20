from django.conf import settings
from django.db import models

from research_projects.models import Project

# Manual Art. III 1: max P100,000/year for institutionally-funded dry research. Advisory only
# (client decision 2026-09-24): real LIBs like sheet P77 (P120k) exceed it, so it's flagged, not rejected.
INSTITUTIONAL_DRY_RESEARCH_CAP = 100000
APP_FLAG_THRESHOLD = 50000


def allocation_periods(project):
    """LIB allocation periods: the quarters the project covers, counted from its start date (client meeting 2026-10-14
    + yearly.png, 2026-10-17). Q1..Qk for a project of 12 months or less, Y1Q1..YnQm (each project year's quarters)
    for a longer one; 8 months = Q1-Q3, 15 months = Y1Q1-Y1Q4 + Y2Q1. None until both start and target end dates are set."""
    start, end = project.start_date, project.target_end_date
    if not start or not end or end < start:
        return None
    months = (end.year - start.year) * 12 + end.month - start.month + (1 if end.day >= start.day else 0)
    quarters = (months + 2) // 3
    if months <= 12:
        return [f"Q{n}" for n in range(1, quarters + 1)]
    return [f"Y{i // 4 + 1}Q{i % 4 + 1}" for i in range(quarters)]


class LineItemBudget(models.Model):
    # Client 2026-10-18: CRC Chair endorses, then the Budget Officer certifies; either one can return it to the
    # Project Leader, who edits and resubmits (back to draft). Only draft/returned LIBs can be edited.
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("endorsed", "Endorsed by CRC Chair"),
        ("returned", "Returned for Revision"),
        ("certified", "Certified"),
    )
    EDITABLE_STATUSES = ("draft", "returned")

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="budgets")
    version_number = models.PositiveIntegerField()
    is_current = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    certified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="certified_budgets"
    )
    certified_at = models.DateTimeField(null=True, blank=True)
    endorsed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="endorsed_budgets"
    )
    endorsed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "version_number"], name="unique_project_budget_version"),
        ]

    def __str__(self):
        return f"{self.project.project_code} budget v{self.version_number}"


class BudgetReview(models.Model):
    """One row per endorsement step on a LIB (client 2026-10-18: full history of every return and resubmit)."""

    ACTION_CHOICES = (
        ("endorsed", "Endorsed"),
        ("returned", "Returned for Revision"),
        ("resubmitted", "Resubmitted"),
        ("certified", "Certified"),
    )

    budget = models.ForeignKey(LineItemBudget, on_delete=models.CASCADE, related_name="reviews")
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    remarks = models.TextField(blank=True)
    acted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="budget_reviews")
    acted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["acted_at", "id"]

    def __str__(self):
        return f"{self.budget}: {self.action}"


class LineItem(models.Model):
    CATEGORY_CHOICES = (
        ("ps", "Personal Services"),
        ("mooe", "Maintenance and Other Operating Expenses"),
        ("co", "Capital Outlay"),
    )
    UNIT_CHOICES = (
        ("unit", "unit"), ("month", "month"), ("lump_sum", "lump sum"), ("pax", "pax"),
        ("lot", "lot"), ("set", "set"), ("hr", "hr"),
    )

    budget = models.ForeignKey(LineItemBudget, on_delete=models.CASCADE, related_name="line_items")
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    description = models.CharField(max_length=300)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    # Client feedback 2026-10-06: registration LIB rows are Unit / Qty / Unit Cost, and amount = quantity x unit_cost
    unit = models.CharField(max_length=10, choices=UNIT_CHOICES, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    # DPMIS-based spec BM-02/04/05: annual allocation, funding source, counterpart funding
    fiscal_year = models.PositiveIntegerField(null=True, blank=True)
    funding_source = models.CharField(max_length=150, blank=True, help_text="e.g. LSPU GAA, DOST-PCAARRD, LGU")
    is_counterpart = models.BooleanField(default=False, help_text="Counterpart (institutional share) funding")
    # Client request 2026-10-07: the Line Items tab has a Justification column per item
    justification = models.TextField(blank=True)
    # Old LSPU-RDO-SF-018 Section X quarterly breakdown (kept for older LIBs); optional, must add up to amount when given
    q1_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    q2_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    q3_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    q4_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    # Client meeting 2026-10-14 + yearly.png: the item's total split over allocation_periods(project), Y1Q1..YnQ4 or
    # Q1..Q4. [{"period": "Y1Q1", "amount": "5000.00"}, ...]; must add up to amount.
    allocations = models.JSONField(default=list, blank=True)
    is_app_flagged = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        self.is_app_flagged = self.amount > APP_FLAG_THRESHOLD
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_category_display()} - {self.description}"


class LibItem(models.Model):
    """An LIB Item the System Admin maintains under one fixed class (client 2026-10-20), e.g. "Honoraria" under PS.
    Line items pick from the active ones and keep the name as text, so renaming or deactivating an item never changes
    an LIB already encoded."""

    category = models.CharField(max_length=10, choices=LineItem.CATEGORY_CHOICES)
    name = models.CharField(max_length=300)
    uacs_code = models.CharField(max_length=20, blank=True, help_text="DBM UACS object code, e.g. 5010210000")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "name"]
        constraints = [models.UniqueConstraint(fields=["category", "name"], name="unique_lib_item_per_class")]

    def __str__(self):
        return f"{self.get_category_display()} - {self.name}"
