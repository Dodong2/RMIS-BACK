from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from research_projects.models import Project

SCALE = [MinValueValidator(1), MaxValueValidator(5)]


class ProjectRisk(models.Model):
    """Manually identified project risk (DPMIS-based spec Module 14 risk register),
    scored on the same 5x5 Likelihood x Impact scale as the computed triggers."""

    CATEGORY_CHOICES = (
        ("technical", "Technical"),
        ("financial", "Financial"),
        ("schedule", "Schedule"),
        ("personnel", "Personnel"),
        ("compliance", "Compliance"),
        ("procurement", "Procurement"),
        ("other", "Other"),
    )
    STATUS_CHOICES = (
        ("open", "Open"),
        ("mitigating", "Mitigating"),
        ("escalated", "Escalated"),
        ("closed", "Closed"),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="risks")
    description = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    likelihood = models.PositiveSmallIntegerField(validators=SCALE)
    impact = models.PositiveSmallIntegerField(validators=SCALE)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_risks")
    mitigation = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="risks_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def score(self):
        return self.likelihood * self.impact

    def __str__(self):
        return f"{self.project.project_code}: {self.description[:40]} ({self.score})"


class RiskUpdate(models.Model):
    """Monitoring note on a risk; a non-blank new_status also moves the risk (close/escalate)."""

    risk = models.ForeignKey(ProjectRisk, on_delete=models.CASCADE, related_name="updates")
    note = models.TextField()
    new_status = models.CharField(max_length=20, choices=ProjectRisk.STATUS_CHOICES, blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="risk_updates")
    created_at = models.DateTimeField(auto_now_add=True)
