from django.conf import settings
from django.db import models

REPORT_TYPE_CHOICES = (
    ("appendix_e", "Appendix E - Midterm Progress Report"),
    ("appendix_f", "Appendix F - Terminal Report"),
    ("appendix_g", "Appendix G - R&D Accomplishment Report"),
    ("project_list", "Custom Filtered Project List"),
    ("financial", "Financial / Procurement Report"),
    ("compliance", "Compliance Report"),
    ("personnel", "Personnel and Task Report"),
    ("outputs", "Research Outputs (6Ps) Report"),
)
FORMAT_CHOICES = (("csv", "CSV"), ("xlsx", "XLSX"), ("pdf", "PDF"), ("docx", "DOCX"))


class GeneratedReportLog(models.Model):
    """Audit trail of who generated which report, when, with what filters —
    the file itself isn't stored (generated on-demand and streamed back), so
    this is metadata-only, not a document archive (that's Module 7's job)."""

    report_type = models.CharField(max_length=30, choices=REPORT_TYPE_CHOICES)
    format = models.CharField(max_length=10, choices=FORMAT_CHOICES)
    filters = models.JSONField(default=dict, blank=True)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="generated_reports")
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self):
        return f"{self.report_type} ({self.format}) by {self.generated_by_id} at {self.generated_at:%Y-%m-%d %H:%M}"
