from django.conf import settings
from django.db import models

from research_projects.models import Project, Study

SIMILARITY_THRESHOLDS = {
    "published_article": 15,
    "thesis_dissertation": 20,
    "other": 20,
}


class EthicsReviewReference(models.Model):
    """Status reference for an external review body's decision. RMIS logs the
    outcome only — TRC/Ethics Review Board/IACUC conduct the actual review."""

    BODY_CHOICES = (
        ("trc", "Technical Review Committee"),
        ("ethics_review_board", "Ethics Review Board"),
        ("iacuc", "Institutional Animal Care and Use Committee"),
    )
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("conditional", "Conditionally Approved"),
        ("revision_required", "Revision Required"),
        ("rejected", "Rejected"),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="ethics_reviews")
    study = models.ForeignKey(Study, on_delete=models.CASCADE, null=True, blank=True, related_name="ethics_reviews")
    review_body = models.CharField(max_length=30, choices=BODY_CHOICES)
    reference_number = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    decision_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ethics_reviews_recorded")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_review_body_display()} - {self.project} ({self.status})"


class SimilarityCheckRecord(models.Model):
    DOCUMENT_TYPE_CHOICES = (
        ("published_article", "Article for Publication"),
        ("thesis_dissertation", "Thesis/Dissertation"),
        ("other", "Other"),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="similarity_checks")
    study = models.ForeignKey(Study, on_delete=models.CASCADE, null=True, blank=True, related_name="similarity_checks")
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES)
    document_title = models.CharField(max_length=300, blank=True)
    similarity_index = models.DecimalField(max_digits=5, decimal_places=2)
    is_within_threshold = models.BooleanField(default=True, editable=False)
    software_used = models.CharField(max_length=100, blank=True)
    checked_on = models.DateField()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="similarity_checks_recorded")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        threshold = SIMILARITY_THRESHOLDS[self.document_type]
        self.is_within_threshold = self.similarity_index <= threshold
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.document_title or self.project} - {self.similarity_index}%"


class AIUseDeclaration(models.Model):
    """AI declaration form, per the Manual's 'Use of Generative AI' section."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="ai_use_declarations")
    study = models.ForeignKey(Study, on_delete=models.CASCADE, null=True, blank=True, related_name="ai_use_declarations")
    declared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ai_use_declarations")
    tool_name = models.CharField(max_length=150)
    purpose = models.CharField(max_length=300, help_text="e.g. grammar editing, data analysis, literature summarization")
    extent = models.TextField(help_text="Description of how and where AI was used in the work")
    declared_on = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tool_name} - {self.project} ({self.declared_by.email})"


class ConflictOfInterestDisclosure(models.Model):
    STATUS_CHOICES = (
        ("disclosed", "Disclosed"),
        ("under_review", "Under Review"),
        ("resolved", "Resolved"),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="coi_disclosures")
    discloser = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="coi_disclosures")
    description = models.TextField()
    mitigation_measures = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="disclosed")
    disclosed_on = models.DateField()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="coi_disclosures_recorded")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"COI - {self.discloser.email} ({self.project})"


class MisconductCaseReference(models.Model):
    """Status reference for a reported misconduct case. RMIS logs the case and its
    outcome only — the Dean (student cases) or Research Chairperson (faculty
    cases) conduct the actual due process, per the Manual."""

    CASE_TYPE_CHOICES = (
        ("plagiarism", "Plagiarism"),
        ("fabrication", "Fabrication"),
        ("falsification", "Falsification"),
        ("other", "Other"),
    )
    STATUS_CHOICES = (
        ("reported", "Reported"),
        ("under_investigation", "Under Investigation"),
        ("upheld", "Upheld"),
        ("dismissed", "Dismissed"),
    )

    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="misconduct_cases")
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="misconduct_cases_against"
    )
    subject_name = models.CharField(max_length=150, blank=True, help_text="Used when the subject is not a system user, e.g. a student")
    case_type = models.CharField(max_length=20, choices=CASE_TYPE_CHOICES)
    referred_to = models.CharField(max_length=150, help_text="e.g. Dean, Research Chairperson")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="reported")
    remarks = models.TextField(blank=True)
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="misconduct_cases_reported")
    reported_on = models.DateField()
    resolved_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_case_type_display()} - {self.subject_name or self.subject} ({self.status})"
