from django.conf import settings
from django.db import models

from document_management.models import Document
from research_projects.models import Project


class MonthlyProgressReport(models.Model):
    """Tracks monthly progress-report submissions. A project with a 3-month
    gap since its last submission is flagged for Dean/RIUH notification, and
    a 6-month gap is flagged for termination, per the Manual's renewal rule."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="monthly_reports")
    period = models.DateField(help_text="First day of the month this report covers")
    narrative = models.TextField(blank=True)
    document = models.ForeignKey(
        Document, on_delete=models.SET_NULL, null=True, blank=True, related_name="monthly_reports"
    )
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="monthly_reports_submitted")
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "period"], name="unique_project_monthly_report_period"),
        ]
        ordering = ["-period"]

    def save(self, *args, **kwargs):
        self.period = self.period.replace(day=1)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.project.project_code} - {self.period:%Y-%m}"


class MidtermReport(models.Model):
    """Appendix E — submitted to the RDO in Q3 of a project-year's implementation."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="midterm_reports")
    project_year = models.PositiveIntegerField(default=1, help_text="Which year of a multi-year project this covers")
    narrative = models.TextField(blank=True)
    expenditure_summary = models.TextField(blank=True, help_text="Summary of expenditures per quarter")
    document = models.ForeignKey(
        Document, on_delete=models.SET_NULL, null=True, blank=True, related_name="midterm_reports"
    )
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="midterm_reports_submitted")
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "project_year"], name="unique_project_midterm_year"),
        ]

    def __str__(self):
        return f"{self.project.project_code} midterm Y{self.project_year}"


class TerminalReport(models.Model):
    """Appendix F — submitted once at project end; RDO/RIUH certifies formal termination."""

    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="terminal_report")
    narrative = models.TextField(blank=True)
    document = models.ForeignKey(
        Document, on_delete=models.SET_NULL, null=True, blank=True, related_name="terminal_reports"
    )
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="terminal_reports_submitted")
    submitted_at = models.DateTimeField(auto_now_add=True)

    is_certified = models.BooleanField(default=False)
    certified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="terminal_reports_certified"
    )
    certified_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.project.project_code} terminal report"


class ProjectEvaluation(models.Model):
    """Annual evaluation before a panel of VPRDE/DRD/CRCs sitting en banc,
    scheduled by the RDO roughly a month after the project's termination date."""

    OUTCOME_CHOICES = (
        ("pending", "Pending"),
        ("passed", "Passed"),
        ("conditional", "Conditional"),
        ("failed", "Failed"),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="evaluations")
    project_year = models.PositiveIntegerField(default=1)
    scheduled_date = models.DateField()
    panel_members = models.TextField(blank=True, help_text="Names/roles of panel members, incl. any external member")
    outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES, default="pending")
    remarks = models.TextField(blank=True)

    evaluated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="evaluations_recorded"
    )
    evaluated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "project_year"], name="unique_project_evaluation_year"),
        ]

    def __str__(self):
        return f"{self.project.project_code} evaluation Y{self.project_year}"


class RenewalApplication(models.Model):
    """A multi-year project's request to continue funding into its next year.
    Eligibility (70% budget used, or 70% deliverables done with a justification
    for unspent funds) is computed live, not stored — see serializers.compute_renewal_eligible."""

    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("denied", "Denied"),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="renewal_applications")
    application_year = models.PositiveIntegerField(help_text="The upcoming project-year being applied for")
    underspend_justification = models.TextField(
        blank=True, help_text="Reasonable explanation for unspent funds, if budget usage is below 70%"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="renewal_applications_decided"
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="renewal_applications_submitted")
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "application_year"], name="unique_project_renewal_year"),
        ]

    def __str__(self):
        return f"{self.project.project_code} renewal Y{self.application_year}"
