from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from research_projects.models import Project, Study

RETENTION_YEARS = 10


class Document(models.Model):
    """A versioned project document, stored in Supabase Storage. Documents are
    never hard-deleted — they're official records with a 10-year retention
    clock per the Manual's Records Office rule; superseded versions are kept
    for history and just marked not-current."""

    TYPE_CHOICES = (
        ("toe", "Terms of Engagement"),
        ("lib", "Line-Item Budget"),
        ("work_plan", "Work Plan"),
        ("midterm_report", "Midterm Report"),
        ("terminal_report", "Terminal Report"),
        ("accomplishment_report", "Accomplishment Report"),
        ("thesis", "Thesis"),
        ("dissertation", "Dissertation"),
        ("dataset", "Research Dataset"),
        ("manuscript", "Manuscript"),
        ("other", "Other"),
    )
    STAGE_CHOICES = (
        ("inception", "Inception"),
        ("midterm", "Midterm"),
        ("terminal", "Terminal"),
        ("post_completion", "Post-Completion"),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="documents")
    study = models.ForeignKey(Study, on_delete=models.CASCADE, null=True, blank=True, related_name="documents")
    document_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, blank=True)

    version_number = models.PositiveIntegerField(editable=False)
    is_current = models.BooleanField(default=True, editable=False)

    storage_path = models.CharField(max_length=500, editable=False)
    file_name = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField(help_text="Size in bytes")
    content_type = models.CharField(max_length=100, blank=True)

    is_archived = models.BooleanField(default=False)
    retention_until = models.DateField(editable=False)

    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="documents_uploaded")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk is None and not self.retention_until:
            self.retention_until = timezone.localdate() + timedelta(days=365 * RETENTION_YEARS)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_document_type_display()} v{self.version_number} - {self.project}"
