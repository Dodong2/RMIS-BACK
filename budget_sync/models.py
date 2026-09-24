from django.conf import settings
from django.db import models

from research_projects.models import Project


class BudgetOfficeImport(models.Model):
    """One upload of the Budget Office's consolidated LIB workbook (Module 15, Objective 2d).
    RMIS has no live connection to the Budget Office system — sync is by file import + reconciliation."""

    file_name = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="budget_office_imports")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.file_name} ({self.uploaded_at:%Y-%m-%d})"


class BudgetOfficeRecord(models.Model):
    """One project sheet (P1, P2, ...) from an import, linked to the matching RMIS project."""

    MATCH_CHOICES = (("auto", "Matched by title"), ("manual", "Linked manually"), ("", "Unlinked"))

    source = models.ForeignKey(BudgetOfficeImport, on_delete=models.CASCADE, related_name="records")
    sheet_name = models.CharField(max_length=30)
    title = models.TextField()
    leader_name = models.CharField(max_length=200, blank=True)
    implementing_unit = models.CharField(max_length=200, blank=True)
    mooe_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    co_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="budget_office_records")
    match_method = models.CharField(max_length=10, choices=MATCH_CHOICES, blank=True)

    def __str__(self):
        return f"{self.sheet_name}: {self.title[:40]}"
