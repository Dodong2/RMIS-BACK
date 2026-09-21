from django.conf import settings
from django.db import models


class Program(models.Model):
    FUNDING_CHOICES = (
        ("institutional", "Institutional (LSPU-Funded)"),
        ("core_funded", "Core-Funded (Self-Funded)"),
        ("externally_funded", "Externally-Funded"),
    )
    STATUS_CHOICES = (
        ("active", "Active"),
        ("completed", "Completed"),
        ("archived", "Archived"),
    )

    code = models.CharField(max_length=50, unique=True, blank=True, null=True)
    title = models.CharField(max_length=300)
    funding_type = models.CharField(max_length=20, choices=FUNDING_CHOICES)
    rei_thrust = models.CharField(max_length=150, blank=True)
    lead = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="led_programs")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    start_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Project(models.Model):
    FUNDING_CHOICES = Program.FUNDING_CHOICES
    STATUS_CHOICES = Program.STATUS_CHOICES

    program = models.ForeignKey(Program, on_delete=models.SET_NULL, null=True, blank=True, related_name="projects")
    title = models.CharField(max_length=300)
    project_code = models.CharField(max_length=50, unique=True)
    funding_type = models.CharField(max_length=20, choices=FUNDING_CHOICES)
    ntp_number = models.CharField(max_length=50, blank=True)
    ntp_date = models.DateField(null=True, blank=True)
    toe_signed_date = models.DateField(null=True, blank=True)
    is_dry_research = models.BooleanField(default=True)
    lead = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="led_projects")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    start_date = models.DateField(null=True, blank=True)
    target_end_date = models.DateField(null=True, blank=True)
    rei_thrust = models.CharField(max_length=150, blank=True)

    # Fields from LSPU-RDO-SF-018 (Research Proposal Form), Section I
    SECTOR_CHOICES = (
        ("agriculture_fisheries", "Agriculture/Fisheries"),
        ("education", "Education"),
        ("community_development", "Community Development"),
        ("information_tech", "Information Tech."),
        ("politics", "Politics"),
        ("others", "Others"),
    )
    RESEARCH_TYPE_CHOICES = (("basic", "Basic Research"), ("applied", "Applied Research"))
    PRIORITY_AREA_CHOICES = (
        ("science_math", "Science and Mathematics"),
        ("education_teacher_training", "Education and Teacher's Training"),
        ("health", "Health and Health Profession"),
        ("ict", "Information and Communication Tech."),
        ("engineering", "Engineering"),
        ("agriculture_fisheries", "Agriculture and Fisheries"),
        ("environmental_science", "Environmental Science"),
        ("social_sciences_humanities", "Social Sciences and Humanities"),
    )
    TYPOLOGY_CHOICES = (
        ("operations", "Operations Research"),
        ("development", "Development Research"),
        ("qualitative", "Qualitative Research"),
        ("quantitative", "Quantitative Research"),
        ("descriptive_survey", "Descriptive/Survey Research"),
        ("laboratory_field", "Laboratory/Field Research"),
        ("quasi_experimental", "Quasi-Experimental Research"),
        ("pure_experimental", "Pure Experimental Research"),
    )

    is_continuing = models.BooleanField(default=False)  # False = New Proposal
    research_type = models.CharField(max_length=10, choices=RESEARCH_TYPE_CHOICES, blank=True)
    sector = models.CharField(max_length=30, choices=SECTOR_CHOICES, blank=True)
    sector_other = models.CharField(max_length=150, blank=True)
    research_priority_area = models.CharField(max_length=40, choices=PRIORITY_AREA_CHOICES, blank=True)
    research_typology = models.JSONField(default=list, blank=True)  # list of TYPOLOGY_CHOICES codes
    sdgs = models.JSONField(default=list, blank=True)  # list of SDG numbers, 1-17
    campus = models.CharField(max_length=100, blank=True)
    implementing_unit = models.CharField(max_length=150, blank=True)
    cooperating_agencies = models.TextField(blank=True)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.project_code} - {self.title}"


class Study(models.Model):
    STATUS_CHOICES = Program.STATUS_CHOICES

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="studies")
    title = models.CharField(max_length=300)
    lead = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="led_studies")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class WorkPlanMilestone(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("in_progress", "In Progress"),
        ("done", "Done"),
        ("delayed", "Delayed"),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    title = models.CharField(max_length=300)
    target_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title