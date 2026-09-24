from django.conf import settings
from django.db import models

from research_projects.models import Project, Study


class SenseRankedPublisher(models.Model):
    """Reference list of SENSE-ranked book/book-chapter publishers (Manual Appendix Q).
    Maintained by RIUH/system_admin; used to look up book incentive eligibility."""

    name = models.CharField(max_length=200, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class PublicationRecord(models.Model):
    TYPE_CHOICES = (
        ("journal_article", "Journal Article"),
        ("book", "Book"),
        ("book_chapter", "Book Chapter"),
        ("conference_proceeding", "Conference Proceeding"),
        ("instructional_material", "Instructional Material (Workbook/Module/Manual)"),
    )
    INDEXING_CHOICES = (
        ("isi", "ISI-indexed (Web of Science / Clarivate)"),
        ("scopus", "Scopus-indexed"),
        ("lspu_refereed", "LSPU Refereed Research Journal"),
        ("non_indexed", "Not Indexed"),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="publications")
    study = models.ForeignKey(Study, on_delete=models.CASCADE, null=True, blank=True, related_name="publications")
    lead_author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="publications")

    title = models.CharField(max_length=400)
    publication_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    indexing_tier = models.CharField(max_length=20, choices=INDEXING_CHOICES, blank=True)
    impact_factor = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    h_index = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    sense_publisher = models.ForeignKey(
        SenseRankedPublisher, on_delete=models.SET_NULL, null=True, blank=True, related_name="publications"
    )
    has_isbn = models.BooleanField(default=False)
    is_lspu_published = models.BooleanField(default=False)
    is_thesis_derived = models.BooleanField(default=False)
    is_supervised_approved_thesis = models.BooleanField(
        default=False, help_text="Thesis/dissertation was an integral part of a duly approved R&D P/P/S under the author's supervision"
    )

    publisher_name = models.CharField(max_length=200, blank=True)
    doi_or_isbn = models.CharField(max_length=100, blank=True)
    published_on = models.DateField()

    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="publications_recorded")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class IPRecord(models.Model):
    """IP metadata only — RMIS does not manage the actual IP filing workflow."""

    TYPE_CHOICES = (
        ("patent", "Patent"),
        ("utility_model", "Utility Model"),
        ("industrial_design", "Industrial Design"),
        ("trademark", "Trademark"),
    )
    STATUS_CHOICES = (
        ("disclosed", "Disclosed"),
        ("filed", "Filed"),
        ("registered", "Registered"),
        ("adopted", "Adopted by a Recipient Community"),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="ip_records")
    study = models.ForeignKey(Study, on_delete=models.CASCADE, null=True, blank=True, related_name="ip_records")
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ip_records")
    co_creators = models.CharField(max_length=300, blank=True, help_text="Comma-separated names of other creators, if any")

    title = models.CharField(max_length=400)
    ip_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="disclosed")
    trl = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Technology Readiness Level, 1-9")
    is_commercialization_intended = models.BooleanField(default=False)
    is_adopted_by_community = models.BooleanField(default=False)
    adoption_moa_reference = models.CharField(max_length=200, blank=True)

    registration_number = models.CharField(max_length=100, blank=True)
    registered_on = models.DateField(null=True, blank=True)
    incentive_claimed = models.BooleanField(default=False, help_text="Incentive is given only once per patent/utility model")

    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ip_records_recorded")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_ip_type_display()} - {self.title}"


class CreativeWorkRecord(models.Model):
    """Per the Creative Works Management Unit's mandate: manage/protect/promote
    creative works produced by faculty, staff and students."""

    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="creative_works")
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="creative_works")

    title = models.CharField(max_length=400)
    work_type = models.CharField(max_length=100, help_text="e.g. digital art, literary work, software, multimedia")
    description = models.TextField(blank=True)
    date_created = models.DateField()
    is_registered = models.BooleanField(default=False, help_text="Rights/ownership registration status")
    rights_holder = models.CharField(max_length=200, blank=True)

    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="creative_works_recorded")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


SIX_PS = (
    ("publications", "Publications"),
    ("patents", "Patents / IP"),
    ("products", "Products"),
    ("people_services", "People Services"),
    ("places_partnerships", "Places and Partnerships"),
    ("policies", "Policies"),
)


class ExpectedOutput(models.Model):
    """Expected deliverable per DOST 6Ps category (client clarification Q11 — DOST standard, RDO to confirm).
    Actual count is computed from PublicationRecord / IPRecord for publications/patents, and entered
    manually for the other four Ps, which have no dedicated record type in RMIS."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="expected_outputs")
    category = models.CharField(max_length=30, choices=SIX_PS)
    description = models.CharField(max_length=300)
    target_count = models.PositiveIntegerField(default=1)
    manual_actual_count = models.PositiveIntegerField(default=0, help_text="Used for products/people/places/policies")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.project.project_code}: {self.get_category_display()} x{self.target_count}"


class ProjectOutcome(models.Model):
    """Observed outcome or impact of a project (DPMIS-based spec ROM-07)."""

    KIND_CHOICES = (("outcome", "Outcome"), ("impact", "Impact"))

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="outcomes")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    description = models.TextField()
    observed_on = models.DateField(null=True, blank=True)
    evidence = models.TextField(blank=True, help_text="Where this is documented (report, MOA, news, etc.)")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="outcomes_recorded")
    created_at = models.DateTimeField(auto_now_add=True)
